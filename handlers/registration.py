"""
Регистрация пользователя: CAPTCHA → страна → зона → город.
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from config import get_settings
from data.countries import COUNTRIES, ZONE_DESCRIPTION
from keyboards import captcha_kb, cities_kb, countries_kb, main_menu_kb
from models import User
from services.captcha_service import (
    CAPTCHA_MAX_ATTEMPTS,
    new_captcha,
    verify_captcha,
)
from services.referral_service import ReferralService
from services.user_service import UserService
from states import RegistrationStates

logger = logging.getLogger(__name__)
router = Router(name="registration")


async def _send_captcha(message: Message, state: FSMContext) -> None:
    code, image_bytes = new_captcha()
    await state.update_data(captcha_code=code, captcha_attempts=0)
    await state.set_state(RegistrationStates.captcha)
    await message.answer_photo(
        photo=BufferedInputFile(image_bytes, filename="captcha.png"),
        caption=(
            "🛡 <b>Проверка безопасности</b>\n\n"
            "Введите символы с изображения (буквы и цифры).\n"
            f"Попыток: {CAPTCHA_MAX_ATTEMPTS}"
        ),
        reply_markup=captcha_kb(),
        parse_mode="HTML",
    )


async def start_registration(message: Message, state: FSMContext) -> None:
    """Начать процесс регистрации с CAPTCHA."""
    await _send_captcha(message, state)


@router.callback_query(F.data == "reg:captcha_refresh")
async def cb_reg_captcha_refresh(callback: CallbackQuery, state: FSMContext):
    code, image_bytes = new_captcha()
    await state.update_data(captcha_code=code, captcha_attempts=0)
    await callback.message.delete()
    await callback.message.answer_photo(
        photo=BufferedInputFile(image_bytes, filename="captcha.png"),
        caption=(
            "🛡 <b>Новая CAPTCHA</b>\n\n"
            "Введите символы с изображения.\n"
            f"Попыток: {CAPTCHA_MAX_ATTEMPTS}"
        ),
        reply_markup=captcha_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(RegistrationStates.captcha)
async def msg_reg_captcha(message: Message, state: FSMContext):
    data = await state.get_data()
    expected = data.get("captcha_code", "")
    attempts = int(data.get("captcha_attempts", 0)) + 1

    if verify_captcha(message.text or "", expected):
        await state.set_state(RegistrationStates.country)
        await message.answer(
            "✅ Проверка пройдена!\n\n"
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Для начала работы пройдите короткую регистрацию.\n\n"
            "🌍 Выберите вашу страну:",
            reply_markup=countries_kb(),
            parse_mode="HTML",
        )
        return

    if attempts >= CAPTCHA_MAX_ATTEMPTS:
        await message.answer(
            "❌ Превышено число попыток. Генерируем новую CAPTCHA..."
        )
        await _send_captcha(message, state)
        return

    await state.update_data(captcha_attempts=attempts)
    remaining = CAPTCHA_MAX_ATTEMPTS - attempts
    await message.answer(
        f"❌ Неверный код. Осталось попыток: {remaining}\n"
        "Попробуйте снова или обновите изображение.",
        reply_markup=captcha_kb(),
    )


@router.callback_query(F.data.startswith("reg:country:"))
async def cb_reg_country(callback: CallbackQuery, state: FSMContext):
    """Выбор страны — показ зоны работы и выбор города."""
    country_key = callback.data.split(":")[2]
    country_name = COUNTRIES.get(country_key, country_key)
    await state.update_data(country_key=country_key, country_name=country_name)
    await state.set_state(RegistrationStates.city)

    text = (
        f"✅ Страна: <b>{country_name}</b>\n\n"
        f"{ZONE_DESCRIPTION}\n\n"
        "🏙 Выберите ваш город:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=cities_kb(country_key),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "reg:back_country")
async def cb_reg_back_country(callback: CallbackQuery, state: FSMContext):
    """Назад к выбору страны."""
    await state.set_state(RegistrationStates.country)
    await callback.message.edit_text(
        "🌍 Выберите вашу страну:",
        reply_markup=countries_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reg:city:"))
async def cb_reg_city(callback: CallbackQuery, state: FSMContext, db_user: User):
    """Выбор города из списка или «Другой город»."""
    city = callback.data.split(":", 2)[2]
    if city == "other":
        await state.set_state(RegistrationStates.city_manual)
        await callback.message.edit_text(
            "✏️ Введите название вашего города:",
            reply_markup=None,
        )
        await callback.answer()
        return

    await _finish_registration(callback.message, state, db_user, city, edit=True)
    await callback.answer()


@router.message(RegistrationStates.city_manual)
async def on_city_manual(message: Message, state: FSMContext, db_user: User):
    """Ручной ввод города."""
    city = message.text.strip()
    if len(city) < 2:
        await message.answer("❌ Введите корректное название города:")
        return
    await _finish_registration(message, state, db_user, city)


async def _finish_registration(
    message: Message,
    state: FSMContext,
    db_user: User,
    city: str,
    edit: bool = False,
) -> None:
    """Сохранить регистрацию и показать главное меню."""
    data = await state.get_data()
    country_name = data.get("country_name", "—")
    updated_user = await UserService.complete_registration(db_user.telegram_id, country_name, city)
    await state.clear()

    text = (
        f"✅ <b>Регистрация завершена!</b>\n\n"
        f"🌍 {country_name}\n"
        f"🏙 {city}\n\n"
        "Выберите раздел:"
    )
    if edit:
        await message.edit_text(text, reply_markup=main_menu_kb(db_user.is_admin), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=main_menu_kb(db_user.is_admin), parse_mode="HTML")

    user = updated_user or db_user
    referral_result = None
    try:
        referral_result = await ReferralService.confirm_referral(user.id)
    except Exception as e:
        logger.error("Ошибка засчёта реферала для user_id=%s: %s", user.id, e)

    if referral_result and referral_result.confirmed:
        await _notify_referrer(message.bot, referral_result)

    logger.info(
        "Новый пользователь после регистрации: telegram_id=%s username=%s country=%s city=%s",
        user.telegram_id, user.username, country_name, city,
    )
    await _notify_admins_new_user(message.bot, user, country_name, city, referral_result)


async def _notify_referrer(bot, referral_result) -> None:
    """Уведомить пригласившего о засчитанном реферале и о награде, если она выдана."""
    if not referral_result.referrer_telegram_id:
        return
    try:
        await bot.send_message(
            referral_result.referrer_telegram_id,
            "🎉 По вашей реферальной ссылке зарегистрировался новый пользователь!\n\n"
            f"📈 Приглашено: {referral_result.new_referral_count}",
            parse_mode="HTML",
        )
    except Exception as e:
        logger.error(
            "Не удалось уведомить реферера %s о засчитанном реферале: %s",
            referral_result.referrer_telegram_id, e,
        )

    if referral_result.reward_granted:
        try:
            await bot.send_message(
                referral_result.referrer_telegram_id,
                "🎁 <b>Поздравляем!</b>\n\n"
                f"Вы пригласили {referral_result.new_referral_count} пользователей "
                "и получили промокод:\n\n"
                f"🎟 <code>{referral_result.reward_promo_code}</code>\n"
                f"💰 Номинал: {referral_result.reward_amount:g} ₽\n\n"
                "Активируйте его в разделе «🎁 Промокоды».",
                parse_mode="HTML",
            )
            logger.info(
                "Уведомление о выдаче промокода отправлено: referrer_telegram_id=%s code=%s",
                referral_result.referrer_telegram_id, referral_result.reward_promo_code,
            )
        except Exception as e:
            logger.error(
                "Не удалось уведомить реферера %s о выдаче промокода: %s",
                referral_result.referrer_telegram_id, e,
            )


async def _notify_admins_new_user(bot, user: User, country: str, city: str, referral_result) -> None:
    """Уведомить администраторов о каждом новом зарегистрированном пользователе."""
    settings = get_settings()
    username = f"@{user.username}" if user.username else "—"

    referrer_line = ""
    if referral_result and referral_result.confirmed:
        referrer = await UserService.get_by_id(referral_result.referrer_user_id)
        if referrer:
            ref_username = f"@{referrer.username}" if referrer.username else "—"
            referrer_line = (
                f"\n👥 Приглашён пользователем: {ref_username} "
                f"(<code>{referrer.telegram_id}</code>), "
                f"всего рефералов: {referral_result.new_referral_count}"
            )

    text = (
        "🆕 <b>Новый зарегистрированный пользователь</b>\n\n"
        f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
        f"🔗 Username: {username}\n"
        f"📛 Имя: {user.full_name or '—'}\n"
        f"🌍 Страна: {country}\n"
        f"🏙 Город: {city}\n"
        f"📅 Дата: {user.created_at or '—'}"
        f"{referrer_line}"
    )

    admin_ids = set(settings.admin_ids)
    admins = await UserService.get_all_admins()
    for a in admins:
        admin_ids.add(a.telegram_id)
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as e:
            logger.error("Не удалось уведомить админа %s о новом пользователе: %s", admin_id, e)
