"""
Сервис пополнения баланса.
"""

import logging
from typing import List, Optional

from database import get_db, transaction
from models import BalanceTopup

logger = logging.getLogger(__name__)


class BalanceService:
    """Заявки на пополнение баланса."""

    @staticmethod
    def _row_to_topup(row) -> BalanceTopup:
        return BalanceTopup(
            id=row["id"],
            user_id=row["user_id"],
            amount=row["amount"],
            status=row["status"],
            receipt_file_id=row["receipt_file_id"],
            receipt_type=row["receipt_type"],
            created_at=row["created_at"],
        )

    @classmethod
    async def create_topup(
        cls,
        user_id: int,
        amount: float,
        receipt_file_id: str,
        receipt_type: str,
    ) -> BalanceTopup:
        async with get_db() as db:
            await db.execute(
                """INSERT INTO balance_topups
                   (user_id, amount, receipt_file_id, receipt_type, status)
                   VALUES (?, ?, ?, ?, 'pending')""",
                (user_id, amount, receipt_file_id, receipt_type),
            )
            cursor = await db.execute("SELECT last_insert_rowid() as id")
            tid = (await cursor.fetchone())["id"]
            cursor = await db.execute(
                "SELECT * FROM balance_topups WHERE id = ?", (tid,)
            )
            return cls._row_to_topup(await cursor.fetchone())

    @classmethod
    async def get_pending(cls) -> List[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT t.*, u.telegram_id, u.username, u.full_name
                   FROM balance_topups t
                   JOIN users u ON t.user_id = u.id
                   WHERE t.status = 'pending'
                   ORDER BY t.created_at DESC"""
            )
            return [dict(r) for r in await cursor.fetchall()]

    @classmethod
    async def get_by_id(cls, topup_id: int) -> Optional[BalanceTopup]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM balance_topups WHERE id = ?", (topup_id,)
            )
            row = await cursor.fetchone()
            return cls._row_to_topup(row) if row else None

    @classmethod
    async def approve(cls, topup_id: int) -> Optional[dict]:
        """Подтвердить пополнение и начислить баланс."""
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT * FROM balance_topups WHERE id = ? AND status = 'pending'",
                (topup_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None

            cursor = await db.execute(
                "UPDATE balance_topups SET status = 'approved' WHERE id = ?",
                (topup_id,),
            )
            if cursor.rowcount != 1:
                return None
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?",
                (row["amount"], row["user_id"]),
            )
            cursor = await db.execute(
                "SELECT telegram_id FROM users WHERE id = ?", (row["user_id"],)
            )
            user_row = await cursor.fetchone()
            
            # Check if this is a VIP purchase
            is_vip_purchase = row["receipt_type"] and row["receipt_type"].startswith("vip_")
            if is_vip_purchase:
                from services.vip_service import VIPService
                await VIPService.grant_vip(row["user_id"], row["amount"], "manual", f"topup_{topup_id}")
            
            return {
                "telegram_id": user_row["telegram_id"],
                "amount": row["amount"],
                "user_id": row["user_id"],
                "is_vip_purchase": is_vip_purchase,
            }

    @classmethod
    async def reject(cls, topup_id: int) -> Optional[int]:
        """Отклонить пополнение. Возвращает telegram_id пользователя."""
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                """SELECT t.user_id, u.telegram_id FROM balance_topups t
                   JOIN users u ON t.user_id = u.id
                   WHERE t.id = ? AND t.status = 'pending'""",
                (topup_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            cursor = await db.execute(
                "UPDATE balance_topups SET status = 'rejected' WHERE id = ?",
                (topup_id,),
            )
            if cursor.rowcount != 1:
                return None
            return row["telegram_id"]
