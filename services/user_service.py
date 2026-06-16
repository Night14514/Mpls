"""
Сервис пользователей: регистрация, VIP, админы.
"""

import logging
from typing import List, Optional

from database import get_db, transaction
from models import User, Stats
from utils import format_price

logger = logging.getLogger(__name__)


class UserService:
    """CRUD и бизнес-логика пользователей."""

    @staticmethod
    def _row_to_user(row) -> User:
        keys = row.keys() if hasattr(row, "keys") else []
        return User(
            id=row["id"],
            telegram_id=row["telegram_id"],
            username=row["username"],
            full_name=row["full_name"],
            balance=row["balance"] or 0,
            is_admin=bool(row["is_admin"]),
            is_trusted=bool(row["is_trusted"]),
            created_at=row["created_at"],
            country=row["country"] if "country" in keys else None,
            city=row["city"] if "city" in keys else None,
            is_registered=bool(row["is_registered"]) if "is_registered" in keys else False,
        )

    @classmethod
    async def get_or_create(
        cls,
        telegram_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        force_admin: bool = False,
    ) -> User:
        """Получить или создать пользователя."""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = await cursor.fetchone()
            if row:
                if force_admin and not row["is_admin"]:
                    await db.execute(
                        "UPDATE users SET is_admin = 1 WHERE telegram_id = ?",
                        (telegram_id,),
                    )
                    cursor = await db.execute(
                        "SELECT * FROM users WHERE telegram_id = ?",
                        (telegram_id,),
                    )
                    row = await cursor.fetchone()
                return cls._row_to_user(row)

            is_admin = 1 if force_admin else 0
            await db.execute(
                """INSERT INTO users (telegram_id, username, full_name, is_admin)
                   VALUES (?, ?, ?, ?)""",
                (telegram_id, username, full_name, is_admin),
            )
            cursor = await db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = await cursor.fetchone()
            logger.info("Новый пользователь: %s", telegram_id)
            return cls._row_to_user(row)

    @classmethod
    async def get_by_telegram_id(cls, telegram_id: int) -> Optional[User]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = await cursor.fetchone()
            return cls._row_to_user(row) if row else None

    @classmethod
    async def get_by_id(cls, user_id: int) -> Optional[User]:
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = await cursor.fetchone()
            return cls._row_to_user(row) if row else None

    @classmethod
    async def set_trusted(cls, telegram_id: int, trusted: bool) -> bool:
        """Выдать или снять VIP-доступ."""
        async with get_db() as db:
            cursor = await db.execute(
                "UPDATE users SET is_trusted = ? WHERE telegram_id = ?",
                (1 if trusted else 0, telegram_id),
            )
            return cursor.rowcount > 0

    @classmethod
    async def get_all_admins(cls) -> List[User]:
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM users WHERE is_admin = 1")
            rows = await cursor.fetchall()
            return [cls._row_to_user(r) for r in rows]

    @classmethod
    async def count_users(cls) -> int:
        async with get_db() as db:
            cursor = await db.execute("SELECT COUNT(*) as c FROM users")
            row = await cursor.fetchone()
            return row["c"]

    @classmethod
    async def count_new_today(cls) -> int:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) as c FROM users WHERE date(created_at) = date('now')"
            )
            row = await cursor.fetchone()
            return row["c"]

    @classmethod
    async def search_by_username_or_id(cls, query: str) -> List[User]:
        async with get_db() as db:
            if query.isdigit():
                cursor = await db.execute(
                    "SELECT * FROM users WHERE telegram_id = ? OR id = ?",
                    (int(query), int(query)),
                )
            else:
                q = f"%{query.lstrip('@')}%"
                cursor = await db.execute(
                    "SELECT * FROM users WHERE username LIKE ?",
                    (q,),
                )
            rows = await cursor.fetchall()
            return [cls._row_to_user(r) for r in rows]

    @classmethod
    async def complete_registration(
        cls, telegram_id: int, country: str, city: str
    ) -> Optional[User]:
        """Завершить регистрацию пользователя."""
        async with get_db() as db:
            await db.execute(
                """UPDATE users SET country = ?, city = ?, is_registered = 1
                   WHERE telegram_id = ?""",
                (country, city, telegram_id),
            )
        return await cls.get_by_telegram_id(telegram_id)

    @classmethod
    async def adjust_balance(cls, user_id: int, delta: float) -> Optional[float]:
        """Изменить баланс (положительное — начисление, отрицательное — списание)."""
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
            row = await cursor.fetchone()
            if not row:
                return None

            cursor = await db.execute(
                """UPDATE users
                   SET balance = balance + ?
                   WHERE id = ? AND balance + ? >= 0""",
                (delta, user_id, delta),
            )
            if cursor.rowcount != 1:
                return None
            cursor = await db.execute("SELECT balance FROM users WHERE id = ?", (user_id,))
            updated = await cursor.fetchone()
            return updated["balance"] if updated else None

    @classmethod
    async def set_balance(cls, user_id: int, amount: float) -> bool:
        """Установить баланс напрямую."""
        if amount < 0:
            return False
        async with get_db() as db:
            cursor = await db.execute(
                "UPDATE users SET balance = ? WHERE id = ?",
                (amount, user_id),
            )
            return cursor.rowcount > 0

    @classmethod
    async def get_user_info_text(cls, telegram_id: int) -> Optional[str]:
        """Текстовая информация о пользователе для админки."""
        user = await cls.get_by_telegram_id(telegram_id)
        if not user:
            return None
        username = f"@{user.username}" if user.username else "—"
        return (
            f"👤 <b>Пользователь</b>\n\n"
            f"🆔 Telegram ID: <code>{user.telegram_id}</code>\n"
            f"🔗 Username: {username}\n"
            f"📛 Имя: {user.full_name or '—'}\n"
            f"💰 Баланс: {format_price(user.balance)}\n"
            f"🌍 Страна: {user.country or '—'}\n"
            f"🏙 Город: {user.city or '—'}\n"
            f"📅 Регистрация: {user.created_at}"
        )
