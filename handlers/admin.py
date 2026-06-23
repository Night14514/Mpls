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
    admin_category_actions_kb,
    admin_order_confirm_kb,
    admin_panel_kb,
    admin_product_actions_kb,
    admin_product_edit_fields_kb,
    admin_products_kb,
    admin_promos_kb,
    admin_referral_back_kb,
    admin_referral_menu_kb,
    admin_referral_settings_kb,
    admin_vip_kb,
    admin_vip_settings_kb,
    back_kb,
    categories_kb,
    confirm_kb,
    secret_access_kb,
    skip_kb,
)
from core.order_engine import ConfirmOutcome, STATUS_COMPLETED, STATUS_CONFIRMED
from services.balance_service import BalanceService
from services.promo_service import PromoService
from services.referral_service import ReferralService
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
    AdminVIPGrantStates,
    AdminWalletStates,
    AdminReferralSettingsStates,
    AdminVIPSettingsStates,
    SecretAccessStates,
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
        "video": draft.get("video"),

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
        "📎 Отправьте <b>контент для выдачи</b> (текст, фото, видео или файл).\n"
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
    await state.set_state(AdminProductStates.category)
    categories = await ProductService.get_categories(include_hidden=True, trusted=True)
    if not categories:
        await message.answer(
            f"💰 Цена: <b>{format_price(price)}</b>\n\n"
            "⚠️ Категорий пока нет. Сначала создайте категорию (Админ-панель → Категории), "
            "затем повторите добавление товара.",
            reply_markup=admin_panel_kb(),
            parse_mode="HTML",
        )
        _product_drafts.pop(uid, None)
        await state.clear()
        return
    await message.answer(
        f"💰 Цена: <b>{format_price(price)}</b>\n\n"
        "📂 Выберите <b>категорию</b> товара:",
        reply_markup=categories_kb(categories, prefix="admin:product_cat"),
        parse_mode="HTML",
    )

@router.callback_query(AdminProductStates.category, F.data.regexp(r"^admin:product_cat:\d+$"))
async def cb_admin_product_category(callback: CallbackQuery, state: FSMContext):
    uid = callback.from_user.id
    if uid not in _product_drafts:
        await callback.answer("Данные потеряны, начните заново: /admin", show_alert=True)
        return
    category_id = int(callback.data.split(":")[2])
    category = await ProductService.get_category(category_id)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return
    _product_drafts[uid]["category_id"] = category_id
    await state.set_state(AdminProductStates.description)
    await callback.message.edit_text(
        f"📂 Категория: <b>{escape(category.name)}</b>\n\n"
        "📝 Введите <b>описание</b> товара:",
        parse_mode="HTML",
    )
    await callback.answer()



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

