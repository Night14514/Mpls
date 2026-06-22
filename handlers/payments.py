"""
Обработка платежей: Crypto Bot, ручные переводы.
"""

import json
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import get_settings
from database import get_db
from keyboards import back_to_menu_kb, admin_order_confirm_kb, manual_paid_kb, payment_kb, wallets_kb
from models import User
from services.crypto_payment import CryptoPaymentService
from services.order_service import OrderService, STATUS_WAITING
from services.product_service import ProductService
from states import ManualPaymentStates
from utils import format_price_crypto, validate_tx_hash

logger = logging.getLogger(__name__)
router = Router(name="payments")


# ── Покупка одного товара Crypto ────────────────────────────

@router.callback_query(F.data.startswith("buy_crypto:"))
async def cb_buy_crypto(callback: CallbackQuery, db_user: User):
    """Оплата одного товара через Crypto Bot."""
    settings = get_settings()
    if not settings.CRYPTO_ENABLED:
        await callback.answer("Crypto отключён", show_alert=True)
        return

    product_id = int(callback.data.split(":")[1])
    product = await ProductService.get_product(product_id)
    if not product:
        await callback.answer("Товар не найден", show_alert=True)
        return

    order = await OrderService.create_order(
        user_id=db_user.id,
        product_id=product_id,
        price=product.price,
        payment_method="crypto",
        status=STATUS_WAITING,
    )

    await _send_crypto_invoice(callback, db_user, order.id, product.title, product.price)


# ── Оформление корзины ───────────────────────────────────────

@router.callback_query(F.data == "checkout:crypto")
async def cb_checkout_crypto(callback: CallbackQuery, db_user: User):
    """Оплата корзины Crypto."""
    settings = get_settings()
    if not settings.CRYPTO_ENABLED:
        await callback.answer("Crypto отключён", show_alert=True)
        return

    _, total, count = await ProductService.cart_total(db_user.id)
    if count == 0:
        await callback.answer("Корзина пуста", show_alert=True)
        return

    order = await OrderService.create_cart_order(db_user.id, "crypto")
    if not order:
        await callback.answer("Ошибка заказа", show_alert=True)
        return

    await _send_crypto_invoice(
        callback, db_user, order.id, f"Заказ #{order.id}", total
    )


async def _send_crypto_invoice(
    callback: CallbackQuery,
    db_user: User,
    order_id: int,
    title: str,
    amount: float,
):
    """Создать и показать Crypto инвойс."""
    settings = get_settings()
    crypto = CryptoPaymentService()
    payload = json.dumps({"order_id": order_id, "type": "crypto"})

    try:
        crypto_amount = round(amount, 2)
        invoice = await crypto.create_invoice(
            amount=crypto_amount,
            description=title,
            payload=payload,
        )
        invoice_id = str(invoice["invoice_id"])
        pay_url = invoice["bot_invoice_url"]

        await OrderService.save_crypto_invoice(
            user_id=db_user.id,
            order_id=order_id,
            invoice_id=invoice_id,
            amount=crypto_amount,
            asset=settings.CRYPTO_ASSET,
        )

        text = (
            "━━━━━━━━━━━━━━━\n"
            "💎 <b>Оплата криптовалютой</b>\n\n"
            f"📦 {title}\n\n"
            f"💰 Сумма: {format_price_crypto(crypto_amount, settings.CRYPTO_ASSET)}\n\n"
            "Нажмите кнопку ниже для оплаты.\n"
            "━━━━━━━━━━━━━━━"
        )
        await callback.message.edit_text(
            text,
            reply_markup=payment_kb(pay_url, invoice_id),
            parse_mode="HTML",
        )
        await callback.answer()
    except Exception as e:
        logger.error("Ошибка Crypto инвойса: %s", e)
        await callback.answer(f"Ошибка: {e}", show_alert=True)


