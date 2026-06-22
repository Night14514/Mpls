"""
Сервис VIP-доступа.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Optional

from config import get_settings
from database import get_db, transaction
from models import VIPSettings, User

logger = logging.getLogger(__name__)


class VIPService:
    """Управление VIP-доступом."""

    @staticmethod
    def _row_to_vip_settings(row) -> VIPSettings:
        return VIPSettings(
            enabled=bool(row["enabled"]),
            price=row["price"],
            discount_percent=row["discount_percent"],
            updated_at=row["updated_at"],
        )

    @classmethod
    async def get_settings(cls) -> VIPSettings:
        """Получить настройки VIP."""
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM vip_settings WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return cls._row_to_vip_settings(row)
            # Fallback to config defaults
            settings = get_settings()
            return VIPSettings(
                enabled=settings.VIP_ENABLED,
                price=settings.VIP_PRICE,
                discount_percent=settings.VIP_DISCOUNT_PERCENT,
                updated_at="",
            )

    @classmethod
    async def update_settings(cls, enabled: bool, price: float, discount_percent: int) -> bool:
        """Обновить настройки VIP."""
        async with get_db() as db:
            await db.execute(
                """UPDATE vip_settings
                   SET enabled = ?, price = ?, discount_percent = ?, updated_at = datetime('now')
                   WHERE id = 1""",
                (1 if enabled else 0, price, discount_percent),
            )
            return True

    @classmethod
    async def is_vip(cls, user: User) -> bool:
        """Проверить, есть ли у пользователя VIP."""
        if not user.is_vip:
            return False
        # Check if VIP is expired
        if user.vip_expiry:
            try:
                expiry = datetime.fromisoformat(user.vip_expiry)
                if datetime.now() > expiry:
                    # Expired - remove VIP status
                    await cls.remove_vip(user.id)
                    return False
            except (ValueError, TypeError):
                logger.warning("Invalid vip_expiry format for user %s", user.id)
        return True

    @classmethod
    async def get_vip_users(cls) -> List[User]:
        """Получить всех VIP-пользователей."""
        from services.user_service import UserService

        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM users WHERE is_vip = 1")
            rows = await cursor.fetchall()
            return [UserService._row_to_user(r) for r in rows]

    @classmethod
    async def grant_vip(cls, user_id: int, amount: float = 0, payment_method: str = "manual", payment_id: Optional[str] = None) -> bool:
        """Выдать VIP пользователю."""
        async with transaction("IMMEDIATE") as db:
            # Calculate expiry (1 year from now by default, or permanent if amount > 0)
            if amount > 0:
                # Record the purchase
                await db.execute(
                    """INSERT INTO vip_purchases (user_id, amount, payment_method, payment_id, status)
                       VALUES (?, ?, ?, ?, 'completed')""",
                    (user_id, amount, payment_method, payment_id),
                )
            
            # Set VIP as permanent (no expiry) for purchases
            expiry = None
            
            await db.execute(
                """UPDATE users
                   SET is_vip = 1, vip_purchased_at = datetime('now'), vip_expiry = ?
                   WHERE id = ?""",
                (expiry, user_id),
            )
            return True

    @classmethod
    async def remove_vip(cls, user_id: int) -> bool:
        """Снять VIP с пользователя."""
        async with get_db() as db:
            await db.execute(
                """UPDATE users
                   SET is_vip = 0, vip_purchased_at = NULL, vip_expiry = NULL
                   WHERE id = ?""",
                (user_id,),
            )
            return True

    @classmethod
    async def calculate_discounted_price(cls, price: float, user: User) -> float:
        """Рассчитать цену со скидкой VIP."""
        if not await cls.is_vip(user):
            return price
        settings = await cls.get_settings()
        if not settings.enabled:
            return price
        discount = price * (settings.discount_percent / 100)
        return round(price - discount, 2)

    @classmethod
    async def get_vip_status_text(cls, user: User) -> str:
        """Получить текст статуса VIP для пользователя."""
        if await cls.is_vip(user):
            settings = await cls.get_settings()
            return f"⭐ <b>VIP-статус активен</b>\nСкидка: {settings.discount_percent}%"
        else:
            settings = await cls.get_settings()
            if not settings.enabled:
                return "⭐ VIP-доступ отключён"
            return f"⭐ <b>VIP-доступ</b>\n\nСтоимость: {settings.price} ₽\nСкидка на все товары: {settings.discount_percent}%"
