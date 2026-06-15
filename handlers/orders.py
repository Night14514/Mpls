"""
История заказов пользователя.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards import back_to_menu_kb, orders_kb
from models import User
from services.order_service import OrderService
from utils import format_order_card

logger = logging.getLogger(__name__)
router = Router(name="orders")


@router.callback_query(F.data == "menu:orders")
@router.callback_query(F.data == "menu:my_orders")
async def cb_orders(callback: CallbackQuery, db_user: User):
    """Список заказов."""
    orders = await OrderService.get_user_orders(db_user.id)
    if not orders:
        await callback.message.edit_text(
            "📦 У вас пока нет заказов.",
            reply_markup=back_to_menu_kb(),
        )
    else:
        await callback.message.edit_text(
            "📦 <b>Мои заказы</b>\n\nВыберите заказ:",
            reply_markup=orders_kb(orders),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data.startswith("orders_section:"))
async def cb_orders_section(callback: CallbackQuery):
    await callback.answer("Раздел заказов")


@router.callback_query(F.data.startswith("orders_page:"))
async def cb_orders_page(callback: CallbackQuery, db_user: User):
    page = int(callback.data.split(":")[1])
    orders = await OrderService.get_user_orders(db_user.id)
    await callback.message.edit_text(
        "📦 <b>Мои заказы</b>\n\nВыберите заказ:",
        reply_markup=orders_kb(orders, page=page),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("order:"))
async def cb_order_detail(callback: CallbackQuery, db_user: User):
    """Детали заказа."""
    order_id = int(callback.data.split(":")[1])
    order = await OrderService.get_order(order_id)
    if not order or order.user_id != db_user.id:
        await callback.answer("Заказ не найден", show_alert=True)
        return

    text = format_order_card(order)
    await callback.message.edit_text(
        text,
        reply_markup=back_to_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()
