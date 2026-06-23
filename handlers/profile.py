"""
Профиль пользователя и пополнение баланса.
"""

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import get_settings
from handlers.registration import start_registration
from keyboards import (
    back_kb,
    back_to_menu_kb,
    payment_kb,
    profile_kb,
    topup_methods_kb,
    topup_wallets_kb,
)
from models import User
from services.balance_service import BalanceService
from services.order_service import OrderService
from services.user_service import UserService
from states import TopUpStates, VIPPurchaseStates
from utils import escape, format_price, format_price_crypto, validate_price

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
    from services.vip_service import VIPService
    is_vip = await VIPService.is_vip(user)
    try:
        await callback.message.edit_text(
            _profile_text(user),
            reply_markup=profile_kb(is_vip=is_vip),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            _profile_text(user),
            reply_markup=profile_kb(is_vip=is_vip),
            parse_mode="HTML",
        )
    await callback.answer()


# ── Обычное пополнение баланса ──────────────────────────────────

@router.callback_query(F.data == "profile:topup")
async def cb_topup_start(callback: CallbackQuery, state: FSMContext):
    """Начало пополнения баланса."""
    await state.clear()
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
    """Пользователь ввёл сумму — выбрать способ оплаты."""
    amount = validate_price(message.text)
    if amount is None:
        await message.answer("❌ Введите корректную сумму (число больше 0):")
        return

    await state.update_data(topup_amount=amount, is_vip_purchase=False)
    await state.set_state(TopUpStates.receipt)

    await message.answer(
        f"💳 <b>Способ оплаты</b>\n\n"
        f"Сумма: {format_price(amount)}\n\n"
        "Выберите способ:",
        reply_markup=topup_methods_kb(),
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
    """Неверный формат чека / выбор способа ещё не сделан."""
    await message.answer(
        "📎 Отправьте чек об оплате — фото или документ (PDF), "
        "либо выберите способ оплаты выше."
    )
async def _process_receipt(
    message: Message, state: FSMContext, db_user: User, file_id: str, receipt_type: str
):
    """Сохранить заявку на ручную проверку и уведомить администраторов."""
    data = await state.get_data()
    amount = data.get("topup_amount", 0)
    is_vip_purchase = data.get("is_vip_purchase", False)
    await state.clear()

    topup = await BalanceService.create_topup(
        user_id=db_user.id,
        amount=amount,
        receipt_file_id=file_id,
        receipt_type=receipt_type,
    )

    # If this is a VIP purchase, store additional metadata
    if is_vip_purchase:
        from database import get_db
        async with get_db() as db:
            await db.execute(
                "UPDATE balance_topups SET receipt_type = ? WHERE id = ?",
                (f"vip_{receipt_type}", topup.id),
            )

    await message.answer(
        "✅ <b>Чек отправлен на проверку</b>\n\n"
        f"Сумма: {format_price(amount)}\n"
        f"Заявка №{topup.id}\n\n"
        "После подтверждения администратором баланс будет начислен." +
        ("\n\n⭐ После подтверждения VIP будет активирован." if is_vip_purchase else ""),
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


# ── Способ оплаты (общий для обычного пополнения и покупки VIP) ──

@router.callback_query(F.data.startswith("topup:method:"))
async def cb_topup_method(callback: CallbackQuery, state: FSMContext, db_user: User):
    """Обработка выбора способа пополнения."""
    method = callback.data.split(":")[2]
    data = await state.get_data()
    amount = data.get("topup_amount", 0)
    is_vip_purchase = data.get("is_vip_purchase", False)

    if not amount or amount <= 0:
        await callback.answer("Сессия истекла, начните заново", show_alert=True)
        return

    if method == "crypto":
        from services.crypto_payment import CryptoPaymentService

        settings = get_settings()
        if not settings.CRYPTO_ENABLED:
            await callback.answer("Crypto отключён", show_alert=True)
            return

        # Конвертация RUB -> USDT
        crypto_amount = round(amount / settings.CRYPTO_USDT_RATE, 2)

        crypto = CryptoPaymentService()
        payload = f"vip_{db_user.id}" if is_vip_purchase else f"balance_{db_user.id}"

        try:
            invoice = await crypto.create_invoice(
                amount=crypto_amount,
                description=f"Пополнение баланса: {amount} ₽",
                payload=payload,
            )
            invoice_id = str(invoice["invoice_id"])
            pay_url = invoice["bot_invoice_url"]
            # Сохраняем инвойс и связанную заявку на пополнение (для логирования
            # и для того, чтобы избежать двойного зачисления одной оплаты).
            from database import get_db
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO crypto_invoices (user_id, invoice_id, amount, asset, status)
                       VALUES (?, ?, ?, ?, 'active')""",
                    (db_user.id, invoice_id, crypto_amount, settings.CRYPTO_ASSET),
                )
                await db.execute(
                    """INSERT INTO balance_topups
                       (user_id, amount, status, receipt_type, crypto_invoice_id)
                       VALUES (?, ?, 'pending', ?, ?)""",
                    (
                        db_user.id,
                        amount,
                        "vip_crypto" if is_vip_purchase else "crypto",
                        invoice_id,
                    ),
                )

            await state.clear()

            text = (
                "━━━━━━━━━━━━━━━\n"
                "💎 <b>Оплата криптовалютой</b>\n\n"
                f"💰 Сумма пополнения: {format_price(amount)}\n"
                f"💳 К оплате: {format_price_crypto(crypto_amount, settings.CRYPTO_ASSET)}\n\n"
                "Нажмите кнопку ниже для оплаты, а затем «Проверить оплату».\n"
                "Зачисление баланса произойдёт автоматически.\n"
                "━━━━━━━━━━━━━━━"
            )
            await callback.message.edit_text(
                text,
                reply_markup=payment_kb(pay_url, invoice_id),
                parse_mode="HTML",
            )
            await callback.answer()

        except Exception as e:
            logger.error("Ошибка Crypto инвойса для пополнения: %s", e)
            await callback.answer(f"Ошибка: {e}", show_alert=True)

    elif method == "manual":
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

        await callback.message.edit_text(
            f"💳 <b>Пополнение на {format_price(amount)}</b>\n\n"
            f"Переведите указанную сумму на один из кошельков:\n\n"
            f"{wallets_text}\n\n"
            f"📎 После оплаты отправьте <b>чек</b> (фото или документ).{support}",
            reply_markup=topup_wallets_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
    else:
        await callback.answer("Неизвестный способ оплаты", show_alert=True)


# ── VIP handlers ───────────────────────────────────────────────

@router.callback_query(F.data == "vip:info")
async def cb_vip_info(callback: CallbackQuery, db_user: User):
    """Информация о VIP-доступе."""
    from services.vip_service import VIPService

    user = await UserService.get_by_telegram_id(db_user.telegram_id)
    is_vip = await VIPService.is_vip(user)
    status_text = await VIPService.get_vip_status_text(user)

    builder = InlineKeyboardBuilder()
    if is_vip:
        builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:profile"))
    else:
        builder.row(
            InlineKeyboardButton(text="⭐ Купить VIP", callback_data="vip:buy"),
        )
        builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:profile"))

    try:
        await callback.message.edit_text(
            status_text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            status_text,
            reply_markup=builder.as_markup(),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "vip:buy")
async def cb_vip_buy(callback: CallbackQuery, db_user: User, state: FSMContext):
    """Начало покупки VIP (отдельный FSM-флоу, не пересекается с обычным
    пополнением баланса и с настройками VIP в админ-панели)."""
    from services.vip_service import VIPService

    settings = await VIPService.get_settings()
    if not settings.enabled:
        await callback.answer("VIP-доступ отключён", show_alert=True)
        return

    await state.clear()
    await state.set_state(VIPPurchaseStates.amount)

    await callback.message.edit_text(
        f"⭐ <b>Покупка VIP-доступа</b>\n\n"
        f"💰 Стоимость: {format_price(settings.price)}\n"
        f"🎁 Скидка на все товары: {settings.discount_percent}%\n\n"
        f"Введите сумму пополнения (минимум {format_price(settings.price)}):",
        reply_markup=back_kb("menu:profile"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(VIPPurchaseStates.amount)
async def on_vip_amount(message: Message, state: FSMContext, db_user: User):
    """Пользователь ввёл сумму для VIP — выбрать способ оплаты."""
    amount = validate_price(message.text)
    if amount is None:
        await message.answer("❌ Введите корректную сумму (число больше 0):")
        return

    from services.vip_service import VIPService
    vip_settings = await VIPService.get_settings()

    if amount < vip_settings.price:
        await message.answer(
            f"❌ Минимальная сумма для VIP: {format_price(vip_settings.price)}\n"
            f"Вы ввели: {format_price(amount)}"
        )
        return

    await state.update_data(topup_amount=amount, is_vip_purchase=True)
    await state.set_state(TopUpStates.receipt)

    await message.answer(
        f"💳 <b>Способ оплаты</b>\n\n"
        f"Сумма: {format_price(amount)}\n\n"
        "Выберите способ:",
        reply_markup=topup_methods_kb(),
        parse_mode="HTML",
    )