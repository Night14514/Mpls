"""
Сервис управления секретным (скрытым) доступом.

Доступ хранится в БД (таблица secret_access), а не только в .env.
Переменная окружения SECURITY_ADMIN_IDS остаётся как "бутстрап"-список
(например, для первого запуска), но основным источником истины
является база данных.
"""

import logging
from typing import List, Optional

from config import get_settings
from database import get_db, transaction

logger = logging.getLogger(__name__)


class SecretAccessService:
    """Управление секретным доступом пользователей."""

    @classmethod
    async def grant(
        cls, telegram_id: int, granted_by: int, note: Optional[str] = None
    ) -> bool:
        """Выдать секретный доступ пользователю."""
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT id, is_active FROM secret_access WHERE telegram_id = ?",
                (telegram_id,),
            )
            row = await cursor.fetchone()
            if row:
                await db.execute(
                    """UPDATE secret_access
                       SET is_active = 1, granted_by = ?, note = ?,
                           created_at = datetime('now'), revoked_by = NULL, revoked_at = NULL
                       WHERE telegram_id = ?""",
                    (granted_by, note, telegram_id),
                )
            else:
                await db.execute(
                    """INSERT INTO secret_access (telegram_id, granted_by, note, is_active)
                       VALUES (?, ?, ?, 1)""",
                    (telegram_id, granted_by, note),
                )
            return True

    @classmethod
    async def revoke(cls, telegram_id: int, revoked_by: int) -> bool:
        """Забрать секретный доступ у пользователя."""
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT id FROM secret_access WHERE telegram_id = ? AND is_active = 1",
                (telegram_id,),
            )
            if not await cursor.fetchone():
                return False
            await db.execute(
                """UPDATE secret_access
                   SET is_active = 0, revoked_by = ?, revoked_at = datetime('now')
                   WHERE telegram_id = ?""",
                (revoked_by, telegram_id),
            )
            return True

    @classmethod
    async def has_access(cls, telegram_id: int) -> bool:
        """Проверить, есть ли у пользователя секретный доступ (БД + .env-бутстрап)."""
        settings = get_settings()
        if telegram_id in settings.security_admin_ids:
            return True

        async with get_db() as db:
            cursor = await db.execute(
                "SELECT 1 FROM secret_access WHERE telegram_id = ? AND is_active = 1",
                (telegram_id,),
            )
            return await cursor.fetchone() is not None

    @classmethod
    async def list_active(cls) -> List[dict]:
        """Список пользователей с активным секретным доступом."""
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT telegram_id, granted_by, note, created_at
                   FROM secret_access WHERE is_active = 1
                   ORDER BY created_at DESC"""
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    @classmethod
    async def log_admin_action(
        cls, admin_telegram_id: int, action: str, target: Optional[str] = None,
        details: Optional[str] = None,
    ) -> None:
        """Записать действие администратора в журнал."""
        try:
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO admin_action_log (admin_telegram_id, action, target, details)
                       VALUES (?, ?, ?, ?)""",
                    (admin_telegram_id, action, target, details),
                )
        except Exception as exc:
            logger.error("Не удалось записать действие администратора: %s", exc)
    @classmethod
    async def get_action_log(cls, limit: int = 20) -> List[dict]:
        """Последние действия администраторов."""
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT admin_telegram_id, action, target, details, created_at
                   FROM admin_action_log
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]