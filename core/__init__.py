"""Domain layer public API."""

from core.order_engine import (
    AdminConfirmation,
    ConfirmOutcome,
    OrderEngine,
    OrderStatus,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_CONFIRMED,
    STATUS_PAID,
    STATUS_PENDING,
    STATUS_WAITING,
    group_orders_by_status,
    normalize_order_status,
)

__all__ = [
    "AdminConfirmation",
    "ConfirmOutcome",
    "OrderEngine",
    "OrderStatus",
    "STATUS_CANCELLED",
    "STATUS_COMPLETED",
    "STATUS_CONFIRMED",
    "STATUS_PAID",
    "STATUS_PENDING",
    "STATUS_WAITING",
    "group_orders_by_status",
    "normalize_order_status",
]
