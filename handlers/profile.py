"""
Профиль пользователя и пополнение баланса.
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import get_settings
from handlers.registration import start_registration
from keyboards import back_to_menu_kb, profile_kb, topup_wallets_kb
from models import User
from services.balance_service import BalanceService
from services.order_service import OrderService
from services.user_service import UserService
from states import TopUpStates
from utils import escape, format_price, validate_price

logger = logging.getLogger(__name__)
router = Router(name="profile")


def _profile_text(user: User) -> str:
    username = f"@{user.username}" if user.username else "—"
    return (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{user.telegram_id}</code>\n"
        f"🔗 Username: {username}\n"
        f"💰 Баланс: {format_price(user.balance)}"
    )


@router.callback_query(F.data == "menu:profile")
async def cb_profile(callback: CallbackQuery, db_user: User, state: FSMContext):
    """Раздел профиля."""
    if not db_user.is_registered:
        await callback.answer("Сначала пройдите регистрацию", show_alert=True)
        await start_registration(callback.message, state)
        return

    user = await UserService.get_by_telegram_id(db_user.telegram_id)
    try:
        await callback.message.edit_text(
            _profile_text(user),
            reply_markup=profile_kb(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            _profile_text(user),
            reply_markup=profile_kb(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "profile:topup")
async def cb_topup_start(callback: CallbackQuery, state: FSMContext):
    """Начало пополнения баланса."""
    await state.set_state(TopUpStates.amount)
    await callback.message.edit_text(
        "💳 <b>Пополнение баланса</b>\n\n"
        "Введите сумму пополнения в <b>рублях</b> (число):",
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TopUpStates.amount)
async def on_topup_amount(message: Message, state: FSMContext):
    """Пользователь ввёл сумму — показать реквизиты."""
    amount = validate_price(message.text)
    if amount is None:
        await message.answer("❌ Введите корректную сумму (число больше 0):")
        return

    await state.update_data(topup_amount=amount)
    await state.set_state(TopUpStates.receipt)

    wallets = await OrderService.get_wallets(active_only=True)
    lines = []
    for w in wallets:
        lines.append(f"💼 <b>{escape(w['network'])}</b>\n<code>{escape(w['address'])}</code>")

    if lines:
        wallets_text = "\n\n".join(lines)
    else:
        wallets_text = "⚠️ Реквизиты пока не настроены. Обратитесь в поддержку."

    settings = get_settings()
    support = f"\n\nПоддержка: @{settings.SUPPORT_USERNAME}" if settings.SUPPORT_USERNAME else ""

    await message.answer(
        f"💳 <b>Пополнение на {format_price(amount)}</b>\n\n"
        f"Переведите указанную сумму на один из кошельков:\n\n"
        f"{wallets_text}\n\n"
        f"📎 После оплаты отправьте <b>чек</b> (фото или документ).{support}",
        reply_markup=topup_wallets_kb(),
        parse_mode="HTML",
    )


@router.message(TopUpStates.receipt, F.photo)
async def on_topup_receipt_photo(message: Message, state: FSMContext, db_user: User):
    """Получен чек (фото)."""
    file_id = message.photo[-1].file_id
    await _process_receipt(message, state, db_user, file_id, "photo")


@router.message(TopUpStates.receipt, F.document)
async def on_topup_receipt_doc(message: Message, state: FSMContext, db_user: User):
    """Получен чек (документ)."""
    await _process_receipt(message, state, db_user, message.document.file_id, "document")


@router.message(TopUpStates.receipt)
async def on_topup_receipt_invalid(message: Message):
    """Неверный формат чека."""
    await message.answer("📎 Отправьте чек об оплате — фото или документ (PDF).")


async def _process_receipt(
    message: Message, state: FSMContext, db_user: User, file_id: str, receipt_type: str
):
    """Сохранить заявку и уведомить администраторов."""
    data = await state.get_data()
    amount = data.get("topup_amount", 0)
    await state.clear()

    topup = await BalanceService.create_topup(
        user_id=db_user.id,
        amount=amount,
        receipt_file_id=file_id,
        receipt_type=receipt_type,
    )

    await message.answer(
        "✅ <b>Чек отправлен на проверку</b>\n\n"
        f"Сумма: {format_price(amount)}\n"
        f"Заявка №{topup.id}\n\n"
        "После подтверждения администратором баланс будет начислен.",
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
    )

    await _notify_admins_topup(message.bot, db_user, topup.id, amount, file_id, receipt_type)


async def _notify_admins_topup(bot, db_user: User, topup_id: int, amount: float, file_id: str, receipt_type: str):
    """Отправить чек администраторам."""
    from keyboards import topup_approve_kb

    settings = get_settings()
    username = f"@{db_user.username}" if db_user.username else "—"
    caption = (
        f"💳 <b>Заявка на пополнение #{topup_id}</b>\n\n"
        f"👤 ID: <code>{db_user.telegram_id}</code>\n"
        f"🔗 {username}\n"
        f"💰 Сумма: {format_price(amount)}"
    )

    admin_ids = set(settings.admin_ids)
    admins = await UserService.get_all_admins()
    for a in admins:
        admin_ids.add(a.telegram_id)

    for admin_id in admin_ids:
        try:
            if receipt_type == "photo":
                await bot.send_photo(
                    admin_id, file_id, caption=caption,
                    reply_markup=topup_approve_kb(topup_id),
                    parse_mode="HTML",
                )
            else:
                await bot.send_document(
                    admin_id, file_id, caption=caption,
                    reply_markup=topup_approve_kb(topup_id),
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.error("Не удалось уведомить админа %s: %s", admin_id, e)