@router.message(AdminProductStates.content, F.video)
async def msg_admin_product_content_video(message: Message, state: FSMContext):
    uid = message.from_user.id
    _product_drafts[uid]["content_type"] = "video"
    _product_drafts[uid]["content_data"] = message.video.file_id
    await message.answer(
        "📎 Видео получено.\n\n"
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
    product_id = int(callback.data.split(":")[2])
    success = await ProductService.delete_product(product_id)
    if success:
        print("SUCCESS:", success)

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
async def cb_admin_categories(callback: CallbackQuery, db_user: User):
    from services.permission_service import PermissionService
    has_hidden = await PermissionService.has_hidden_access(db_user.telegram_id)
    categories = await ProductService.get_categories(include_hidden=True, trusted=True)
    await callback.message.edit_text(
        "📂 <b>Категории</b>",
        reply_markup=admin_categories_kb(categories, has_hidden_access=has_hidden),
        parse_mode="HTML",
    )
    await callback.answer()


# ── Category Reordering ──────────────────────────────────────

@router.callback_query(F.data.startswith("admin:cat:"))
async def cb_admin_category_action(callback: CallbackQuery, db_user: User):
    """Действия с категорией."""
    parts = callback.data.split(":")

    # Handle admin:cat:ID (view category details)
    if len(parts) == 3 and parts[2].isdigit():
        category_id = int(parts[2])
        category = await ProductService.get_category(category_id)
        if not category:
            await callback.answer("Категория не найдена", show_alert=True)
            return

        from services.permission_service import PermissionService
        has_hidden = await PermissionService.has_hidden_access(db_user.telegram_id)

        hidden = "🔒 скрытая" if category.is_hidden else "✅ видимая"
        text = f"📂 <b>{escape(category.name)}</b>\n\n" f"ID: {category_id}\n" f"Статус: {hidden}\nПорядок: {category.sort_order}"
        await safe_edit_or_send(
            callback, text, reply_markup=admin_category_actions_kb(category_id, has_hidden)
        )
        await callback.answer()
        return

    # Handle admin:cat:action:ID
    if len(parts) >= 4:
        action = parts[2]
        category_id = int(parts[3]) if parts[3].isdigit() else None

        if not category_id:
            await callback.answer("Неверный формат", show_alert=True)
            return

        from services.permission_service import PermissionService
        has_hidden = await PermissionService.has_hidden_access(db_user.telegram_id)

        # Check hidden access for reordering actions
        if action in ["up", "down"] and not has_hidden:
            await callback.answer("⛔ Доступ запрещён", show_alert=True)
            return

        # Validate callback server-side
        if not await PermissionService.validate_callback(callback.data, db_user.telegram_id):
            await callback.answer("⛔ Доступ запрещён", show_alert=True)
            return

        if action == "up":
            success = await ProductService.move_category_up(category_id)
            if success:
                category = await ProductService.get_category(category_id)
                hidden = "🔒 скрытая" if category.is_hidden else "✅ видимая"
                text = (
                    f"📂 <b>{escape(category.name)}</b>\n\n"
                    f"ID: {category_id}\nСтатус: {hidden}\nПорядок: {category.sort_order}"
                )
                await safe_edit_or_send(
                    callback, text, reply_markup=admin_category_actions_kb(category_id, has_hidden)
                )
            await callback.answer("↑ Категория перемещена вверх" if success else "Уже в начале списка")
        elif action == "down":
            success = await ProductService.move_category_down(category_id)
            if success:
                category = await ProductService.get_category(category_id)
                hidden = "🔒 скрытая" if category.is_hidden else "✅ видимая"
                text = (
                    f"📂 <b>{escape(category.name)}</b>\n\n"
                    f"ID: {category_id}\nСтатус: {hidden}\nПорядок: {category.sort_order}"
                )
                await safe_edit_or_send(
                    callback, text, reply_markup=admin_category_actions_kb(category_id, has_hidden)
                )
            await callback.answer("↓ Категория перемещена вниз" if success else "Уже в конце списка")
        elif action == "edit":
            await callback.answer("Редактирование скоро будет доступно")
        elif action == "del":
            await callback.message.edit_text(
                f"🗑 Удалить категорию #{category_id}?",
                reply_markup=confirm_kb(f"admin:cat_del_yes:{category_id}", "admin:categories"),
                parse_mode="HTML",
            )
            await callback.answer()
        return


@router.callback_query(F.data.startswith("admin:cat_del_yes:"))
async def cb_admin_cat_delete_yes(callback: CallbackQuery):
    cat_id = int(callback.data.split(":")[2])
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
        text = (
            "💳 <b>Кошельки</b>\n\n" + "\n".join(lines)
            + "\n\nДобавить: /add_wallet\nУдалить: /delete_wallet"
        )
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


@router.message(Command("delete_wallet"))
async def cmd_delete_wallet(message: Message):
    wallets = await OrderService.get_wallets(active_only=False)
    if not wallets:
        await message.answer("💳 Кошельков пока нет.", reply_markup=admin_panel_kb())
        return
    builder = InlineKeyboardBuilder()
    for w in wallets:
        builder.row(
            InlineKeyboardButton(
                text=f"🗑 {w['network']}: {w['address']}",
                callback_data=f"admin:wallet_del:{w['id']}",
            )
        )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:wallets"))
    await message.answer(
        "💳 Выберите кошелёк для удаления:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^admin:wallet_del:\d+$"))