@router.callback_query(F.data.startswith("crypto_check:"))
async def cb_crypto_check(callback: CallbackQuery, db_user: User):
    """Ручная проверка статуса Crypto (дополнительно к scheduler)."""
    invoice_id = callback.data.split(":")[1]
    
    # Check if this is a balance topup invoice
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT payload FROM crypto_invoices WHERE invoice_id = ?",
            (invoice_id,)
        )
        row = await cursor.fetchone()
        if row and (row["payload"] or "").startswith(("vip_", "balance_")):
            # Handle balance topup check
            crypto = CryptoPaymentService()
            invoice = await crypto.get_invoice_by_id(invoice_id)
            if invoice and invoice.get("status") == "paid":
                await _process_crypto_balance_topup(
                    callback.bot, 
                    invoice_id, 
                    db_user.id, 
                    invoice, 
                    row["payload"]
                )
                await callback.answer("✅ Платёж подтвержден!")
            else:
                await callback.answer("Платёж ещё не оплачен")
        else:
            await _process_crypto_payment(callback.bot, callback.from_user.id, db_user, invoice_id)
            await callback.answer()


# ── Обработка Crypto платежей ─────────────────────────────────

async def _process_crypto_payment(bot: Bot, telegram_id: int, db_user: User, invoice_id: str):
    """Проверка и обработка Crypto платежа."""
    crypto = CryptoPaymentService()
    try:
        if await crypto.check_invoice_paid(invoice_id):
            # Получаем информацию о заказе из payload
            invoice = await crypto.get_invoice_by_id(invoice_id)
            if not invoice:
                await bot.send_message(telegram_id, "Ошибка получения информации о платеже")
                return

            payload_data = json.loads(invoice.get("payload", "{}"))
            order_id = payload_data.get("order_id")
            
            if not order_id:
                await bot.send_message(telegram_id, "Ошибка идентификации заказа")
                return

            # Проверяем, не был ли платеж уже обработан
            if await OrderService.is_payment_processed("crypto", invoice_id):
                await bot.send_message(telegram_id, "Платёж уже был обработан")
                return

            # Завершаем заказ
            success = await OrderService.complete_order(
                order_id=order_id,
                provider="crypto",
                provider_payment_id=invoice_id,
                amount=float(invoice.get("amount", 0)),
                currency=invoice.get("asset", "USDT"),
            )

            if success:
                await OrderService.deliver_content(bot, telegram_id, order_id)
                await bot.send_message(telegram_id, "✅ Оплата подтверждена! Товар отправлен.")
            else:
                await bot.send_message(telegram_id, "Ошибка обработки заказа")
        else:
            await bot.send_message(telegram_id, "Платёж ещё не оплачен. Попробуйте позже.")
    except Exception as e:
        logger.error("Ошибка обработки Crypto платежа: %s", e)
        await bot.send_message(telegram_id, f"Ошибка: {e}")


