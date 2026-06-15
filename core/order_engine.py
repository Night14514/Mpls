"""Order domain logic.

This module is intentionally free of Telegram objects. In production it is one
of the protected modules compiled by Cython or Nuitka.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional

from db import get_db, transaction
from models import Order

logger = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


STATUS_PENDING = OrderStatus.PENDING.value
STATUS_CONFIRMED = OrderStatus.CONFIRMED.value
STATUS_COMPLETED = OrderStatus.COMPLETED.value
STATUS_CANCELLED = OrderStatus.CANCELLED.value

# Backward-compatible names used by the existing bot flow.
STATUS_WAITING = STATUS_PENDING
STATUS_PAID = STATUS_CONFIRMED

_STATUS_ALIASES = {
    "pending": STATUS_PENDING,
    "waiting_payment": STATUS_PENDING,
    "wait_payment": STATUS_PENDING,
    "paid": STATUS_CONFIRMED,
    "confirmed": STATUS_CONFIRMED,
    "completed": STATUS_COMPLETED,
    "done": STATUS_COMPLETED,
    "cancelled": STATUS_CANCELLED,
    "canceled": STATUS_CANCELLED,
}


class ConfirmOutcome(str, Enum):
    CONFIRMED = "confirmed"
    ALREADY_CONFIRMED = "already_confirmed"
    NOT_FOUND = "not_found"
    INVALID_STATE = "invalid_state"


@dataclass(frozen=True)
class AdminConfirmation:
    outcome: ConfirmOutcome
    order: Optional[Order] = None


def normalize_order_status(status: Optional[str]) -> str:
    """Normalize old lowercase statuses into the production status model."""
    if not status:
        return STATUS_PENDING
    raw = str(status).strip()
    if raw.upper() in OrderStatus._value2member_map_:
        return raw.upper()
    return _STATUS_ALIASES.get(raw.lower(), raw)


def group_orders_by_status(orders: Iterable[Order]) -> Dict[str, List[Order]]:
    grouped = {
        STATUS_PENDING: [],
        STATUS_CONFIRMED: [],
        STATUS_COMPLETED: [],
        STATUS_CANCELLED: [],
    }
    for order in orders:
        grouped.setdefault(normalize_order_status(order.status), []).append(order)
    return grouped


class OrderEngine:
    """Business logic for order lifecycle and order-related storage."""

    @staticmethod
    def _row_to_order(row) -> Order:
        keys = row.keys() if hasattr(row, "keys") else []
        return Order(
            id=row["id"],
            user_id=row["user_id"],
            product_id=row["product_id"],
            price=row["price"],
            payment_method=row["payment_method"],
            payment_id=row["payment_id"],
            status=normalize_order_status(row["status"]),
            created_at=row["created_at"],
            product_title=row["product_title"] if "product_title" in keys else None,
            confirmed_by=row["confirmed_by"] if "confirmed_by" in keys else None,
            confirmed_at=row["confirmed_at"] if "confirmed_at" in keys else None,
        )

    @classmethod
    async def create_order(
        cls,
        user_id: int,
        product_id: Optional[int],
        price: float,
        payment_method: str,
        status: str = STATUS_PENDING,
    ) -> Optional[Order]:
        async with get_db() as db:
            await db.execute(
                """INSERT INTO orders (user_id, product_id, price, payment_method, status)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, product_id, price, payment_method, normalize_order_status(status)),
            )
            cursor = await db.execute("SELECT last_insert_rowid() as id")
            oid = (await cursor.fetchone())["id"]
        return await cls.get_order(oid)

    @classmethod
    async def create_cart_order_from_items(
        cls,
        user_id: int,
        payment_method: str,
        items: List[dict],
        total: float,
    ) -> Optional[Order]:
        if not items:
            return None

        async with transaction("IMMEDIATE") as db:
            await db.execute(
                """INSERT INTO orders (user_id, product_id, price, payment_method, status)
                   VALUES (?, NULL, ?, ?, ?)""",
                (user_id, total, payment_method, STATUS_PENDING),
            )
            cursor = await db.execute("SELECT last_insert_rowid() as id")
            oid = (await cursor.fetchone())["id"]
            for item in items:
                await db.execute(
                    """INSERT INTO order_items (order_id, product_id, price, quantity)
                       VALUES (?, ?, ?, ?)""",
                    (oid, item["product_id"], item["price"], item["quantity"]),
                )
        return await cls.get_order(oid)

    @classmethod
    async def get_order(cls, order_id: int) -> Optional[Order]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT o.*, p.title as product_title
                   FROM orders o
                   LEFT JOIN products p ON o.product_id = p.id
                   WHERE o.id = ?""",
                (order_id,),
            )
            row = await cursor.fetchone()
            return cls._row_to_order(row) if row else None

    @classmethod
    async def get_user_orders(cls, user_id: int, limit: int = 50) -> List[Order]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT o.*, p.title as product_title
                   FROM orders o
                   LEFT JOIN products p ON o.product_id = p.id
                   WHERE o.user_id = ?
                   ORDER BY o.created_at DESC
                   LIMIT ?""",
                (user_id, limit),
            )
            rows = await cursor.fetchall()
            return [cls._row_to_order(r) for r in rows]

    @classmethod
    async def get_order_items(cls, order_id: int) -> List[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT oi.*, p.title, p.content_data
                   FROM order_items oi
                   JOIN products p ON oi.product_id = p.id
                   WHERE oi.order_id = ?""",
                (order_id,),
            )
            return [dict(r) for r in await cursor.fetchall()]

    @classmethod
    async def update_status(
        cls,
        order_id: int,
        status: str,
        payment_id: Optional[str] = None,
    ) -> Optional[Order]:
        status = normalize_order_status(status)
        async with get_db() as db:
            if payment_id:
                await db.execute(
                    "UPDATE orders SET status = ?, payment_id = ? WHERE id = ?",
                    (status, payment_id, order_id),
                )
            else:
                await db.execute(
                    "UPDATE orders SET status = ? WHERE id = ?",
                    (status, order_id),
                )
        return await cls.get_order(order_id)

    @classmethod
    async def is_payment_processed(cls, provider: str, provider_payment_id: str) -> bool:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT id FROM payments
                   WHERE provider = ? AND provider_payment_id = ? AND status = 'paid'""",
                (provider, provider_payment_id),
            )
            return await cursor.fetchone() is not None

    @classmethod
    async def create_payment(
        cls,
        user_id: int,
        order_id: int,
        provider: str,
        provider_payment_id: str,
        amount: float,
        currency: str,
        status: str = "paid",
    ) -> int:
        async with get_db() as db:
            await db.execute(
                """INSERT INTO payments
                   (user_id, order_id, provider, provider_payment_id, amount, currency, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, order_id, provider, provider_payment_id, amount, currency, status),
            )
            cursor = await db.execute("SELECT last_insert_rowid() as id")
            return (await cursor.fetchone())["id"]

    @classmethod
    async def complete_order(
        cls,
        order_id: int,
        provider: str,
        provider_payment_id: str,
        amount: float,
        currency: str,
    ) -> bool:
        """Atomically register payment and mark the order confirmed."""
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                """SELECT o.*, p.title as product_title
                   FROM orders o
                   LEFT JOIN products p ON o.product_id = p.id
                   WHERE o.id = ?""",
                (order_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return False

            status = normalize_order_status(row["status"])
            if status in {STATUS_COMPLETED, STATUS_CANCELLED}:
                logger.warning("Order %s is already terminal: %s", order_id, status)
                return False

            cursor = await db.execute(
                """SELECT id FROM payments
                   WHERE provider = ? AND provider_payment_id = ? AND status = 'paid'""",
                (provider, provider_payment_id),
            )
            if await cursor.fetchone():
                logger.warning("Duplicate payment: %s %s", provider, provider_payment_id)
                return False

            try:
                await db.execute(
                    """INSERT INTO payments
                       (user_id, order_id, provider, provider_payment_id, amount, currency, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'paid')""",
                    (
                        row["user_id"],
                        order_id,
                        provider,
                        provider_payment_id,
                        amount,
                        currency,
                    ),
                )
            except sqlite3.IntegrityError:
                logger.warning("Payment unique constraint hit: %s %s", provider, provider_payment_id)
                return False

            await db.execute(
                """UPDATE orders
                   SET status = ?, payment_id = ?, confirmed_at = COALESCE(confirmed_at, datetime('now'))
                   WHERE id = ?""",
                (STATUS_CONFIRMED, provider_payment_id, order_id),
            )
            return True

    @classmethod
    async def confirm_order_by_admin(cls, order_id: int, admin_user_id: int) -> AdminConfirmation:
        """Confirm a pending order with a write lock.

        First admin wins and moves the order to CONFIRMED. Later attempts are
        deterministic and return ALREADY_CONFIRMED instead of racing.
        """
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                """SELECT o.*, p.title as product_title
                   FROM orders o
                   LEFT JOIN products p ON o.product_id = p.id
                   WHERE o.id = ?""",
                (order_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return AdminConfirmation(ConfirmOutcome.NOT_FOUND)

            current = normalize_order_status(row["status"])
            order = cls._row_to_order(row)
            if current in {STATUS_CONFIRMED, STATUS_COMPLETED}:
                await db.execute(
                    """INSERT INTO order_admin_actions (order_id, admin_user_id, action)
                       VALUES (?, ?, ?)""",
                    (order_id, admin_user_id, "duplicate_confirm"),
                )
                return AdminConfirmation(ConfirmOutcome.ALREADY_CONFIRMED, order)

            if current != STATUS_PENDING:
                return AdminConfirmation(ConfirmOutcome.INVALID_STATE, order)

            cursor = await db.execute(
                """UPDATE orders
                   SET status = ?, confirmed_by = ?, confirmed_at = datetime('now')
                   WHERE id = ? AND status = ?""",
                (STATUS_CONFIRMED, admin_user_id, order_id, STATUS_PENDING),
            )
            if cursor.rowcount != 1:
                updated = await cls.get_order(order_id)
                return AdminConfirmation(ConfirmOutcome.ALREADY_CONFIRMED, updated)

            await db.execute(
                """INSERT INTO order_admin_actions (order_id, admin_user_id, action)
                   VALUES (?, ?, ?)""",
                (order_id, admin_user_id, "confirm"),
            )
            cursor = await db.execute(
                """SELECT o.*, p.title as product_title
                   FROM orders o
                   LEFT JOIN products p ON o.product_id = p.id
                   WHERE o.id = ?""",
                (order_id,),
            )
            return AdminConfirmation(ConfirmOutcome.CONFIRMED, cls._row_to_order(await cursor.fetchone()))

    @classmethod
    async def count_orders(cls, status: Optional[str] = None) -> int:
        async with get_db() as db:
            if status:
                cursor = await db.execute(
                    "SELECT COUNT(*) as c FROM orders WHERE status = ?",
                    (normalize_order_status(status),),
                )
            else:
                cursor = await db.execute("SELECT COUNT(*) as c FROM orders")
            return (await cursor.fetchone())["c"]

    @classmethod
    async def revenue_by_provider(cls, provider: str) -> float:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT COALESCE(SUM(amount), 0) as total
                   FROM payments WHERE provider = ? AND status = 'paid'""",
                (provider,),
            )
            row = await cursor.fetchone()
            return row["total"] or 0

    @classmethod
    async def get_recent_payments(cls, limit: int = 20) -> List[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT p.*, u.username, u.telegram_id
                   FROM payments p
                   JOIN users u ON p.user_id = u.id
                   ORDER BY p.created_at DESC LIMIT ?""",
                (limit,),
            )
            return [dict(r) for r in await cursor.fetchall()]

    @classmethod
    async def save_crypto_invoice(
        cls,
        user_id: int,
        order_id: int,
        invoice_id: str,
        amount: float,
        asset: str,
    ) -> None:
        async with get_db() as db:
            await db.execute(
                """INSERT OR REPLACE INTO crypto_invoices
                   (user_id, order_id, invoice_id, amount, asset, status)
                   VALUES (?, ?, ?, ?, ?, 'active')""",
                (user_id, order_id, invoice_id, amount, asset),
            )

    @classmethod
    async def get_pending_crypto_invoices(cls) -> List[dict]:
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM crypto_invoices WHERE status = 'active'")
            return [dict(r) for r in await cursor.fetchall()]

    @classmethod
    async def mark_crypto_invoice_paid(cls, invoice_id: str) -> None:
        async with get_db() as db:
            await db.execute(
                "UPDATE crypto_invoices SET status = 'paid' WHERE invoice_id = ?",
                (invoice_id,),
            )

    @classmethod
    async def get_wallets(cls, active_only: bool = True) -> List[dict]:
        async with get_db() as db:
            if active_only:
                cursor = await db.execute("SELECT * FROM wallets WHERE is_active = 1")
            else:
                cursor = await db.execute("SELECT * FROM wallets")
            return [dict(r) for r in await cursor.fetchall()]

    @classmethod
    async def add_wallet(cls, network: str, address: str) -> int:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO wallets (network, address) VALUES (?, ?)",
                (network, address),
            )
            cursor = await db.execute("SELECT last_insert_rowid() as id")
            return (await cursor.fetchone())["id"]

    @classmethod
    async def update_wallet(cls, wallet_id: int, address: str) -> bool:
        async with get_db() as db:
            cursor = await db.execute(
                "UPDATE wallets SET address = ? WHERE id = ?",
                (address, wallet_id),
            )
            return cursor.rowcount > 0

    @classmethod
    async def delete_wallet(cls, wallet_id: int) -> bool:
        async with get_db() as db:
            cursor = await db.execute("DELETE FROM wallets WHERE id = ?", (wallet_id,))
            return cursor.rowcount > 0

    @classmethod
    async def get_wallet(cls, wallet_id: int) -> Optional[dict]:
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM wallets WHERE id = ?", (wallet_id,))
            row = await cursor.fetchone()
            return dict(row) if row else None
