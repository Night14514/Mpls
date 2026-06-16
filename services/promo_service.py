"""
Сервис промокодов.
"""

import logging
import secrets
import string
from typing import List, Optional

from database import get_db
from models import PromoCode

logger = logging.getLogger(__name__)


class PromoService:
    """Создание и активация промокодов."""

    @staticmethod
    def _row_to_promo(row) -> PromoCode:
        return PromoCode(
            id=row["id"],
            code=row["code"],
            amount=row["amount"],
            max_activations=row["max_activations"],
            used_count=row["used_count"] or 0,
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
        )

    @classmethod
    async def create(
        cls,
        code: str,
        amount: float,
        max_activations: int,
    ) -> PromoCode:
        code = code.strip().upper()
        async with get_db() as db:
            await db.execute(
                """INSERT INTO promo_codes (code, amount, max_activations)
                   VALUES (?, ?, ?)""",
                (code, amount, max_activations),
            )
            cursor = await db.execute(
                "SELECT * FROM promo_codes WHERE code = ?", (code,)
            )
            return cls._row_to_promo(await cursor.fetchone())

    @classmethod
    async def get_all_active(cls) -> List[PromoCode]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM promo_codes WHERE is_active = 1 ORDER BY created_at DESC"
            )
            return [cls._row_to_promo(r) for r in await cursor.fetchall()]

    @classmethod
    async def get_all(cls) -> List[PromoCode]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM promo_codes ORDER BY created_at DESC"
            )
            return [cls._row_to_promo(r) for r in await cursor.fetchall()]

    @classmethod
    async def get_by_code(cls, code: str) -> Optional[PromoCode]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM promo_codes WHERE code = ?",
                (code.strip().upper(),),
            )
            row = await cursor.fetchone()
            return cls._row_to_promo(row) if row else None

    @classmethod
    async def delete(cls, promo_id: int) -> bool:
        async with get_db() as db:
            cursor = await db.execute(
                "UPDATE promo_codes SET is_active = 0 WHERE id = ?", (promo_id,)
            )
            return cursor.rowcount > 0

    @classmethod
    async def activate(cls, user_id: int, code: str) -> tuple:
        """
        Активировать промокод.
        Возвращает (success: bool, message: str, amount: float).
        """
        promo = await cls.get_by_code(code)
        if not promo or not promo.is_active:
            return False, "Промокод не найден", 0

        if promo.used_count >= promo.max_activations:
            return False, "Промокод исчерпан", 0

        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id FROM promo_redemptions WHERE promo_id = ? AND user_id = ?",
                (promo.id, user_id),
            )
            if await cursor.fetchone():
                return False, "Вы уже использовали этот промокод", 0

            await db.execute(
                "INSERT INTO promo_redemptions (promo_id, user_id) VALUES (?, ?)",
                (promo.id, user_id),
            )
            await db.execute(
                "UPDATE promo_codes SET used_count = used_count + 1 WHERE id = ?",
                (promo.id,),
            )
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (promo.amount, user_id),
            )

        return True, f"Начислено {promo.amount:g} ₽", promo.amount

    @staticmethod
    def generate_code(length: int = 8) -> str:
        chars = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(chars) for _ in range(length))
