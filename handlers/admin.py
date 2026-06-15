"""
Админ-панель: товары, категории, статистика, кошельки, настройки.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import get_settings
from keyboards import (
    admin_balance_kb,
    admin_categories_kb,
    admin_order_confirm_kb,
    admin_panel_kb,
    admin_product_actions_kb,
    admin_product_edit_fields_kb,
    admin_products_kb,
    admin_promos_kb,
    back_to_menu_kb,
    confirm_kb,
    skip_kb,
)
from core.order_engine import ConfirmOutcome, STATUS_COMPLETED, STATUS_CONFIRMED
from services.balance_service import BalanceService
from services.promo_service import PromoService
from middlewares import AdminMiddleware
from models import User
from services.order_service import OrderService
from services.product_service import ProductService
from services.user_service import UserService
from states import (
    AdminBalanceStates,
    AdminCategoryStates,
    AdminProductEditStates,
    AdminProductStates,
    AdminPromoStates,
    AdminWalletStates,
)
from utils import escape, validate_price

logger = logging.getLogger(__name__)
router = Router(name="admin")
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())

# Временное хранилище данных при создании товара
_product_drafts: dict = {}
_balance_action: dict = {}  # add / sub


# ── Статистика ──────────────────────────────────────────────

@router.callback_query(F.data == "admin:stats")
async def cb_admin_stats(callback: CallbackQuery):
    total_users = await UserService.count_users()
    total_orders = await OrderService.count_orders()
    paid_orders = await OrderService.count_orders("completed") + await OrderService.count_orders("paid")

    crypto_rev = await OrderService.revenue_by_provider("crypto")
    new_today = await UserService.count_new_today()
    popular = await ProductService.get_popular_products(5)

    pop_lines = "\n".join(
        f"  • {p['title']} — {p['count']} продаж" for p in popular
    ) or "  — нет данных"

    text = (
        "━━━━━━━━━━━━━━━\n"
        "📊 <b>Статистика</b>\n\n"
        f"👤 Пользователей: {total_users}\n"
        f"📦 Заказов: {total_orders}\n"
        f"✅ Оплаченных: {paid_orders}\n"

        f"💎 Выручка Crypto: {crypto_rev:.2f}\n"
        f"🆕 Новых за сутки: {new_today}\n\n"
        f"<b>Популярные товары:</b>\n{pop_lines}\n"
        "━━━━━━━━━━━━━━━"
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_panel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Платежи ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin:payments")
async def cb_admin_payments(callback: CallbackQuery):
    payments = await OrderService.get_recent_payments(15)
    if not payments:
        text = "💰 Платежей пока нет."
    else:
        lines = []
        for p in payments:
            lines.append(
                f"#{p['id']} | {p['provider']} | {p['amount']} {p['currency']} | {p['status']}"
            )
        text = "💰 <b>Последние платежи</b>\n\n" + "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:order_confirm:"))
async def cb_admin_order_confirm(callback: CallbackQuery, db_user: User):
    order_id = int(callback.data.split(":")[2])
    result = await OrderService.confirm_order_by_admin(order_id, db_user.id)

    if result.outcome is ConfirmOutcome.CONFIRMED:
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("✅ Заказ подтверждён")
        try:
            from services.user_service import UserService

            user = await UserService.get_by_id(result.order.user_id) if result.order else None
            if user:
                await callback.bot.send_message(
                    user.telegram_id,
                    f"✅ Ваш заказ №{order_id} подтверждён.",
                )
        except Exception:
            pass
        return

    if result.outcome is ConfirmOutcome.ALREADY_CONFIRMED:
        await callback.answer("Заказ уже подтверждён", show_alert=True)
        return

    if result.outcome is ConfirmOutcome.NOT_FOUND:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    await callback.answer("Заказ нельзя подтвердить в текущем статусе", show_alert=True)


# ── Crypto настройки ────────────────────────────────
@router.callback_query(F.data == "admin:crypto")
async def cb_admin_crypto(callback: CallbackQuery):

    text = (
        "💎 <b>Crypto Bot</b>\n\n"
        f"Статус: {'✅ Включено' if s.CRYPTO_ENABLED else '❌ Выключено'}\n"
        f"API: {s.CRYPTO_API_URL}\n"
        f"Токен: {'✅ задан' if s.CRYPTO_TOKEN else '❌ не задан'}\n"
        f"Валюта: {s.CRYPTO_ASSET}\n"
        f"Polling: каждые {s.CRYPTO_POLL_INTERVAL} сек.\n\n"
        "Настройки в .env: CRYPTO_TOKEN, CRYPTO_API_URL"
    )
    await callback.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:settings")
async def cb_admin_settings(callback: CallbackQuery):

    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"Ручные переводы: {'✅' if s.MANUAL_CRYPTO_ENABLED else '❌'}\n"
        f"Поддержка: @{s.SUPPORT_USERNAME or '—'}\n"
        f"Админы: {s.ADMIN_IDS or '—'}\n"
    )
    await callback.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode="HTML")
    await callback.answer()


# ── Товары ──────────────────────────────────────────────────

@router.callback_query(F.data == "admin:products")
async def cb_admin_products(callback: CallbackQuery):
    products = await ProductService.get_all_products()
    await callback.message.edit_text(
        "📦 <b>Управление товарами</b>",
        reply_markup=admin_products_kb(products),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:product:"))
async def cb_admin_product_detail(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[2])
    product = await ProductService.get_product(product_id)
    if not product:
        await callback.answer("Не найден", show_alert=True)
        return

    text = (
        f"📦 <b>{escape(product.title)}</b>\n\n"
        f"Цена: {int(product.price)}\n"
        f"Активен: {'✅' if product.is_active else '❌'}\n"
        f"Скрытый: {'🔒' if product.is_hidden else '—'}\n"
        f"Контент: {escape((product.content_data or '')[:100])}"
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_product_actions_kb(product_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:product_add")
async def cb_admin_product_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminProductStates.title)
    _product_drafts[callback.from_user.id] = {}
    await callback.message.edit_text("📝 Введите <b>название</b> товара:", parse_mode="HTML")
    await callback.answer()


@router.message(AdminProductStates.title)
async def msg_admin_product_title(message: Message, state: FSMContext):
    uid = message.from_user.id
    _product_drafts[uid]["title"] = message.text
    await state.set_state(AdminProductStates.price_usd)
    await message.answer(
        f"📝 Название: <b>{escape(message.text)}</b>\n\n"
        "💰 Введите <b>цену в USD</b> (число):",
        parse_mode="HTML",
    )


@router.message(AdminProductStates.price_usd)
async def msg_admin_product_price_usd(message: Message, state: FSMContext):
    if not validate_price(message.text):
        await message.answer("❌ Некорректная цена. Введите число.")
        return
    uid = message.from_user.id
    _product_drafts[uid]["price_usd"] = float(message.text)
    await state.set_state(AdminProductStates.price_rub)
    await message.answer(
        f"💰 Цена USD: <b>{message.text}</b>\n\n"
        "� Введите <b>цену в RUB</b> (число):",
        parse_mode="HTML",
    )


@router.message(AdminProductStates.price_rub)
async def msg_admin_product_price_rub(message: Message, state: FSMContext):
    if not validate_price(message.text):
        await message.answer("❌ Некорректная цена. Введите число.")
        return
    uid = message.from_user.id
    _product_drafts[uid]["price_rub"] = float(message.text)
    await state.set_state(AdminProductStates.description)
    await message.answer(
        f"💰 Цена RUB: <b>{message.text}</b>\n\n"
        "📝 Введите <b>описание</b> товара:",
        parse_mode="HTML",
    )


@router.message(AdminProductStates.content, F.photo)
async def msg_admin_product_content_photo(message: Message, state: FSMContext):
    uid = message.from_user.id
    photo = message.photo[-1]
    _product_drafts[uid]["content_type"] = "photo"
    _product_drafts[uid]["content_data"] = photo.file_id
    await message.answer(
        "📎 Фото получено.\n\n"
        "📦 Создать товар?",
        reply_markup=confirm_kb("admin:product_create", "admin:products"),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductStates.confirm)


@router.message(AdminProductStates.content, F.document)
async def msg_admin_product_content_file(message: Message, state: FSMContext):
    uid = message.from_user.id
    doc = message.document
    _product_drafts[uid]["content_type"] = "document"
    _product_drafts[uid]["content_data"] = doc.file_id
    await message.answer(
        "📎 Файл получен.\n\n"
        "📦 Создать товар?",
        reply_markup=confirm_kb("admin:product_create", "admin:products"),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductStates.confirm)


@router.message(AdminProductStates.content, F.text)
async def msg_admin_product_content_text(message: Message, state: FSMContext):
    uid = message.from_user.id
    _product_drafts[uid]["content_type"] = "text"
    _product_drafts[uid]["content_data"] = message.text
    await message.answer(
        "📎 Текст получен.\n\n"
        "📦 Создать товар?",
        reply_markup=confirm_kb("admin:product_create", "admin:products"),
        parse_mode="HTML",
    )
    await state.set_state(AdminProductStates.confirm)


@router.callback_query(F.data == "admin:product_create")
async def cb_admin_product_create(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    draft = _product_drafts.get(uid)
    if not draft:
        await callback.answer("Данные потеряны", show_alert=True)
        return
    product = await ProductService.create_product(
        title=draft["title"],
        price=draft.get("price", 0),
        price_usd=draft.get("price_usd"),
        price_rub=draft.get("price_rub"),
        content_type=draft.get("content_type", "text"),
        content_data=draft.get("content_data", ""),
    )
    if product:
        await callback.message.edit_text(
            "✅ Товар создан!",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        _product_drafts[uid] = {}
        await state.clear()
    else:
        await callback.answer("Ошибка создания", show_alert=True)
    await callback.answer()


@router.callback_query(F.data == "admin:skip_content")
async def cb_admin_skip_content(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    _product_drafts[uid]["content_type"] = "text"
    _product_drafts[uid]["content_data"] = None
    await _finish_product_create(callback.message, state, uid)
    await callback.answer()


async def _finish_product_create(message: Message, state: FSMContext, user_id: int):
    draft = _product_drafts.get(user_id)
    if not draft:
        await message.answer("❌ Данные потеряны")
        return
    product = await ProductService.create_product(
        title=draft["title"],
        price=draft.get("price", 0),
        price_usd=draft.get("price_usd"),
        price_rub=draft.get("price_rub"),
        content_type=draft.get("content_type", "text"),
        content_data=draft.get("content_data", ""),
    )
    if product:
        await message.answer(
            "✅ Товар создан!",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        _product_drafts[user_id] = {}
        await state.clear()
    else:
        await message.answer("❌ Ошибка создания")


@router.callback_query(F.data.startswith("admin:product_del:"))
async def cb_admin_product_delete(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        f"🗑 Удалить товар #{product_id}?",
        reply_markup=confirm_kb(f"admin:product_del_yes:{product_id}", "admin:products"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:product_del_yes:"))
async def cb_admin_product_delete_yes(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[3])
    success = await ProductService.delete_product(product_id)
    if success:
        categories = await ProductService.get_all_products()
        await callback.message.edit_text(
            "✅ Товар удалён",
            reply_markup=admin_categories_kb(categories),
            parse_mode="HTML",
        )
    else:
        await callback.answer("Ошибка удаления", show_alert=True)
    await callback.answer()


@router.callback_query(F.data == "admin:cat_add")
async def cb_admin_cat_add(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminCategoryStates.name)
    await callback.message.edit_text("📝 Введите <b>название категории</b>:", parse_mode="HTML")
    await callback.answer()


@router.message(AdminCategoryStates.name)
async def msg_admin_cat_name(message: Message, state: FSMContext):
    name = message.text
    cat = await ProductService.create_category(name)
    if cat:
        await message.answer("✅ Категория создана", reply_markup=admin_panel_kb())
        await state.clear()
    else:
        await message.answer("❌ Ошибка создания")


@router.callback_query(F.data == "admin:categories")
async def cb_admin_categories(callback: CallbackQuery):
    categories = await ProductService.get_all_categories()
    await callback.message.edit_text(
        "📂 <b>Категории</b>",
        reply_markup=admin_categories_kb(categories),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:cat_del:"))
async def cb_admin_cat_delete(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        f"🗑 Удалить категорию #{cat_id}?",
        reply_markup=confirm_kb(f"admin:cat_del_yes:{cat_id}", "admin:categories"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:cat_del_yes:"))
async def cb_admin_cat_delete_yes(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[3])
    success = await ProductService.delete_category(cat_id)
    if success:
        await callback.message.edit_text(
            "✅ Категория удалена",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
    else:
        await callback.answer("Ошибка удаления", show_alert=True)
    await callback.answer()


# ── Кошельки ───────────────────────────────────────────────

@router.callback_query(F.data == "admin:wallets")
async def cb_admin_wallets(callback: CallbackQuery):
    from services.wallet_service import WalletService

    wallets = await WalletService.get_all_wallets()
    if not wallets:
        text = "💳 Кошельков пока нет."
    else:
        lines = []
        for w in wallets:
            lines.append(f"💳 {w['currency']}: {w['address']}")
        text = "💳 <b>Кошельки</b>\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode="HTML")
    await callback.answer()


@router.message(Command("add_wallet"))
async def cmd_add_wallet(message: Message, state: FSMContext):
    await state.set_state(AdminWalletStates.currency)
    await message.answer("💰 Введите валюту (USDT, BTC, etc.):")


@router.message(AdminWalletStates.currency)
async def msg_wallet_currency(message: Message, state: FSMContext):
    async with state.update_data() as data:
        data["currency"] = message.text.upper()
    await state.set_state(AdminWalletStates.address)
    await message.answer("💳 Введите адрес кошелька:")


@router.message(AdminWalletStates.address)
async def msg_wallet_address(message: Message, state: FSMContext):
    async with state.update_data() as data:
        data["address"] = message.text
    from services.wallet_service import WalletService

    wallet = await WalletService.create_wallet(**data)
    if wallet:
        await message.answer("✅ Кошелёк добавлен", reply_markup=admin_panel_kb())
        await state.clear()
    else:
        await message.answer("❌ Ошибка")


# ── Баланс ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin:balance")
async def cb_admin_balance(callback: CallbackQuery):
    await callback.message.edit_text(
        "💳 <b>Управление балансом</b>",
        reply_markup=admin_balance_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:bal_add")
async def cb_admin_balance_add(callback: CallbackQuery, state: FSMContext):
    _balance_action[callback.from_user.id] = "add"
    await state.set_state(AdminBalanceStates.view_user_id)
    await callback.message.edit_text(
        "➕ Введите <b>Telegram ID</b> пользователя для начисления:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:bal_sub")
async def cb_admin_balance_sub(callback: CallbackQuery, state: FSMContext):
    _balance_action[callback.from_user.id] = "sub"
    await state.set_state(AdminBalanceStates.view_user_id)
    await callback.message.edit_text(
        "➖ Введите <b>Telegram ID</b> пользователя для списания:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:bal_info")
async def cb_admin_balance_info(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminBalanceStates.view_user_id)
    await callback.message.edit_text(
        "🔍 Введите <b>Telegram ID</b> пользователя:",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminBalanceStates.view_user_id)
async def msg_balance_view_user(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Некорректный ID. Введите число.")
        return
    user = await UserService.get_by_telegram_id(user_id)
    if not user:
        await message.answer("❌ Пользователь не найден")
        await state.clear()
        return
    action = _balance_action.get(message.from_user.id)
    if action == "add":
        await state.set_state(AdminBalanceStates.amount)
        async with state.update_data() as data:
            data["target_user_id"] = user.id
        await message.answer(
            f"👤 Пользователь: {user_id}\n💰 Введите сумму для начисления:"
        )
    elif action == "sub":
        await state.set_state(AdminBalanceStates.amount)
        async with state.update_data() as data:
            data["target_user_id"] = user.id
        await message.answer(f"👤 Пользователь: {user_id}\n💰 Введите сумму для списания:")
    else:
        bal = await BalanceService.get_balance(user.id)
        await message.answer(
            f"👤 ID: {user_id}\n💰 Баланс: {bal}",
            reply_markup=admin_panel_kb(),
        )
        await state.clear()


@router.message(AdminBalanceStates.amount)
async def msg_balance_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text)
    except ValueError:
        await message.answer("❌ Некорректная сумма. Введите число.")
        return
    data = await state.get_data()
    target_user_id = data["target_user_id"]
    action = _balance_action.get(message.from_user.id)
    if action == "add":
        await BalanceService.add_balance(target_user_id, amount)
        await message.answer(f"✅ Начислено {amount} пользователю", reply_markup=admin_panel_kb())
    elif action == "sub":
        await BalanceService.subtract_balance(target_user_id, amount)
        await message.answer(f"✅ Списано {amount} у пользователя", reply_markup=admin_panel_kb())
    await state.clear()


# ── Топапы ───────────────────────────────────────────────────

@router.callback_query(F.data == "admin:topups")
async def cb_admin_topups(callback: CallbackQuery):
    from services.balance_service import BalanceService

    pending = await BalanceService.get_pending_topups()
    if not pending:
        text = "💳 Ожидают проверки: нет"
    else:
        lines = [
            f"#{t['id']} | ID {t['telegram_id']} | {t['amount']}"
            for t in pending
        ]
        text = "💳 <b>Ожидают проверки:</b>\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:topup_ok:"))
async def cb_topup_approve(callback: CallbackQuery):
    topup_id = int(callback.data.split(":")[2])
    from services.balance_service import BalanceService

    success = await BalanceService.approve_topup(topup_id)
    if success:
        await callback.answer("✅ Одобрено")
        await cb_admin_topups(callback)
    else:
        await callback.answer("❌ Ошибка", show_alert=True)


# ── Промокоды ───────────────────────────────────────────────

@router.callback_query(F.data == "admin:promos")
async def cb_admin_promos(callback: CallbackQuery):
    promos = await PromoService.get_all_promos()
    await callback.message.edit_text(
        "🎟 <b>Промокоды</b>",
        reply_markup=admin_promos_kb(promos),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:promo_add")
async def cb_admin_promo_add(callback: CallbackQuery, state: FSMContext):
    import random
    import string

    suggested = "".join(random.choices(string.ascii_uppercase, k=6))
    await state.set_state(AdminPromoStates.code)
    await callback.message.edit_text(
        "🎟 Введите <b>код</b> промокода:\n\n"
        f"Или используйте предложенный: <code>{suggested}</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminPromoStates.code)
async def msg_promo_code(message: Message, state: FSMContext):
    code = message.text.upper()
    existing = await PromoService.get_by_code(code)
    if existing:
        await message.answer("❌ Такой код уже существует")
        return
    async with state.update_data() as data:
        data["code"] = code
    await state.set_state(AdminPromoStates.discount)
    await message.answer(f"🎟 Код: <code>{code}</code>\n\n💰 Введите скидку (%):", parse_mode="HTML")


@router.message(AdminPromoStates.discount)
async def msg_promo_discount(message: Message, state: FSMContext):
    try:
        discount = float(message.text)
    except ValueError:
        await message.answer("❌ Некорректное значение")
        return
    async with state.update_data() as data:
        data["discount"] = discount
    await state.set_state(AdminPromoStates.max_uses)
    await message.answer(f"💰 Скидка: {discount}%\n\n🔢 Макс. использований (0 = безлимит):")


@router.message(AdminPromoStates.max_uses)
async def msg_promo_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text) if message.text else 0
    except ValueError:
        await message.answer("❌ Некорректное значение")
        return
    data = await state.get_data()
    promo = await PromoService.create_promo(
        code=data["code"],
        discount=data["discount"],
        max_uses=max_uses,
    )
    if promo:
        await message.answer("✅ Промокод создан", reply_markup=admin_panel_kb())
        await state.clear()
    else:
        await message.answer("❌ Ошибка")


@router.callback_query(F.data.startswith("admin:promo_del:"))
async def cb_admin_promo_delete(callback: CallbackQuery):
    promo_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        f"🗑 Удалить промокод #{promo_id}?",
        reply_markup=confirm_kb(f"admin:promo_del_yes:{promo_id}", "admin:promos"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:promo_del_yes:"))
async def cb_admin_promo_delete_yes(callback: CallbackQuery):
    promo_id = int(callback.data.split(":")[3])
    success = await PromoService.delete_promo(promo_id)
    if success:
        await callback.message.edit_text(
            "✅ Промокод удалён",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
    else:
        await callback.answer("Ошибка удаления", show_alert=True)
    await callback.answer()


# ── Редактирование товара ───────────────────────────────────

@router.callback_query(F.data.startswith("admin:edit_product:"))
async def cb_admin_edit_product(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        "✏️ Выберите поле для редактирования:",
        reply_markup=admin_product_edit_fields_kb(product_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:edit_field:"))
async def cb_admin_edit_field(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    product_id = int(parts[2])
    field = parts[3]
    await state.set_state(AdminProductEditStates.value)
    async with state.update_data() as data:
        data["product_id"] = product_id
        data["field"] = field
    prompts = {
        "title": "📝 Новое название:",
        "price": "💰 Новая цена:",
        "content": "📎 Новый контент для выдачи:",
    }
    await callback.message.edit_text(prompts.get(field, "Введите значение:"))
    await callback.answer()


@router.message(AdminProductEditStates.value, F.photo)
async def msg_edit_value_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data["product_id"]
    field = data["field"]
    photo = message.photo[-1]
    if field == "content":
        await ProductService.update_product(product_id, content_type="photo", content_data=photo.file_id)
        await message.answer("✅ Контент обновлён (фото)", reply_markup=admin_panel_kb())
        await state.clear()
    else:
        await message.answer("❌ Неверный тип данных для этого поля")


@router.message(AdminProductEditStates.value, F.document)
async def msg_edit_value_file(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data["product_id"]
    field = data["field"]
    doc = message.document
    if field == "content":
        await ProductService.update_product(product_id, content_type="document", content_data=doc.file_id)
        await message.answer("✅ Контент обновлён (файл)", reply_markup=admin_panel_kb())
        await state.clear()
    else:
        await message.answer("❌ Неверный тип данных для этого поля")


@router.message(AdminProductEditStates.value, F.text)
async def msg_edit_value_text(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data["product_id"]
    field = data["field"]
    value = message.text
    if field == "price":
        if not validate_price(value):
            await message.answer("❌ Некорректная цена")
            return
        await ProductService.update_product(product_id, price=float(value))
        await message.answer("✅ Цена обновлена", reply_markup=admin_panel_kb())
        await state.clear()
    elif field == "title":
        await ProductService.update_product(product_id, title=value)
        await message.answer("✅ Название обновлено", reply_markup=admin_panel_kb())
        await state.clear()
    elif field == "content":
        await ProductService.update_product(product_id, content_type="text", content_data=value)
        await message.answer("✅ Контент обновлён (текст)", reply_markup=admin_panel_kb())
        await state.clear()
    else:
        await message.answer("❌ Неизвестное поле")
