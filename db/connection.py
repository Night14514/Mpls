"""Database connection and transaction helpers.

The current production target is one VPS, so SQLite is fully supported and uses
WAL plus explicit write transactions. PostgreSQL is kept behind this layer so
domain code does not depend on a Telegram handler or a concrete database file.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional

import aiosqlite

from config import get_settings

logger = logging.getLogger(__name__)

_db_path: Optional[str] = None
_sqlite_url_prefixes = ("sqlite+aiosqlite:///", "sqlite:///")


def _is_sqlite_url(url: str) -> bool:
    return url.startswith(_sqlite_url_prefixes) or "://" not in url


def _is_postgres_url(url: str) -> bool:
    return url.startswith(("postgresql://", "postgresql+asyncpg://"))


def _resolve_sqlite_path(url: str) -> str:
    for prefix in _sqlite_url_prefixes:
        if url.startswith(prefix):
            return url[len(prefix) :]
    return url


async def _connect_sqlite() -> aiosqlite.Connection:
    global _db_path
    if _db_path is None:
        settings = get_settings()
        _db_path = _resolve_sqlite_path(settings.DATABASE_URL)

    db = await aiosqlite.connect(_db_path, isolation_level=None)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    await db.execute("PRAGMA busy_timeout = 5000")
    return db


async def init_db() -> None:
    """Initialize the configured database and run lightweight migrations."""
    global _db_path
    settings = get_settings()
    url = settings.DATABASE_URL

    if _is_sqlite_url(url):
        _db_path = _resolve_sqlite_path(url)
        Path(_db_path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(_db_path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA journal_mode = WAL")
            await db.execute("PRAGMA busy_timeout = 5000")
            await _create_tables(db)
            await _migrate_columns(db)
            await db.commit()
        logger.info("SQLite database initialized: %s", _db_path)
        return

    if _is_postgres_url(url):
        raise NotImplementedError(
            "PostgreSQL is isolated behind db.connection. Add asyncpg migrations "
            "and repository implementations here before switching DATABASE_URL."
        )

    raise ValueError(f"Unsupported DATABASE_URL: {url!r}")


async def _create_tables(db: aiosqlite.Connection) -> None:
    await db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            full_name TEXT,
            balance REAL DEFAULT 0,
            is_admin INTEGER DEFAULT 0,
            is_trusted INTEGER DEFAULT 0,
            country TEXT,
            city TEXT,
            is_registered INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            is_hidden INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            price_usd REAL,
            price_rub REAL,
            photo TEXT,
            category_id INTEGER,
            is_hidden INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            content_data TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (category_id) REFERENCES categories(id)
        );

        CREATE TABLE IF NOT EXISTS cart (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            UNIQUE(user_id, product_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER,
            price REAL NOT NULL,
            payment_method TEXT,
            payment_id TEXT,
            status TEXT DEFAULT 'PENDING',
            confirmed_by INTEGER,
            confirmed_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER DEFAULT 1,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            order_id INTEGER,
            provider TEXT NOT NULL,
            provider_payment_id TEXT,
            amount REAL NOT NULL,
            currency TEXT,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        );

        CREATE TABLE IF NOT EXISTS wallets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            network TEXT NOT NULL,
            address TEXT NOT NULL,
            is_active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS crypto_invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            order_id INTEGER,
            invoice_id TEXT UNIQUE NOT NULL,
            amount REAL NOT NULL,
            asset TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (order_id) REFERENCES orders(id)
        );

        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            UNIQUE(user_id, product_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE NOT NULL,
            amount REAL NOT NULL,
            max_activations INTEGER NOT NULL,
            used_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS promo_redemptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            promo_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(promo_id, user_id),
            FOREIGN KEY (promo_id) REFERENCES promo_codes(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS balance_topups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            receipt_file_id TEXT,
            receipt_type TEXT,
            admin_message_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS order_admin_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            admin_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (admin_user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_payments_provider_id ON payments(provider_payment_id);
        CREATE INDEX IF NOT EXISTS idx_crypto_invoices_invoice_id ON crypto_invoices(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_order_admin_actions_order_id ON order_admin_actions(order_id);
        """
    )
    await _migrate_columns(db)
    await _safe_execute(
        db,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_payments_provider_unique
        ON payments(provider, provider_payment_id)
        WHERE provider_payment_id IS NOT NULL
        """,
    )


async def _migrate_columns(db: aiosqlite.Connection) -> None:
    migrations = [
        "ALTER TABLE users ADD COLUMN country TEXT",
        "ALTER TABLE users ADD COLUMN city TEXT",
        "ALTER TABLE users ADD COLUMN is_registered INTEGER DEFAULT 0",
        "ALTER TABLE orders ADD COLUMN confirmed_by INTEGER",
        "ALTER TABLE orders ADD COLUMN confirmed_at TEXT",
        "ALTER TABLE balance_topups ADD COLUMN admin_message_id INTEGER",
        "ALTER TABLE products ADD COLUMN price_usd REAL",
        "ALTER TABLE products ADD COLUMN price_rub REAL",
    ]
    for sql in migrations:
        await _safe_execute(db, sql)

    await db.execute(
        """
        UPDATE orders
        SET status = CASE lower(status)
            WHEN 'pending' THEN 'PENDING'
            WHEN 'waiting_payment' THEN 'PENDING'
            WHEN 'paid' THEN 'CONFIRMED'
            WHEN 'confirmed' THEN 'CONFIRMED'
            WHEN 'completed' THEN 'COMPLETED'
            WHEN 'cancelled' THEN 'CANCELLED'
            ELSE status
        END
        """
    )


async def _safe_execute(db: aiosqlite.Connection, sql: str) -> None:
    try:
        await db.execute(sql)
    except Exception as exc:
        logger.debug("Ignored migration statement %r: %s", sql, exc)


@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Open a short-lived autocommit-style SQLite connection."""
    db = await _connect_sqlite()
    try:
        await db.execute("BEGIN")
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()


@asynccontextmanager
async def transaction(mode: str = "IMMEDIATE") -> AsyncGenerator[aiosqlite.Connection, None]:
    """Open an explicit transaction.

    SQLite's ``BEGIN IMMEDIATE`` acquires the write lock up front. For the order
    confirmation path this is the stable single-VPS equivalent of
    ``SELECT ... FOR UPDATE``.
    """
    db = await _connect_sqlite()
    try:
        mode_sql = mode.strip().upper()
        if mode_sql not in {"DEFERRED", "IMMEDIATE", "EXCLUSIVE"}:
            raise ValueError(f"Unsupported SQLite transaction mode: {mode!r}")
        await db.execute(f"BEGIN {mode_sql}")
        yield db
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    finally:
        await db.close()