async def poll_crypto_invoices(bot: Bot):
    """Периодическая проверка неоплаченных Crypto инвойсов."""
    from services.order_service import OrderService
    
    try:
        # Получаем все активные инвойсы
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT ci.invoice_id, ci.user_id, ci.order_id, ci.amount, ci.asset
                   FROM crypto_invoices ci
                   WHERE ci.status = 'active'
                   ORDER BY ci.created_at DESC
                   LIMIT 50"""
            )
            invoices = await cursor.fetchall()
        
        crypto = CryptoPaymentService()
        
        for row in invoices:
            invoice_id = row["invoice_id"]
            user_id = row["user_id"]
            order_id = row["order_id"]
            amount = row["amount"]
            asset = row["asset"]
            
            try:
                # Проверяем статус через API
                invoice = await crypto.get_invoice_by_id(invoice_id)
                if not invoice:
                    continue
                
                if invoice.get("status") == "paid":
                    # Проверяем, не был ли платеж уже обработан
                    if await OrderService.is_payment_processed("crypto", invoice_id):
                        async with get_db() as db:
                            await db.execute(
                                "UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = ?",
                                (invoice_id,)
                            )
                        continue
                    
                    payload = invoice.get("payload", "")
                    
                    # Обработка пополнения баланса или покупки VIP
                    if payload.startswith("vip_") or payload.startswith("balance_"):
                        await _process_crypto_balance_topup(bot, invoice_id, user_id, invoice, payload)
                    else:
                        # Обычная оплата заказа
                        if order_id:
                            success = await OrderService.complete_order(
                                order_id=order_id,
                                provider="crypto",
                                provider_payment_id=invoice_id,
                                amount=float(invoice.get("amount", 0)),
                                currency=invoice.get("asset", "USDT"),
                            )
                            
                            if success:
                                from services.user_service import UserService
                                user = await UserService.get_by_id(user_id)
                                if user:
                                    await OrderService.deliver_content(bot, user.telegram_id, order_id)
                                    await bot.send_message(
                                        user.telegram_id, 
                                        "✅ Оплата подтверждена! Товар отправлен."
                                    )
                    
                    # Обновляем статус инвойса
                    async with get_db() as db:
                        await db.execute(
                            "UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = ?",
                            (invoice_id,)
                        )
            except Exception as e:
                logger.error("Ошибка обработки инвойса %s: %s", invoice_id, e)
                
    except Exception as e:
        logger.error("Ошибка poll_crypto_invoices: %s", e)


async def _process_crypto_balance_topup(bot: Bot, invoice_id: str, user_id: int, invoice: dict, payload: str):
    """Обработка успешной оплаты пополнения баланса через Crypto."""
    from services.user_service import UserService
    from services.vip_service import VIPService
    
    settings = get_settings()
    crypto_amount = float(invoice.get("amount", 0))
    rub_amount = round(crypto_amount * settings.CRYPTO_USDT_RATE, 2)
    
    is_vip_purchase = payload.startswith("vip_")
    
    async with get_db() as db:
        # Проверяем idempotency
        cursor = await db.execute(
            "SELECT id FROM payments WHERE provider = 'crypto' AND provider_payment_id = ?",
            (invoice_id,)
        )
        if await cursor.fetchone():
            logger.warning("Crypto payment already processed: %s", invoice_id)
            return
        
        # Начисляем баланс
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (rub_amount, user_id)
        )
        
        # Записываем платеж
        await db.execute(
            """INSERT INTO payments (user_id, provider, provider_payment_id, amount, currency, status)
               VALUES (?, 'crypto', ?, ?, ?, 'paid')""",
            (user_id, invoice_id, crypto_amount, invoice.get("asset", "USDT"))
        )
        
        # Если это покупка VIP, выдаём VIP
        if is_vip_purchase:
            await VIPService.grant_vip(user_id, rub_amount, "crypto", invoice_id)
        
        # Обновляем статус в balance_topups если есть запись
        await db.execute(
            """UPDATE balance_topups 
               SET status = 'approved' 
               WHERE user_id = ? AND status = 'pending' AND receipt_type = 'crypto'
               LIMIT 1""",
            (user_id,)
        )
    
    # Уведомляем пользователя
    user = await UserService.get_by_id(user_id)
    if user:
        if is_vip_purchase:
            await bot.send_message(
                user.telegram_id,
                f"✅ Оплата подтверждена!\n\n💰 Баланс пополнен: {rub_amount} ₽\n⭐ VIP-доступ активирован!"
            )
        else:
            await bot.send_message(
                user.telegram_id,
                f"✅ Оплата подтверждена!\n\n💰 Баланс пополнен: {rub_amount} ₽"
            )
    
    # Уведомляем админов
    from config import get_settings
    config = get_settings()
    username = f"@{user.username}" if user and user.username else "—"
    admin_ids = set(config.admin_ids)
    admins = await UserService.get_all_admins()
    for a in admins:
        admin_ids.add(a.telegram_id)
    
    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                f"💳 <b>Крипто-пополнение</b>\n\n"
                f"👤 {username} (ID: {user.telegram_id if user else user_id})\n"
                f"💰 {crypto_amount} {invoice.get('asset', 'USDT')} → {rub_amount} ₽"
                f"{' (VIP)' if is_vip_purchase else ''}",
                parse_mode="HTML"
            )
        except Exception:
            pass


# ── Ручные криптопереводы ───────────────────────────────────

@router.callback_query(F.data == "manual_crypto:start")
async def cb_manual_crypto_start(callback: CallbackQuery, state: FSMContext):
    """Начало ручного перевода."""
    settings = get_settings()
    if not settings.MANUAL_CRYPTO_ENABLED:
        await callback.answer("Ручные переводы отключены", show_alert=True)
        return

    await state.set_state(ManualPaymentStates.amount)
    await callback.message.edit_text(
        "💳 <b>Ручной перевод</b>\n\n"
        "Введите сумму перевода:",
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ManualPaymentStates.amount)
async def on_manual_amount(message: Message, state: FSMContext):
    """Пользователь ввёл сумму для ручного перевода."""
    from utils import validate_price
    
    amount = validate_price(message.text)
    if amount is None:
        await message.answer("❌ Введите корректную сумму:")
        return

    await state.update_data(amount=amount)
    await state.set_state(ManualPaymentStates.tx_hash)

    wallets = await OrderService.get_wallets(active_only=True)
    lines = []
    for w in wallets:
        lines.append(f"💼 <b>{w['network']}</b>\n<code>{w['address']}</code>")

    if lines:
        wallets_text = "\n\n".join(lines)
    else:
        wallets_text = "⚠️ Реквизиты пока не настроены."

    await message.answer(
        f"💳 <b>Переведите {amount}</b>\n\n"
        f"На один из кошельков:\n\n"
        f"{wallets_text}\n\n"
        "После перевода отправьте TX Hash или Invoice ID:",
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
    )


@router.message(ManualPaymentStates.tx_hash)
async def on_manual_tx_hash(message: Message, state: FSMContext, db_user: User):
    """Получен TX Hash / Invoice ID."""
    tx_hash = message.text.strip()
    if not validate_tx_hash(tx_hash):
        await message.answer("❌ Некорректный формат. Отправьте TX Hash или Invoice ID:")
        return

    data = await state.get_data()
    amount = data.get("amount", 0)
    await state.clear()

    # Создаём платёж в статусе pending
    payment_id = f"manual_{tx_hash}"
    order = await OrderService.create_order(
        user_id=db_user.id,
        product_id=None,
        price=amount,
        payment_method="manual_crypto",
        status="pending",
    )
    
    await OrderService.create_payment(
        user_id=db_user.id,
        order_id=order.id,
        provider="manual_crypto",
        provider_payment_id=payment_id,
        amount=amount,
        currency="USDT",
        status="pending",
    )

    await message.answer(
        "✅ <b>Заявка отправлена</b>\n\n"
        f"Сумма: {amount}\n"
        f"TX Hash: <code>{tx_hash}</code>\n\n"
        "После проверки администратором баланс будет начислен.",
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
    )

    # Уведомляем администраторов
    await _notify_admins_manual_payment(message.bot, db_user, order.id, amount, tx_hash)


async def _notify_admins_manual_payment(bot, db_user: User, order_id: int, amount: float, tx_hash: str):
    """Уведомить администраторов о ручном переводе."""
    from services.user_service import UserService
    from config import get_settings
    from database import get_db
    
    settings = get_settings()
    username = f"@{db_user.username}" if db_user.username else "—"
    text = (
        f"💳 <b>Ручной перевод #{order_id}</b>\n\n"
        f"👤 ID: <code>{db_user.telegram_id}</code>\n"
        f"🔗 {username}\n"
        f"💰 Сумма: {amount}\n"
        f"🔑 TX Hash: <code>{tx_hash}</code>"
    )

    admin_ids = set(settings.admin_ids)
    admins = await UserService.get_all_admins()
    for a in admins:
        admin_ids.add(a.telegram_id)

    for admin_id in admin_ids:
        try:
            await bot.send_message(
                admin_id,
                text,
                reply_markup=manual_paid_kb(order_id),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("Не удалось уведомить админа %s: %s", admin_id, e)


# ── Подтверждение ручных платежей администратором ───────────────

@router.callback_query(F.data.startswith("admin:manual_paid:"))
async def cb_admin_manual_paid(callback: CallbackQuery, db_user: User):
    """Подтверждение ручного платежа администратором."""
    if not db_user.is_admin:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    order_id = int(callback.data.split(":")[2])
    order = await OrderService.get_order(order_id)
    if not order:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    # Завершаем заказ
    success = await OrderService.complete_order(
        order_id=order_id,
        provider="manual_crypto",
        provider_payment_id=order.payment_id or f"manual_{order_id}",
        amount=order.price,
        currency="USDT",
    )

    if success:
        await OrderService.deliver_content(callback.bot, order.user_id, order_id)
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅ Платёж подтверждён")
        
        # Уведомляем пользователя
        from services.user_service import UserService
        user = await UserService.get_by_id(order.user_id)
        if user:
            try:
                await callback.bot.send_message(
                    user.telegram_id,
                    f"✅ Ваш платёж #{order_id} подтверждён!",
                )
            except Exception:
                pass
    else:
        await callback.answer("Ошибка подтверждения", show_alert=True)
