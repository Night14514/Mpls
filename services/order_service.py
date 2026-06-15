"""Order service adapter.

The protected order lifecycle lives in ``core.order_engine``. This module keeps
the existing imports and Telegram delivery behavior stable for handlers.
"""

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import FSInputFile

from core.order_engine import (
    OrderEngine,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_WAITING,
)
from services.product_service import ProductService
from utils import parse_content_data

logger = logging.getLogger(__name__)


class OrderService(OrderEngine):
    """Compatibility facade for order operations used by bot handlers."""

    @classmethod
    async def create_cart_order(cls, user_id: int, payment_method: str):
        """Create an order from the current cart."""
        items, total, _ = await ProductService.cart_total(user_id)
        return await cls.create_cart_order_from_items(user_id, payment_method, items, total)

    @classmethod
    async def deliver_content(cls, bot: Bot, telegram_id: int, order_id: int) -> None:
        """Automatically deliver digital product content after successful payment."""
        order = await cls.get_order(order_id)
        if not order:
            return

        products_to_deliver = []
        if order.product_id:
            product = await ProductService.get_product(order.product_id)
            if product:
                products_to_deliver.append(product)
        else:
            items = await cls.get_order_items(order_id)
            for item in items:
                product = await ProductService.get_product(item["product_id"])
                if product:
                    products_to_deliver.append(product)

        for product in products_to_deliver:
            await cls._send_product_content(bot, telegram_id, product)

        await ProductService.clear_cart(order.user_id)
        await cls.update_status(order_id, STATUS_COMPLETED)

    @classmethod
    async def _send_product_content(cls, bot: Bot, telegram_id: int, product) -> None:
        content = parse_content_data(product.content_data or "")
        ctype = content.get("type", "text")
        data = content.get("data", "")
        header = f"📦 <b>{product.title}</b>\n\nВаш цифровой товар:\n\n"

        try:
            if ctype == "link":
                await bot.send_message(
                    telegram_id,
                    f'{header}🔗 <a href="{data}">Перейти по ссылке</a>',
                    parse_mode="HTML",
                )
            elif ctype == "file":
                if data.startswith("http"):
                    await bot.send_message(
                        telegram_id,
                        f'{header}📎 <a href="{data}">Скачать файл</a>',
                        parse_mode="HTML",
                    )
                else:
                    await bot.send_document(telegram_id, FSInputFile(data), caption=product.title)
            elif ctype == "code":
                await bot.send_message(
                    telegram_id,
                    f"{header}🔑 Код доступа:\n<code>{data}</code>",
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(telegram_id, f"{header}{data}", parse_mode="HTML")
        except Exception as exc:
            logger.error("Ошибка выдачи контента товара %s: %s", product.id, exc)
            await bot.send_message(
                telegram_id,
                "⚠️ Не удалось автоматически выдать товар. Обратитесь в поддержку.",
            )


__all__ = [
    "OrderService",
    "STATUS_PENDING",
    "STATUS_CONFIRMED",
    "STATUS_WAITING",
    "STATUS_PAID",
    "STATUS_COMPLETED",
    "STATUS_CANCELLED",
]
