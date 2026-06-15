"""
Вспомогательные функции: форматирование, валидация, логирование.
"""

import html
import logging
import re
from datetime import datetime
from typing import Optional

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from core.order_engine import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_PENDING,
    normalize_order_status,
)
from models import Order, Product

logger = logging.getLogger(__name__)


def escape(text: Optional[str]) -> str:
    """Экранирование HTML для Telegram."""
    if not text:
        return ""
    return html.escape(str(text))


def format_price(price: float) -> str:
    """Форматирование цены (баланс)."""
    if price == int(price):
        return f"{int(price)}"
    return f"{price:.2f}"


def format_price_crypto(price: float, asset: str = "USDT") -> str:
    """Форматирование цены в криптовалюте."""
    return f"{price:.2f} {asset}"


def format_price_multicurrency(price_usd: Optional[float], price_rub: Optional[float]) -> str:
    """Форматирование цены в нескольких валютах."""
    lines = ["💰 Цена:"]
    if price_usd is not None:
        lines.append(f"  USD: ${format_price(price_usd)}")
    if price_rub is not None:
        lines.append(f"  RUB: ₽{format_price(price_rub)}")
    return "\n".join(lines)


def format_product_card(product: Product, category_name: Optional[str] = None) -> str:
    """Карточка товара для маркета."""
    # Try to use multicurrency formatting if available
    price_usd = getattr(product, "price_usd", None)
    price_rub = getattr(product, "price_rub", None)
    
    if price_usd is not None or price_rub is not None:
        price_line = format_price_multicurrency(price_usd, price_rub)
    else:
        price_line = f"� Цена: {format_price(product.price)}"
    
    return (
        f"�🛍 <b>{escape(product.title)}</b>\n\n"
        f"📄 {escape(product.description or 'Описание отсутствует')}\n\n"
        f"{price_line}"
    )


def format_order_card(order: Order) -> str:
    """Карточка заказа для пользователя."""
    status_map = {
        STATUS_PENDING: "⏳ Ожидает",
        STATUS_CONFIRMED: "✅ Подтверждён",
        STATUS_COMPLETED: "✅ Выполнен",
        STATUS_CANCELLED: "❌ Отменён",
    }
    status = normalize_order_status(order.status)
    status_text = status_map.get(status, status)
    try:
        dt = datetime.fromisoformat(order.created_at.replace("Z", ""))
        date_str = dt.strftime("%d.%m.%Y %H:%M")
    except (ValueError, AttributeError):
        date_str = order.created_at or "—"

    title = escape(order.product_title or "Корзина")
    return (
        f"📦 <b>Заказ #{order.id}</b>\n\n"
        f"🛍 Товар: {title}\n\n"
        f"Статус:\n{status_text}\n\n"
        f"Дата:\n{date_str}\n\n"
        f"Сумма:\n{format_price(order.price)}"
    )


def format_cart_summary(items_count: int, total: float) -> str:
    """Сводка корзины."""
    return (
        "🛒 <b>Корзина</b>\n\n"
        f"Товаров: {items_count}\n\n"
        f"<b>Итого:</b>\n{format_price(total)}\n\n"
        "Выберите способ оплаты:"
    )


def validate_price(text: str) -> Optional[float]:
    """Валидация цены."""
    text = text.strip().replace(",", ".")
    try:
        price = float(text)
        if price <= 0:
            return None
        return price
    except ValueError:
        return None


def validate_tx_hash(text: str) -> bool:
    """Базовая валидация TX Hash / Invoice ID."""
    text = text.strip()
    if len(text) < 8:
        return False
    return bool(re.match(r"^[a-zA-Z0-9_\-]+$", text))


def parse_content_data(content: str) -> dict:
    """
    Парсинг content_data товара.
    Формат JSON-подобный или простой:
    type:link|url:https://...
    type:text|data:текст
    type:code|data:ABC123
    type:file|path:/path или file_id
    """
    result = {"type": "text", "data": content}
    if not content:
        return result

    if content.startswith("type:"):
        parts = {}
        for segment in content.split("|"):
            if ":" in segment:
                key, val = segment.split(":", 1)
                parts[key] = val
        result["type"] = parts.get("type", "text")
        result["data"] = parts.get("data") or parts.get("url") or parts.get("path") or content
    elif content.startswith("http"):
        result = {"type": "link", "data": content}
    return result


def setup_logging(level: str = "INFO") -> None:
    """Настройка логирования."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def safe_edit_or_send(
    callback: CallbackQuery,
    text: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML",
) -> None:
    """
    Безопасно обновить сообщение или отправить новое.
    Нужно, когда предыдущее сообщение — фото (edit_text невозможен).
    """
    msg = callback.message
    try:
        if msg.photo:
            await msg.delete()
            await msg.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramBadRequest:
        await msg.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
