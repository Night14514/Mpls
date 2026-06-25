"""
Сервис VIP-доступа (подписки).
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from config import get_settings
from database import get_db, transaction
from models import VIPPlan, VIPSettings, User

logger = logging.getLogger(__name__)

VIP_PLANS: Dict[str, VIPPlan] = {
    "1d": VIPPlan(key="1d", label="1 день", price=60, days=1),
    "1w": VIPPlan(key="1w", label="1 неделя", price=300, days=7),
    "1m": VIPPlan(key="1m", label="1 месяц", price=600, days=30),
    "3m": VIPPlan(key="3m", label="3 месяца", price=1100, days=90),
    "1y": VIPPlan(key="1y", label="1 год", price=3700, days=365),
}


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
    def get_plan(cls, plan_key: str) -> Optional[VIPPlan]:
        return VIP_PLANS.get(plan_key)

    @classmethod
    def get_plans(cls) -> List[VIPPlan]:
        return list(VIP_PLANS.values())

    @classmethod
    async def get_settings(cls) -> VIPSettings:
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM vip_settings WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return cls._row_to_vip_settings(row)
            settings = get_settings()
            return VIPSettings(
                enabled=settings.VIP_ENABLED,
                price=settings.VIP_PRICE,
                discount_percent=settings.VIP_DISCOUNT_PERCENT,
                updated_at="",
            )

    @classmethod
    async def update_settings(
        cls, enabled: bool, price: float, discount_percent: int
    ) -> VIPSettings:
        async with get_db() as db:
            await db.execute(
                """UPDATE vip_settings
                   SET enabled = ?, price = ?, discount_percent = ?, updated_at = datetime('now')
                   WHERE id = 1""",
                (1 if enabled else 0, price, discount_percent),
            )
        return await cls.get_settings()

    @classmethod
    async def expire_if_needed(cls, user: User) -> User:
        """Снять просроченный VIP и вернуть актуального пользователя."""
        if not user.is_vip:
            return user
        if not user.vip_expiry:
            return user
        try:
            expiry = datetime.fromisoformat(user.vip_expiry)
        except (ValueError, TypeError):
            logger.warning("Invalid vip_expiry format for user %s", user.id)
            return user
        if datetime.now() > expiry:
            await cls.remove_vip(user.id)
            from services.user_service import UserService

            refreshed = await UserService.get_by_id(user.id)
            return refreshed or user
        return user

    @classmethod
    async def is_vip(cls, user: User) -> bool:
        user = await cls.expire_if_needed(user)
        return bool(user.is_vip)

    @classmethod
    async def cleanup_expired_vips(cls) -> int:
        """Фоновая очистка просроченных VIP."""
        async with get_db() as db:
            cursor = await db.execute(
                """
                UPDATE users
                SET is_vip = 0, vip_purchased_at = NULL, vip_expiry = NULL, vip_plan = NULL
                WHERE is_vip = 1
                  AND vip_expiry IS NOT NULL
                  AND vip_expiry != ''
                  AND datetime(vip_expiry) <= datetime('now')
                """
            )
            return cursor.rowcount

    @classmethod
    async def get_vip_users(cls) -> List[User]:
        from services.user_service import UserService

        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM users WHERE is_vip = 1")
            rows = await cursor.fetchall()
        users = [UserService._row_to_user(r) for r in rows]
        active = []
        for user in users:
            refreshed = await cls.expire_if_needed(user)
            if refreshed.is_vip:
                active.append(refreshed)
        return active

    @classmethod
    def _calculate_expiry(
        cls, current_expiry: Optional[str], plan_days: int
    ) -> str:
        now = datetime.now()
        base = now
        if current_expiry:
            try:
                existing = datetime.fromisoformat(current_expiry)
                if existing > now:
                    base = existing
            except (ValueError, TypeError):
                pass
        return (base + timedelta(days=plan_days)).isoformat(timespec="seconds")

    @classmethod
    async def grant_vip(
        cls,
        user_id: int,
        amount: float = 0,
        payment_method: str = "manual",
        payment_id: Optional[str] = None,
        plan_key: str = "1m",
        days: Optional[int] = None,
    ) -> bool:
        plan = cls.get_plan(plan_key)
        plan_days = days if days is not None else (plan.days if plan else 30)
        plan_label = plan.key if plan else plan_key

        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT vip_expiry FROM users WHERE id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return False

            expiry = cls._calculate_expiry(row["vip_expiry"], plan_days)

            if amount > 0:
                await db.execute(
                    """INSERT INTO vip_purchases (user_id, amount, payment_method, payment_id, status)
                       VALUES (?, ?, ?, ?, 'completed')""",
                    (user_id, amount, payment_method, payment_id),
                )

            await db.execute(
                """UPDATE users
                   SET is_vip = 1,
                       vip_purchased_at = datetime('now'),
                       vip_expiry = ?,
                       vip_plan = ?
                   WHERE id = ?""",
                (expiry, plan_label, user_id),
            )
            return True

    @classmethod
    async def remove_vip(cls, user_id: int) -> bool:
        async with get_db() as db:
            await db.execute(
                """UPDATE users
                   SET is_vip = 0, vip_purchased_at = NULL, vip_expiry = NULL, vip_plan = NULL
                   WHERE id = ?""",
                (user_id,),
            )
            return True

    @classmethod
    async def calculate_discounted_price(cls, price: float, user: User) -> float:
        if not await cls.is_vip(user):
            return price
        settings = await cls.get_settings()
        if not settings.enabled:
            return price
        discount = price * (settings.discount_percent / 100)
        return round(price - discount, 2)

    @classmethod
    def _format_expiry(cls, vip_expiry: Optional[str]) -> str:
        if not vip_expiry:
            return "—"
        try:
            expiry = datetime.fromisoformat(vip_expiry)
            return expiry.strftime("%d.%m.%Y %H:%M")
        except (ValueError, TypeError):
            return vip_expiry

    @classmethod
    async def get_vip_status_text(cls, user: User) -> str:
        user = await cls.expire_if_needed(user)
        settings = await cls.get_settings()
        if user.is_vip:
            plan = cls.get_plan(user.vip_plan or "")
            plan_line = f"\nТариф: {plan.label}" if plan else ""
            return (
                f"⭐ <b>VIP-статус активен</b>{plan_line}\n"
                f"Действует до: {cls._format_expiry(user.vip_expiry)}\n"
                f"Скидка: {settings.discount_percent}%"
            )
        if not settings.enabled:
            return "⭐ VIP-доступ отключён"
        lines = ["⭐ <b>VIP-подписка</b>\n", "Выберите тариф:"]
        for plan in cls.get_plans():
            lines.append(f"• {plan.label} — {plan.price:g} ₽")
        lines.append(f"\nСкидка на все товары: {settings.discount_percent}%")
        return "\n".join(lines)

    @classmethod
    def plan_price(cls, plan_key: str) -> float:
        plan = cls.get_plan(plan_key)
        return plan.price if plan else 0.0
