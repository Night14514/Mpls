"""
Маркет: категории, товары, покупка за баланс.
"""

import logging
import uuid

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from handlers.registration import start_registration
from keyboards import (
    back_to_menu_kb,
    categories_kb,
    insufficient_balance_kb,
    product_card_kb,
    products_kb,
)
from models import User
from services.order_service import OrderService, STATUS_COMPLETED, STATUS_PAID
from services.product_service import ProductService
from services.user_service import UserService
from utils import format_price, format_product_card, get_product_price, safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router(name="catalog")


async def _check_registered(callback: CallbackQuery, db_user: User, state: FSMContext) -> bool:
    if not db_user.is_registered:
        await callback.answer("Сначала пройдите регистрацию", show_alert=True)
        await start_registration(callback.message, state)
        return False
    return True


@router.callback_query(F.data == "menu:market")
@router.callback_query(F.data == "menu:catalog")
async def cb_market(callback: CallbackQuery, db_user: User, state: FSMContext):
    """Маркет — список категорий."""
    if not await _check_registered(callback, db_user, state):
        return

    categories = await ProductService.get_categories(trusted=db_user.is_trusted)
    visible = [c for c in categories if not c.is_hidden or db_user.is_trusted]

    if not visible:
        await safe_edit_or_send(
            callback,
            "🛍 <b>Маркет</b>\n\n"
            "Товары временно отсутствуют.",
            reply_markup=back_to_menu_kb(),
        )
    else:
        await safe_edit_or_send(
            callback,
            "🛍 <b>Маркет</b>\n\nВыберите категорию:",
            reply_markup=categories_kb(visible),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def cb_category(callback: CallbackQuery, db_user: User, state: FSMContext):
    """Товары в категории."""
    if not await _check_registered(callback, db_user, state):
        return

    category_id = int(callback.data.split(":")[1])
    category = await ProductService.get_category(category_id)
    if not category:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    if category.is_hidden and not db_user.is_trusted:
        await callback.answer("🔒 Доступ запрещён", show_alert=True)
        return

    products = await ProductService.get_products_by_category(category_id, db_user.is_trusted)
    if not products:
        await safe_edit_or_send(
            callback,
            f"📂 <b>{category.name}</b>\n\n"
            "В этой категории пока нет товаров.",
            reply_markup=back_to_menu_kb(),
        )
    else:
        await safe_edit_or_send(
            callback,
            f"📂 <b>{category.name}</b>\n\nВыберите товар:",
            reply_markup=products_kb(products, category_id),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("products_page:"))
async def cb_products_page(callback: CallbackQuery, db_user: User):
    parts = callback.data.split(":")
    category_id = int(parts[1])
    page = int(parts[2])
    products = await ProductService.get_products_by_category(category_id, db_user.is_trusted)
    category = await ProductService.get_category(category_id)
    await safe_edit_or_send(
        callback,
        f"📂 <b>{category.name}</b>\n\nВыберите товар:",
        reply_markup=products_kb(products, category_id, page=page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("product:"))
async def cb_product(callback: CallbackQuery, db_user: User):
    """Карточка товара."""
    product_id = int(callback.data.split(":")[1])
    product = await ProductService.get_product(product_id)
    if not product or not product.is_active:
        await callback.answer("Товар не найден", show_alert=True)
        return

    if product.is_hidden and not db_user.is_trusted:
        await callback.answer("🔒 Товар недоступен", show_alert=True)
        return

    text = format_product_card(product)
    kb = product_card_kb(product_id, product.category_id)

    if product.photo:
        try:
            await callback.message.delete()
            await callback.message.answer_photo(
                photo=product.photo,
                caption=text,
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        try:
            await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("buy_balance:"))
async def cb_buy_balance(callback: CallbackQuery, db_user: User):
    """Покупка товара за баланс."""
    product_id = int(callback.data.split(":")[1])
    product = await ProductService.get_product(product_id)
    if not product or not product.is_active:
        await callback.answer("Товар не найден", show_alert=True)
        return

    user = await UserService.get_by_telegram_id(db_user.telegram_id)
    price = get_product_price(product)
    if user.balance < price:
        text = (
            "❌ <b>Недостаточно средств</b>\n\n"
            f"Стоимость: {format_price(price)}\n"
            f"Ваш баланс: {format_price(user.balance)}\n\n"
            "Пополните баланс для покупки."
        )
        await safe_edit_or_send(
            callback, text, reply_markup=insufficient_balance_kb()
        )
        await callback.answer()
        return

    new_balance = await UserService.adjust_balance(user.id, -price)
    if new_balance is None:
        await callback.answer("Ошибка списания", show_alert=True)
        return

    payment_id = f"balance_{uuid.uuid4().hex[:12]}"
    order = await OrderService.create_order(
        user_id=user.id,
        product_id=product_id,
        price=price,
        payment_method="balance",
        status=STATUS_PAID,
    )
    await OrderService.update_status(order.id, STATUS_COMPLETED, payment_id=payment_id)
    await OrderService.create_payment(
        user_id=user.id,
        order_id=order.id,
        provider="balance",
        provider_payment_id=payment_id,
        amount=price,
        currency="RUB",
        status="paid",
    )
    await OrderService.deliver_content(callback.bot, user.telegram_id, order.id)

    confirm_text = (
        "✅ <b>Покупка оформлена!</b>\n\n"
        f"🛍 {product.title}\n"
        f"💰 Списано: {format_price(price)}\n"
        f"💳 Остаток: {format_price(new_balance)}"
    )
    await safe_edit_or_send(callback, confirm_text, reply_markup=back_to_menu_kb())
    await callback.answer("✅ Покупка успешна!")


# ── Legacy: корзина, VIP, избранное ─────────────────────────

@router.callback_query(F.data == "menu:vip")
async def cb_vip(callback: CallbackQuery, db_user: User):
    if not db_user.is_trusted:
        await callback.answer("⭐ VIP-доступ не активирован", show_alert=True)
        return
    categories = await ProductService.get_categories(trusted=True)
    hidden = [c for c in categories if c.is_hidden]
    if not hidden:
        await callback.message.edit_text(
            "⭐ VIP — скрытых категорий нет.",
            reply_markup=back_to_menu_kb(),
        )
    else:
        await callback.message.edit_text(
            "⭐ VIP Раздел:",
            reply_markup=categories_kb(hidden, prefix="cat"),
        )
    await callback.answer()


@router.callback_query(F.data == "menu:cart")
async def cb_cart(callback: CallbackQuery, db_user: User):
    from keyboards import cart_kb
    from utils import format_cart_summary

    items, total, count = await ProductService.cart_total(db_user.id)
    if not items:
        await callback.message.edit_text("🛒 Корзина пуста.", reply_markup=back_to_menu_kb())
    else:
        product_ids = [i["product_id"] for i in items]
        lines = "\n".join(
            f"• {i['title']} × {i['quantity']} — {format_price(i['price'] * i['quantity'])}"
            for i in items
        )
        text = format_cart_summary(count, total) + f"\n\n{lines}"
        await callback.message.edit_text(text, reply_markup=cart_kb(product_ids), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("cart_add:"))
async def cb_cart_add(callback: CallbackQuery, db_user: User):
    product_id = int(callback.data.split(":")[1])
    await ProductService.add_to_cart(db_user.id, product_id)
    await callback.answer("✅ Добавлено в корзину")


@router.callback_query(F.data.startswith("cart_inc:"))
async def cb_cart_inc(callback: CallbackQuery, db_user: User):
    product_id = int(callback.data.split(":")[1])
    await ProductService.update_cart_qty(db_user.id, product_id, 1)
    await cb_cart(callback, db_user)


@router.callback_query(F.data.startswith("cart_dec:"))
async def cb_cart_dec(callback: CallbackQuery, db_user: User):
    product_id = int(callback.data.split(":")[1])
    await ProductService.update_cart_qty(db_user.id, product_id, -1)
    await cb_cart(callback, db_user)


@router.callback_query(F.data == "cart_clear")
async def cb_cart_clear(callback: CallbackQuery, db_user: User):
    await ProductService.clear_cart(db_user.id)
    await callback.answer("🗑 Корзина очищена")
    await cb_cart(callback, db_user)