async def cb_admin_wallet_delete(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])
    wallet = await OrderService.get_wallet(wallet_id)
    if not wallet:
        await callback.answer("Кошелёк не найден", show_alert=True)
        return
    await callback.message.edit_text(
        f"🗑 Удалить кошелёк <b>{escape(wallet['network'])}</b>: "
        f"<code>{escape(wallet['address'])}</code>?",
        reply_markup=confirm_kb(f"admin:wallet_del_yes:{wallet_id}", "admin:wallets"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^admin:wallet_del_yes:\d+$"))
async def cb_admin_wallet_delete_yes(callback: CallbackQuery):
    wallet_id = int(callback.data.split(":")[2])
    success = await OrderService.delete_wallet(wallet_id)
    if success:
        await callback.message.edit_text(
            "✅ Кошелёк удалён",
            reply_markup=admin_panel_kb(),
        )
        await callback.answer()
    else:
        await callback.answer("Ошибка удаления", show_alert=True)


# ── Баланс ───────────────────────────────────────────────

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
    promo_id = int(callback.data.split(":")[2])

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

# ── Реферальная система ─────────────────────────────────────

@router.callback_query(F.data == "admin:ref:menu")
async def cb_admin_ref_menu(callback: CallbackQuery):
    await safe_edit_or_send(
        callback,
        "👥 <b>Реферальная система</b>\n\nВыберите раздел:",
        reply_markup=admin_referral_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:ref:stats")
async def cb_admin_ref_stats(callback: CallbackQuery):
    overview = await ReferralService.get_admin_overview()
    logger.info("Админ просмотрел статистику реферальной системы: admin_id=%s", callback.from_user.id)
    text = (
        "📊 <b>Статистика реферальной системы</b>\n\n"
        f"👥 Всего рефералов: {overview['total_confirmed']}\n"
        f"🆕 За сегодня: {overview['today']}\n"
        f"📅 За неделю: {overview['week']}\n"
        f"🙋 Участников программы: {overview['participants']}\n"
        f"🎁 Выдано наград: {overview['rewards_count']}\n"
        f"🎟 Выдано промокодов: {overview['promos_count']}"
    )
    await safe_edit_or_send(callback, text, reply_markup=admin_referral_back_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:ref:top")
async def cb_admin_ref_top(callback: CallbackQuery):
    top = await ReferralService.get_top_referrers(limit=10)
    if not top:
        text = "🏆 <b>Топ рефералов</b>\n\nПока нет данных."
    else:
        lines = []
        for i, r in enumerate(top, start=1):
            name = r["full_name"] or "—"
            username = f"@{r['username']}" if r["username"] else "—"
            lines.append(
                f"{i}. {escape(name)} ({username}) — ID <code>{r['telegram_id']}</code> "
                f"— {r['cnt']} приглашённых"
            )
        text = "🏆 <b>Топ рефералов</b>\n\n" + "\n".join(lines)
    await safe_edit_or_send(callback, text, reply_markup=admin_referral_back_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:ref:rewards")
async def cb_admin_ref_rewards(callback: CallbackQuery):
    rewards = await ReferralService.get_all_rewards(limit=30)
    if not rewards:
        text = "🎁 <b>Выданные награды</b>\n\nПока нет выданных наград."
    else:
        lines = []
        for r in rewards:
            name = r["full_name"] or (f"@{r['username']}" if r["username"] else f"ID {r['telegram_id']}")
            lines.append(
                f"🎟 <code>{r['promo_code']}</code> — {format_price(r['amount'])}\n"
                f"   👤 {escape(name)} | 📈 {r['referral_count_at_grant']} рефералов | "
                f"📅 {r['created_at']}"
            )
        text = "🎁 <b>Выданные награды</b>\n\n" + "\n\n".join(lines)
    await safe_edit_or_send(callback, text, reply_markup=admin_referral_back_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:ref:settings")
async def cb_admin_ref_settings(callback: CallbackQuery):
    settings = await ReferralService.get_settings()
    text = (
        "⚙ <b>Настройки реферальной системы</b>\n\n"
        f"Статус: {'🟢 включена' if settings.enabled else '🔴 выключена'}\n"
        f"Порог для награды: {settings.threshold} рефералов\n"
        f"Размер награды: {settings.reward_amount:g} ₽\n\n"
        "Изменения применяются сразу, без перезапуска бота."
    )
    await safe_edit_or_send(callback, text, reply_markup=admin_referral_settings_kb(settings.enabled))
    await callback.answer()


@router.callback_query(F.data == "admin:ref:toggle")
async def cb_admin_ref_toggle(callback: CallbackQuery):
    settings = await ReferralService.get_settings()
    new_settings = await ReferralService.update_settings(enabled=not settings.enabled)
    logger.info(
        "Админ изменил настройки реферальной системы: admin_id=%s enabled=%s",
        callback.from_user.id, new_settings.enabled,
    )
    await callback.answer(
        "Программа включена" if new_settings.enabled else "Программа выключена"
    )
    text = (
        "⚙ <b>Настройки реферальной системы</b>\n\n"
        f"Статус: {'🟢 включена' if new_settings.enabled else '🔴 выключена'}\n"
        f"Порог для награды: {new_settings.threshold} рефералов\n"
        f"Размер награды: {new_settings.reward_amount:g} ₽\n\n"
        "Изменения применяются сразу, без перезапуска бота."
    )
    await safe_edit_or_send(callback, text, reply_markup=admin_referral_settings_kb(new_settings.enabled))


@router.callback_query(F.data == "admin:ref:set_threshold")
async def cb_admin_ref_set_threshold(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminReferralSettingsStates.threshold)
    await safe_edit_or_send(
        callback,
        "🔢 Введите новое количество приглашённых пользователей, "
        "необходимое для получения награды (целое число больше 0):",
        reply_markup=back_kb("admin:ref:settings"),
    )
    await callback.answer()


@router.message(AdminReferralSettingsStates.threshold)
async def msg_admin_ref_threshold(message: Message, state: FSMContext):
    try:
        threshold = int(message.text.strip())
        if threshold <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите целое число больше 0")
        return
    new_settings = await ReferralService.update_settings(threshold=threshold)
    await state.clear()
    logger.info(
        "Админ изменил порог рефералов: admin_id=%s threshold=%s",
        message.from_user.id, threshold,
    )
    await message.answer(
        f"✅ Порог обновлён: {new_settings.threshold} рефералов",
        reply_markup=admin_referral_settings_kb(new_settings.enabled),
    )


@router.callback_query(F.data == "admin:ref:set_amount")
async def cb_admin_ref_set_amount(callback: CallbackQuery, state: FSMContext):
    await state.set_state(AdminReferralSettingsStates.reward_amount)
    await safe_edit_or_send(
        callback,
        "💰 Введите новый размер награды в рублях (число больше 0):",
        reply_markup=back_kb("admin:ref:settings"),
    )
    await callback.answer()


@router.message(AdminReferralSettingsStates.reward_amount)
async def msg_admin_ref_amount(message: Message, state: FSMContext):
    amount = validate_price(message.text)
    if amount is None:
        await message.answer("❌ Введите корректную сумму (число больше 0)")
        return
    new_settings = await ReferralService.update_settings(reward_amount=amount)
    await state.clear()
    logger.info(
        "Админ изменил размер награды: admin_id=%s amount=%s",
        message.from_user.id, amount,
    )
    await message.answer(
        f"✅ Размер награды обновлён: {format_price(new_settings.reward_amount)}",
        reply_markup=admin_referral_settings_kb(new_settings.enabled),
    )


# ── VIP Admin ───────────────────────────────────────────────

@router.callback_query(F.data == "admin:vip")
async def cb_admin_vip(callback: CallbackQuery):
    """VIP-меню админки."""
    from services.vip_service import VIPService
    
    settings = await VIPService.get_settings()
    text = (
        "⭐ <b>VIP-доступ</b>\n\n"
        f"Статус: {'✅ Включен' if settings.enabled else '❌ Выключен'}\n"
        f"Стоимость: {format_price(settings.price)}\n"
        f"Скидка: {settings.discount_percent}%"
    )
    await safe_edit_or_send(callback, text, reply_markup=admin_vip_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:vip:settings")
async def cb_admin_vip_settings(callback: CallbackQuery):
    """Настройки VIP."""
    from services.vip_service import VIPService
    
    settings = await VIPService.get_settings()
    text = (
        "⚙️ <b>Настройки VIP</b>\n\n"
        f"Включено: {'✅ Да' if settings.enabled else '❌ Нет'}\n"
        f"Стоимость: {format_price(settings.price)}\n"
        f"Скидка: {settings.discount_percent}%"
    )
    await safe_edit_or_send(
        callback, text, reply_markup=admin_vip_settings_kb({"enabled": settings.enabled})
    )
    await callback.answer()


@router.callback_query(F.data == "admin:vip:toggle_enabled")
async def cb_admin_vip_toggle(callback: CallbackQuery):
    """Переключить VIP."""
    from services.vip_service import VIPService
    
    settings = await VIPService.get_settings()
    new_settings = await VIPService.update_settings(
        enabled=not settings.enabled,
        price=settings.price,
        discount_percent=settings.discount_percent,
    )
    await callback.answer(
        "VIP включен" if new_settings.enabled else "VIP выключен"
    )
    text = (
        "⚙️ <b>Настройки VIP</b>\n\n"
        f"Включено: {'✅ Да' if new_settings.enabled else '❌ Нет'}\n"
        f"Стоимость: {format_price(new_settings.price)}\n"
        f"Скидка: {new_settings.discount_percent}%"
    )
    await safe_edit_or_send(
        callback, text, reply_markup=admin_vip_settings_kb({"enabled": new_settings.enabled})
    )


@router.callback_query(F.data == "admin:vip:set_price")
async def cb_admin_vip_set_price(callback: CallbackQuery, state: FSMContext):
    """Установить цену VIP."""
    await state.set_state(AdminVIPSettingsStates.price)
    await state.update_data(vip_setting_action="price")
    await safe_edit_or_send(
        callback,
        "💰 Введите новую стоимость VIP в рублях:",
        reply_markup=back_kb("admin:vip:settings"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:vip:set_discount")
async def cb_admin_vip_set_discount(callback: CallbackQuery, state: FSMContext):
    """Установить скидку VIP."""
    await state.set_state(AdminVIPSettingsStates.discount)
    await state.update_data(vip_setting_action="discount")
    await safe_edit_or_send(
        callback,
        "🎁 Введите новую скидку VIP в процентах (0-100):",
        reply_markup=back_kb("admin:vip:settings"),
    )
    await callback.answer()


@router.message(AdminVIPSettingsStates.price)
async def msg_admin_vip_price(message: Message, state: FSMContext, db_user: User):
    """Обработка ввода цены VIP."""
    from services.vip_service import VIPService
    
    amount = validate_price(message.text)
    if amount is None:
        await message.answer("❌ Введите корректное число")
        return
    
    settings = await VIPService.get_settings()
    new_settings = await VIPService.update_settings(
        enabled=settings.enabled,
        price=amount,
        discount_percent=settings.discount_percent,
    )
    await state.clear()
    await message.answer(
        f"✅ Цена VIP обновлена: {format_price(new_settings.price)}",
        reply_markup=admin_vip_kb(),
    )


@router.message(AdminVIPSettingsStates.discount)
async def msg_admin_vip_discount(message: Message, state: FSMContext, db_user: User):
    """Обработка ввода скидки VIP."""
    from services.vip_service import VIPService
    
    try:
        discount = int(message.text.strip())
        if not 0 <= discount <= 100:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число от 0 до 100")
        return
    
    settings = await VIPService.get_settings()
    new_settings = await VIPService.update_settings(
        enabled=settings.enabled,
        price=settings.price,
        discount_percent=discount,
    )
    await state.clear()
    await message.answer(
        f"✅ Скидка VIP обновлена: {new_settings.discount_percent}%",
        reply_markup=admin_vip_kb(),
    )


@router.callback_query(F.data == "admin:vip:list")
async def cb_admin_vip_list(callback: CallbackQuery):
    """Список VIP-пользователей."""
    from services.vip_service import VIPService
    
    vip_users = await VIPService.get_vip_users()
    if not vip_users:
        text = "👥 <b>VIP-пользователи</b>\n\nПока нет VIP-пользователей."
    else:
        lines = []
        for u in vip_users[:50]:
            username = f"@{u.username}" if u.username else "—"
            lines.append(
                f"👤 {username} (ID: <code>{u.telegram_id}</code>)\n"
                f"   Баланс: {format_price(u.balance)}\n"
                f"   Выдан: {u.vip_purchased_at or '—'}"
            )
        text = "👥 <b>VIP-пользователи</b>\n\n" + "\n\n".join(lines)
    await safe_edit_or_send(callback, text, reply_markup=admin_vip_kb())
    await callback.answer()


@router.callback_query(F.data == "admin:vip:grant")
async def cb_admin_vip_grant(callback: CallbackQuery, state: FSMContext):
    """Выдать VIP пользователю."""
    await state.set_state(AdminVIPGrantStates.search)
    await safe_edit_or_send(
        callback,
        "👤 Введите <b>Telegram ID</b> или <b>@username</b> пользователя для выдачи VIP:",
        reply_markup=back_kb("admin:vip"),
    )
    await callback.answer()


@router.message(AdminVIPGrantStates.search)
async def msg_admin_vip_grant_search(message: Message, state: FSMContext, db_user: User):
    """Найти пользователя и выдать ему VIP."""
    from services.vip_service import VIPService

    users = await UserService.search_by_username_or_id(message.text.strip())
    if not users:
        await message.answer("❌ Пользователь не найден", reply_markup=admin_vip_kb())
        await state.clear()
        return

    target = users[0]
    settings = await VIPService.get_settings()
    await VIPService.grant_vip(target.id, 0, "admin_grant", str(db_user.telegram_id))

    from services.secret_access_service import SecretAccessService
    await SecretAccessService.log_admin_action(
        db_user.telegram_id, "vip_grant", target=str(target.telegram_id),
    )

    username = f"@{target.username}" if target.username else "—"
    await message.answer(
        f"✅ VIP-доступ выдан пользователю {username} (ID: <code>{target.telegram_id}</code>)\n"
        f"🎁 Скидка: {settings.discount_percent}%",
        reply_markup=admin_vip_kb(),
        parse_mode="HTML",
    )
    await state.clear()


# ── Секретный доступ ──────────────────────────────────────────

@router.callback_query(F.data == "admin:secret")
async def cb_admin_secret_menu(callback: CallbackQuery, db_user: User):
    """Меню управления секретным доступом."""
    from services.permission_service import PermissionService

    if not await PermissionService.has_hidden_access(db_user.telegram_id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await safe_edit_or_send(
        callback,
        "🔐 <b>Секретный доступ</b>\n\n"
        "Здесь можно выдать или забрать расширенный (скрытый) доступ "
        "у пользователя, а также посмотреть список и журнал действий.",
        reply_markup=secret_access_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:secret:grant")
async def cb_admin_secret_grant(callback: CallbackQuery, state: FSMContext, db_user: User):
    """Начать выдачу секретного доступа."""
    from services.permission_service import PermissionService

    if not await PermissionService.has_hidden_access(db_user.telegram_id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(SecretAccessStates.grant_id)
    await safe_edit_or_send(
        callback,
        "🔐 Введите <b>Telegram ID</b> пользователя, которому нужно выдать секретный доступ:",
        reply_markup=back_kb("admin:secret"),
    )
    await callback.answer()


@router.message(SecretAccessStates.grant_id)
async def msg_admin_secret_grant(message: Message, state: FSMContext, db_user: User):
    """Обработать ввод ID и выдать секретный доступ."""
    from services.permission_service import PermissionService
    from services.secret_access_service import SecretAccessService

    if not await PermissionService.has_hidden_access(db_user.telegram_id):
        await message.answer("⛔ Доступ запрещён")
        await state.clear()
        return

    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Введите числовой Telegram ID:")
        return

    target_id = int(text)
    try:
        await SecretAccessService.grant(target_id, db_user.telegram_id)
        await SecretAccessService.log_admin_action(
            db_user.telegram_id, "secret_access_grant", target=str(target_id),
        )
        await message.answer(
            f"✅ Секретный доступ выдан пользователю <code>{target_id}</code>",
            reply_markup=secret_access_kb(),
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Ошибка выдачи секретного доступа: %s", exc)
        await message.answer(f"❌ Ошибка: {exc}", reply_markup=secret_access_kb())
    await state.clear()


@router.callback_query(F.data == "admin:secret:revoke")
async def cb_admin_secret_revoke(callback: CallbackQuery, state: FSMContext, db_user: User):
    """Начать отзыв секретного доступа."""
    from services.permission_service import PermissionService

    if not await PermissionService.has_hidden_access(db_user.telegram_id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    await state.set_state(SecretAccessStates.revoke_id)
    await safe_edit_or_send(
        callback,
        "🔐 Введите <b>Telegram ID</b> пользователя, у которого нужно забрать секретный доступ:",
        reply_markup=back_kb("admin:secret"),
    )
    await callback.answer()


@router.message(SecretAccessStates.revoke_id)
async def msg_admin_secret_revoke(message: Message, state: FSMContext, db_user: User):
    """Обработать ввод ID и забрать секретный доступ."""
    from services.permission_service import PermissionService
    from services.secret_access_service import SecretAccessService

    if not await PermissionService.has_hidden_access(db_user.telegram_id):
        await message.answer("⛔ Доступ запрещён")
        await state.clear()
        return

    text = message.text.strip()
    if not text.isdigit():
        await message.answer("❌ Введите числовой Telegram ID:")
        return

    target_id = int(text)
    try:
        success = await SecretAccessService.revoke(target_id, db_user.telegram_id)
        await SecretAccessService.log_admin_action(
            db_user.telegram_id, "secret_access_revoke", target=str(target_id),
            details="ok" if success else "not_found",
        )
        if success:
            await message.answer(
                f"✅ Секретный доступ у пользователя <code>{target_id}</code> отозван",
                reply_markup=secret_access_kb(),
                parse_mode="HTML",
            )
        else:
            await message.answer(
                f"⚠️ У пользователя <code>{target_id}</code> не было активного секретного доступа",
                reply_markup=secret_access_kb(),
                parse_mode="HTML",
            )
    except Exception as exc:
        logger.error("Ошибка отзыва секретного доступа: %s", exc)
        await message.answer(f"❌ Ошибка: {exc}", reply_markup=secret_access_kb())
    await state.clear()


@router.callback_query(F.data == "admin:secret:list")
async def cb_admin_secret_list(callback: CallbackQuery, db_user: User):
    """Список пользователей с секретным доступом."""
    from services.permission_service import PermissionService
    from services.secret_access_service import SecretAccessService

    if not await PermissionService.has_hidden_access(db_user.telegram_id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    entries = await SecretAccessService.list_active()
    if not entries:
        text = "🔐 <b>Секретный доступ</b>\n\nСейчас ни у кого нет секретного доступа."
    else:
        lines = []
        for e in entries[:50]:
            lines.append(
                f"👤 ID: <code>{e['telegram_id']}</code>\n"
                f"   Выдал: {e['granted_by'] or '—'}\n"
                f"   Дата: {e['created_at']}"
            )
        text = "🔐 <b>Пользователи с секретным доступом</b>\n\n" + "\n\n".join(lines)
    await safe_edit_or_send(callback, text, reply_markup=secret_access_kb())
    await callback.answer()
@router.callback_query(F.data == "admin:secret:log")
async def cb_admin_secret_log(callback: CallbackQuery, db_user: User):
    """Журнал действий администраторов по секретному доступу."""
    from services.permission_service import PermissionService
    from services.secret_access_service import SecretAccessService

    if not await PermissionService.has_hidden_access(db_user.telegram_id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return

    entries = await SecretAccessService.get_action_log(limit=20)
    if not entries:
        text = "📋 <b>Журнал действий</b>\n\nПока нет записей."
    else:
        lines = []
        for e in entries:
            lines.append(
                f"🕒 {e['created_at']}\n"
                f"👤 Админ: <code>{e['admin_telegram_id']}</code>\n"
                f"⚙️ {escape(e['action'])} → {escape(e['target'] or '—')}"
            )
        text = "📋 <b>Журнал действий администраторов</b>\n\n" + "\n\n".join(lines)
    await safe_edit_or_send(callback, text, reply_markup=secret_access_kb())
    await callback.answer()


# ── Category Reordering ──────────────────────────────────────

@router.callback_query(F.data.startswith("admin:cat:"))
async def cb_admin_category_action(callback: CallbackQuery, db_user: User):
    """Действия с категорией."""
    parts = callback.data.split(":")
    
    # Handle admin:cat:ID (view category details)
    if len(parts) == 3 and parts[2].isdigit():
        category_id = int(parts[2])
        category = await ProductService.get_category(category_id)
        if not category:
            await callback.answer("Категория не найдена", show_alert=True)
            return
        
        from services.permission_service import PermissionService
        has_hidden = PermissionService.has_hidden_access(db_user.telegram_id)
        
        hidden = "🔒 скрытая" if category.is_hidden else "✅ видимая"
        text = f"📂 <b>{escape(category.name)}</b>\n\n" f"ID: {category_id}\n" f"Статус: {hidden}\nПорядок: {category.sort_order}"
        await safe_edit_or_send(
            callback, text, reply_markup=admin_category_actions_kb(category_id, has_hidden)
        )
        await callback.answer()
        return
    
    # Handle admin:cat:action:ID
    if len(parts) >= 4:
        action = parts[2]
        category_id = int(parts[3]) if parts[3].isdigit() else None
        
        if not category_id:
            await callback.answer("Неверный формат", show_alert=True)
            return
        
        from services.permission_service import PermissionService
        has_hidden = PermissionService.has_hidden_access(db_user.telegram_id)
        
        # Check hidden access for reordering actions
        if action in ["up", "down"] and not has_hidden:
            await callback.answer("⛔ Доступ запрещён", show_alert=True)
            return
        
        # Validate callback server-side
        if not await PermissionService.validate_callback(callback.data, db_user.telegram_id):
            await callback.answer("⛔ Доступ запрещён", show_alert=True)
            return
        
        if action == "up":
            success = await ProductService.move_category_up(category_id)
            await callback.answer("↑ Категория перемещена вверх" if success else "Ошибка")
        elif action == "down":
            success = await ProductService.move_category_down(category_id)
            await callback.answer("↓ Категория перемещена вниз" if success else "Ошибка")
        elif action == "edit":
            # TODO: Add edit functionality
            await callback.answer("Редактирование скоро будет доступно")
        elif action == "del":
            # Show delete confirmation
            await callback.message.edit_text(
                f"🗑 Удалить категорию #{category_id}?",
                reply_markup=confirm_kb(f"admin:cat_del_yes:{category_id}", "admin:categories"),
                parse_mode="HTML",
            )
            await callback.answer()
        return
    
    await callback.answer("Неверный формат", show_alert=True)