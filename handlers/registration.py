"""
Регистрация пользователя: страна → зона → город.
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from data.countries import COUNTRIES, ZONE_DESCRIPTION
from keyboards import cities_kb, countries_kb, main_menu_kb
from models import User
from services.user_service import UserService
from states import RegistrationStates

logger = logging.getLogger(__name__)
router = Router(name="registration")


async def start_registration(message: Message, state: FSMContext) -> None:
    """Начать процесс регистрации."""
    await state.set_state(RegistrationStates.country)
    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Для начала работы пройдите короткую регистрацию.\n\n"
        "🌍 Выберите вашу страну:",
        reply_markup=countries_kb(),
        parse_mode="HTML",
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
    await UserService.complete_registration(db_user.telegram_id, country_name, city)
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
