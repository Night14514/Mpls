"""
Админ-панель: товары, категории, статистика, кошельки, настройки.
"""

import logging

from aiogram import F, Router
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

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
    back_kb,
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
    AdminUserStates,
    AdminWalletStates,
)
from utils import encode_content_data, escape, format_price, get_product_price, safe_edit_or_send, validate_price

logger = logging.getLogger(__name__)
router = Router(name="admin")
router.message.middleware(AdminMiddleware())
router.callback_query.middleware(AdminMiddleware())

# Временное хранилище данных при создании товара
_product_drafts: dict = {}
_balance_action: dict = {}  # add / sub / info


def _draft_to_product_kwargs(draft: dict) -> dict:
    """Подготовка аргументов для ProductService.create_product."""
    content_type = draft.get("content_type", "text")
    raw_content = draft.get("content_data") or ""
    content_data = encode_content_data(content_type, raw_content) if raw_content else None
    price = draft.get("price_rub") or draft.get("price") or 0
    return {
        "title": draft["title"],
        "description": draft.get("description", ""),
        "price": price,
        "category_id": draft.get("category_id"),
        "photo": draft.get("photo"),
        "content_data": content_data,
        "price_usd": None,
        "price_rub": price,
    }


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
    s = get_settings()
    text = (
        "💎 <b>Crypto Bot</b>\n\n"
        f"Статус: {'✅ Включено' if s.CRYPTO_ENABLED else '❌ Выключено'}\n"
        f"API: {s.CRYPTO_API_URL}\n"
        f"Токен: {'✅ задан' if s.CRYPTO_TOKEN else '❌ не задан'}\n"
        f"Валюта: {s.CRYPTO_ASSET}\n"
        f"Polling: каждые {s.CRYPTO_POLL_INTERVAL} сек.\n\n"
        "Настройки в .env: CRYPTO_TOKEN, CRYPTO_API_URL"
    )
    await safe_edit_or_send(callback, text, reply_markup=admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:settings")
async def cb_admin_settings(callback: CallbackQuery):
    s = get_settings()
    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"Ручные переводы: {'✅' if s.MANUAL_CRYPTO_ENABLED else '❌'}\n"
        f"Поддержка: @{s.SUPPORT_USERNAME or '—'}\n"
        f"Админы: {s.ADMIN_IDS or '—'}\n"
    )
    await safe_edit_or_send(callback, text, reply_markup=admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:users")
async def cb_admin_users(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminUserStates.search)
    await safe_edit_or_send(
        callback,
        "👤 <b>Пользователи</b>\n\n"
        "Введите <b>Telegram ID</b> или <b>@username</b> для поиска:",
        reply_markup=back_kb("admin:panel"),
    )
    await callback.answer()


@router.message(AdminUserStates.search)
async def msg_admin_user_search(message: Message, state: FSMContext):
    users = await UserService.search_by_username_or_id(message.text.strip())
    if not users:
        await message.answer("❌ Пользователь не найден", reply_markup=admin_panel_kb())
    else:
        for user in users[:5]:
            info = await UserService.get_user_info_text(user.telegram_id)
            if info:
                await message.answer(info, parse_mode="HTML")
        await message.answer("✅ Готово", reply_markup=admin_panel_kb())
    await state.clear()


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


@router.callback_query(F.data.regexp(r"^admin:product:\d+$"))
async def cb_admin_product_detail(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[2])
    product = await ProductService.get_product(product_id)
    if not product:
        await callback.answer("Не найден", show_alert=True)
        return

    price = get_product_price(product)
    text = (
        f"📦 <b>{escape(product.title)}</b>\n\n"
        f"📄 {escape(product.description or '—')}\n\n"
        f"💰 Цена: {format_price(price)}\n"
        f"📂 Категория: {escape(product.category_name or '—')}\n"
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
    await state.set_state(AdminProductStates.price_rub)
    await message.answer(
        f"📝 Название: <b>{escape(message.text)}</b>\n\n"
        "💰 Введите <b>цену в рублях</b> (число):",
        parse_mode="HTML",
    )


@router.message(AdminProductStates.description)
async def msg_admin_product_description(message: Message, state: FSMContext):
    uid = message.from_user.id
    _product_drafts[uid]["description"] = message.text
    await state.set_state(AdminProductStates.content)
    await message.answer(
        "📝 Описание сохранено.\n\n"
        "📎 Отправьте <b>контент для выдачи</b> (текст, фото или файл).\n"
        "Или пропустите — контент можно добавить позже.",
        reply_markup=skip_kb("admin:skip_content"),
        parse_mode="HTML",
    )


@router.message(AdminProductStates.price_rub)
async def msg_admin_product_price_rub(message: Message, state: FSMContext):
    if not validate_price(message.text):
        await message.answer("❌ Некорректная цена. Введите число.")
        return
    uid = message.from_user.id
    price = float(message.text.replace(",", "."))
    _product_drafts[uid]["price_rub"] = price
    _product_drafts[uid]["price"] = price
    await state.set_state(AdminProductStates.description)
    await message.answer(
        f"💰 Цена: <b>{format_price(price)}</b>\n\n"
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
    if not draft or "title" not in draft:
        await callback.answer("Данные потеряны", show_alert=True)
        return
    product = await ProductService.create_product(**_draft_to_product_kwargs(draft))
    if product:
        await callback.message.edit_text(
            "✅ Товар создан!",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        _product_drafts.pop(uid, None)
        await state.clear()
        await callback.answer()
    else:
        await callback.answer("Ошибка создания", show_alert=True)


@router.callback_query(F.data == "admin:skip_content")
async def cb_admin_skip_content(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in _product_drafts:
        await callback.answer("Данные потеряны", show_alert=True)
        return
    _product_drafts[uid]["content_type"] = "text"
    _product_drafts[uid]["content_data"] = ""
    await state.set_state(AdminProductStates.confirm)
    await callback.message.edit_text(
        "📦 Создать товар без контента?",
        reply_markup=confirm_kb("admin:product_create", "admin:products"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin:product_del:\d+$"))
async def cb_admin_product_delete(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[2])
    await callback.message.edit_text(
        f"🗑 Удалить товар #{product_id}?",
        reply_markup=confirm_kb(f"admin:product_del_yes:{product_id}", "admin:products"),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin:product_del_yes:\d+$"))
async def cb_admin_product_delete_yes(callback: CallbackQuery):
    product_id = int(callback.data.split(":")[3])
    success = await ProductService.delete_product(product_id)
    if success:
        products = await ProductService.get_all_products()
        await callback.message.edit_text(
            "✅ Товар удалён",
            reply_markup=admin_products_kb(products),
            parse_mode="HTML",
        )
        await callback.answer()
    else:
        await callback.answer("Ошибка удаления", show_alert=True)


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
    categories = await ProductService.get_categories(include_hidden=True, trusted=True)
    await callback.message.edit_text(
        "📂 <b>Категории</b>",
        reply_markup=admin_categories_kb(categories),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin:cat:\d+$"))
async def cb_admin_cat_detail(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[2])
    cat = await ProductService.get_category(cat_id)
    if not cat:
        await callback.answer("Не найдена", show_alert=True)
        return
    hidden = "🔒 скрытая" if cat.is_hidden else "✅ видимая"
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:cat_del:{cat_id}"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:categories"))
    await callback.message.edit_text(
        f"📂 <b>{escape(cat.name)}</b>\n\n"
        f"ID: {cat.id}\n"
        f"Статус: {hidden}",
        reply_markup=builder.as_markup(),
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
        await callback.answer()
    else:
        await callback.answer("Ошибка удаления", show_alert=True)


# ── Кошельки ───────────────────────────────────────────────

@router.callback_query(F.data == "admin:wallets")
async def cb_admin_wallets(callback: CallbackQuery):
    wallets = await OrderService.get_wallets(active_only=False)
    if not wallets:
        text = "💳 Кошельков пока нет.\n\nДобавить: /add_wallet"
    else:
        lines = [f"💳 {w['network']}: <code>{escape(w['address'])}</code>" for w in wallets]
        text = "💳 <b>Кошельки</b>\n\n" + "\n".join(lines) + "\n\nДобавить: /add_wallet"
    await safe_edit_or_send(callback, text, reply_markup=admin_panel_kb())
    await callback.answer()


@router.message(Command("add_wallet"))
async def cmd_add_wallet(message: Message, state: FSMContext):
    await state.set_state(AdminWalletStates.network)
    await message.answer("💳 Введите сеть кошелька (USDT TRC20, BTC, ETH и т.д.):")


@router.message(AdminWalletStates.network)
async def msg_wallet_network(message: Message, state: FSMContext):
    await state.update_data(network=message.text.strip())
    await state.set_state(AdminWalletStates.address)
    await message.answer("💳 Введите адрес кошелька:")


@router.message(AdminWalletStates.address)
async def msg_wallet_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    data = await state.get_data()
    wallet_id = await OrderService.add_wallet(data["network"], data["address"])
    if wallet_id:
        await message.answer("✅ Кошелёк добавлен", reply_markup=admin_panel_kb())
        await state.clear()
    else:
        await message.answer("❌ Ошибка")


# ── Баланс ─────────────────────────────────────────────────

@router.callback_query(F.data == "admin:balance")
async def cb_admin_balance(callback: CallbackQuery):
    await callback.message.edit_text(
        "💳 <b>Управление балансом</b>\n\nБаланс пользователей в рублях.",
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
    _balance_action[callback.from_user.id] = "info"
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
        await state.update_data(target_user_id=user.id)
        await message.answer(
            f"👤 Пользователь: {user_id}\n💰 Введите сумму в рублях для начисления:"
        )
    elif action == "sub":
        await state.set_state(AdminBalanceStates.amount)
        await state.update_data(target_user_id=user.id)
        await message.answer(f"👤 Пользователь: {user_id}\n💰 Введите сумму в рублях для списания:")
    else:
        await message.answer(
            f"👤 ID: {user_id}\n💰 Баланс: {format_price(user.balance)}",
            reply_markup=admin_panel_kb(),
        )
        await state.clear()
        _balance_action.pop(message.from_user.id, None)


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
        new_balance = await UserService.adjust_balance(target_user_id, amount)
        if new_balance is not None:
            await message.answer(
                f"✅ Начислено {format_price(amount)}. Новый баланс: {format_price(new_balance)}",
                reply_markup=admin_panel_kb(),
            )
        else:
            await message.answer("❌ Ошибка начисления", reply_markup=admin_panel_kb())
    elif action == "sub":
        new_balance = await UserService.adjust_balance(target_user_id, -amount)
        if new_balance is not None:
            await message.answer(
                f"✅ Списано {format_price(amount)}. Новый баланс: {format_price(new_balance)}",
                reply_markup=admin_panel_kb(),
            )
        else:
            await message.answer("❌ Недостаточно средств или ошибка", reply_markup=admin_panel_kb())
    _balance_action.pop(message.from_user.id, None)
    await state.clear()


# ── Топапы ───────────────────────────────────────────────────

@router.callback_query(F.data == "admin:topups")
async def cb_admin_topups(callback: CallbackQuery):
    pending = await BalanceService.get_pending()
    if not pending:
        text = "💳 Ожидают проверки: нет"
    else:
        lines = [
            f"#{t['id']} | ID {t['telegram_id']} | {format_price(t['amount'])}"
            for t in pending
        ]
        text = "💳 <b>Ожидают проверки:</b>\n\n" + "\n".join(lines)
    await safe_edit_or_send(callback, text, reply_markup=admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("admin:topup_ok:"))
async def cb_topup_approve(callback: CallbackQuery):
    topup_id = int(callback.data.split(":")[2])
    result = await BalanceService.approve(topup_id)
    if result:
        try:
            await callback.bot.send_message(
                result["telegram_id"],
                f"✅ Пополнение на {format_price(result['amount'])} одобрено",
            )
        except Exception:
            pass
        pending = await BalanceService.get_pending()
        if not pending:
            text = "💳 Ожидают проверки: нет"
        else:
            lines = [
                f"#{t['id']} | ID {t['telegram_id']} | {format_price(t['amount'])}"
                for t in pending
            ]
            text = "💳 <b>Ожидают проверки:</b>\n\n" + "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode="HTML")
        await callback.answer("✅ Одобрено")
    else:
        await callback.answer("❌ Ошибка", show_alert=True)


@router.callback_query(F.data.startswith("admin:topup_no:"))
async def cb_topup_reject(callback: CallbackQuery):
    topup_id = int(callback.data.split(":")[2])
    telegram_id = await BalanceService.reject(topup_id)
    if telegram_id:
        try:
            await callback.bot.send_message(telegram_id, "❌ Ваше пополнение отклонено")
        except Exception:
            pass
        pending = await BalanceService.get_pending()
        if not pending:
            text = "💳 Ожидают проверки: нет"
        else:
            lines = [
                f"#{t['id']} | ID {t['telegram_id']} | {format_price(t['amount'])}"
                for t in pending
            ]
            text = "💳 <b>Ожидают проверки:</b>\n\n" + "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=admin_panel_kb(), parse_mode="HTML")
        await callback.answer("❌ Отклонено")
    else:
        await callback.answer("❌ Ошибка", show_alert=True)


# ── Промокоды ───────────────────────────────────────────────

@router.callback_query(F.data == "admin:promos")
async def cb_admin_promos(callback: CallbackQuery):
    promos = await PromoService.get_all()
    await callback.message.edit_text(
        "🎟 <b>Промокоды</b>",
        reply_markup=admin_promos_kb(promos),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin:promo:\d+$"))
async def cb_admin_promo_detail(callback: CallbackQuery):
    promo_id = int(callback.data.split(":")[2])
    promos = await PromoService.get_all()
    promo = next((p for p in promos if p.id == promo_id), None)
    if not promo:
        await callback.answer("Не найден", show_alert=True)
        return
    status = "✅ активен" if promo.is_active else "❌ неактивен"
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:promo_del:{promo_id}"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:promos"))
    await callback.message.edit_text(
        f"🎟 <b>{escape(promo.code)}</b>\n\n"
        f"Сумма: {format_price(promo.amount)}\n"
        f"Использовано: {promo.used_count}/{promo.max_activations}\n"
        f"Статус: {status}",
        reply_markup=builder.as_markup(),
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
    await state.update_data(code=code)
    await state.set_state(AdminPromoStates.discount)
    await message.answer(
        f"🎟 Код: <code>{code}</code>\n\n💰 Введите <b>сумму начисления</b> на баланс:",
        parse_mode="HTML",
    )


@router.message(AdminPromoStates.discount)
async def msg_promo_discount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Некорректная сумма")
        return
    await state.update_data(amount=amount)
    await state.set_state(AdminPromoStates.max_uses)
    await message.answer(f"💰 Сумма: {format_price(amount)}\n\n🔢 Макс. использований (0 = безлимит):")


@router.message(AdminPromoStates.max_uses)
async def msg_promo_max_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text) if message.text else 0
    except ValueError:
        await message.answer("❌ Некорректное значение")
        return
    data = await state.get_data()
    max_activations = max_uses if max_uses > 0 else 999_999
    promo = await PromoService.create(
        code=data["code"],
        amount=data["amount"],
        max_activations=max_activations,
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
    success = await PromoService.delete(promo_id)
    if success:
        await callback.message.edit_text(
            "✅ Промокод удалён",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
    else:
        await callback.answer("Ошибка удаления", show_alert=True)


# ── Редактирование товара ───────────────────────────────────

@router.callback_query(F.data.startswith("admin:product_edit:"))
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
    await state.update_data(product_id=product_id, field=field)
    prompts = {
        "title": "📝 Новое название:",
        "description": "📝 Новое описание:",
        "price": "💰 Новая цена в рублях:",
        "category": "📂 Введите ID категории (0 — без категории):",
        "photo": "🖼 Отправьте новое фото товара:",
        "content": "📎 Новый контент для выдачи (текст, фото или файл):",
    }
    await callback.message.edit_text(prompts.get(field, "Введите значение:"))
    await callback.answer()


@router.message(AdminProductEditStates.value, F.photo)
async def msg_edit_value_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    product_id = data["product_id"]
    field = data["field"]
    photo = message.photo[-1]
    if field == "photo":
        await ProductService.update_product(product_id, photo=photo.file_id)
        await message.answer("✅ Фото обновлено", reply_markup=admin_panel_kb())
        await state.clear()
    elif field == "content":
        encoded = encode_content_data("photo", photo.file_id)
        await ProductService.update_product(product_id, content_data=encoded)
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
        encoded = encode_content_data("document", doc.file_id)
        await ProductService.update_product(product_id, content_data=encoded)
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
        price_val = float(value.replace(",", "."))
        await ProductService.update_product(product_id, price=price_val, price_rub=price_val)
        await message.answer(f"✅ Цена обновлена: {format_price(price_val)}", reply_markup=admin_panel_kb())
        await state.clear()
    elif field == "title":
        await ProductService.update_product(product_id, title=value)
        await message.answer("✅ Название обновлено", reply_markup=admin_panel_kb())
        await state.clear()
    elif field == "description":
        await ProductService.update_product(product_id, description=value)
        await message.answer("✅ Описание обновлено", reply_markup=admin_panel_kb())
        await state.clear()
    elif field == "category":
        try:
            cat_id = int(value.strip())
            cat_id = None if cat_id == 0 else cat_id
        except ValueError:
            await message.answer("❌ Введите число (ID категории или 0)")
            return
        if cat_id is not None and not await ProductService.get_category(cat_id):
            await message.answer("❌ Категория не найдена")
            return
        await ProductService.update_product(product_id, category_id=cat_id)
        await message.answer("✅ Категория обновлена", reply_markup=admin_panel_kb())
        await state.clear()
    elif field == "content":
        encoded = encode_content_data("text", value)
        await ProductService.update_product(product_id, content_data=encoded)
        await message.answer("✅ Контент обновлён (текст)", reply_markup=admin_panel_kb())
        await state.clear()
    else:
        await message.answer("❌ Неизвестное поле")
