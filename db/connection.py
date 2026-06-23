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
            await _migrate_product_foreign_keys(db)
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
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
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

        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_user_id INTEGER NOT NULL,
            referred_user_id INTEGER NOT NULL UNIQUE,
            source_payload TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            confirmed_at TEXT,
            FOREIGN KEY (referrer_user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (referred_user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS referral_rewards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_user_id INTEGER NOT NULL,
            milestone INTEGER NOT NULL,
            promo_code TEXT NOT NULL,
            amount REAL NOT NULL,
            referral_count_at_grant INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(referrer_user_id, milestone),
            FOREIGN KEY (referrer_user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS referral_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER NOT NULL DEFAULT 1,
            threshold INTEGER NOT NULL DEFAULT 5,
            reward_amount REAL NOT NULL DEFAULT 500,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS vip_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER NOT NULL DEFAULT 1,
            price REAL NOT NULL DEFAULT 1000.0,
            discount_percent INTEGER NOT NULL DEFAULT 10,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS vip_purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            payment_method TEXT,
            payment_id TEXT,
            status TEXT DEFAULT 'completed',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS secret_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            granted_by INTEGER,
            note TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            revoked_by INTEGER,
            revoked_at TEXT
        );

        CREATE TABLE IF NOT EXISTS admin_action_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_telegram_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            target TEXT,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
        CREATE INDEX IF NOT EXISTS idx_payments_provider_id ON payments(provider_payment_id);
        CREATE INDEX IF NOT EXISTS idx_crypto_invoices_invoice_id ON crypto_invoices(invoice_id);
        CREATE INDEX IF NOT EXISTS idx_order_admin_actions_order_id ON order_admin_actions(order_id);
        CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_user_id);
        CREATE INDEX IF NOT EXISTS idx_referrals_status ON referrals(status);
        CREATE INDEX IF NOT EXISTS idx_referral_rewards_referrer ON referral_rewards(referrer_user_id);
        CREATE INDEX IF NOT EXISTS idx_secret_access_telegram_id ON secret_access(telegram_id);
        CREATE INDEX IF NOT EXISTS idx_admin_action_log_admin ON admin_action_log(admin_telegram_id);
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
        "ALTER TABLE users ADD COLUMN referral_code TEXT",
        "ALTER TABLE users ADD COLUMN is_vip INTEGER DEFAULT 0",
        "ALTER TABLE users ADD COLUMN vip_purchased_at TEXT",
        "ALTER TABLE users ADD COLUMN vip_expiry TEXT",
        "ALTER TABLE categories ADD COLUMN sort_order INTEGER DEFAULT 0",
        "ALTER TABLE categories ADD COLUMN sort_order INTEGER DEFAULT 0",
        "ALTER TABLE balance_topups ADD COLUMN crypto_invoice_id TEXT",
            ]

    for sql in migrations:
        await _safe_execute(db, sql)

    await _safe_execute(
        db,
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code "
        "ON users(referral_code) WHERE referral_code IS NOT NULL",
    )
    await _safe_execute(
        db,
        "INSERT OR IGNORE INTO referral_settings (id, enabled, threshold, reward_amount) "
        "VALUES (1, 1, 5, 500)",
    )
    await _safe_execute(
        db,
        "INSERT OR IGNORE INTO vip_settings (id, enabled, price, discount_percent) "
        "VALUES (1, 1, 1000.0, 10)",
    )

    # Initialize sort_order for existing categories based on their ID
    await db.execute(
        """
        UPDATE categories
        SET sort_order = id
        WHERE sort_order = 0 OR sort_order IS NULL
        """
    )

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


_PRODUCT_FK_EXPECTATIONS = {
    "cart": [
        ("product_id", "products", "CASCADE"),
        ("user_id", "users", "CASCADE"),
    ],
    "favorites": [
        ("product_id", "products", "CASCADE"),
        ("user_id", "users", "CASCADE"),
    ],
    "orders": [
        ("product_id", "products", "SET NULL"),
        ("user_id", "users", "CASCADE"),
    ],
    "order_items": [
        ("product_id", "products", "CASCADE"),
        ("order_id", "orders", "CASCADE"),
    ],
    "crypto_invoices": [
        ("user_id", "users", "NO ACTION"),
        ("order_id", "orders", "NO ACTION"),
    ],
    "order_admin_actions": [
        ("order_id", "orders", "NO ACTION"),
        ("admin_user_id", "users", "NO ACTION"),
    ],
}

_PRODUCT_FK_TABLE_DEFINITIONS = {
    "orders": """
        CREATE TABLE {table} (
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
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
        )
    """,
    "order_items": """
        CREATE TABLE {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER DEFAULT 1,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """,
    "cart": """
        CREATE TABLE {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            quantity INTEGER DEFAULT 1,
            UNIQUE(user_id, product_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """,
    "favorites": """
        CREATE TABLE {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            UNIQUE(user_id, product_id),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """,
    "crypto_invoices": """
        CREATE TABLE {table} (
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
        )
    """,
    "order_admin_actions": """
        CREATE TABLE {table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            admin_user_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (admin_user_id) REFERENCES users(id)
        )
    """,
}


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    return await cursor.fetchone() is not None


async def _get_table_columns(db: aiosqlite.Connection, table_name: str) -> list[str]:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    rows = await cursor.fetchall()
    return [row["name"] for row in rows]


async def _get_foreign_key_rules(
    db: aiosqlite.Connection, table_name: str
) -> dict[tuple[str, str], str]:
    cursor = await db.execute(f"PRAGMA foreign_key_list({table_name})")
    rows = await cursor.fetchall()
    return {(row["from"], row["table"]): row["on_delete"].upper() for row in rows}


def _normalize_on_delete(rule: str) -> str:
    normalized = rule.strip().upper()
    if normalized in {"", "NO ACTION", "RESTRICT"}:
        return "NO ACTION"
    return normalized


async def _product_foreign_keys_need_migration(db: aiosqlite.Connection) -> bool:
    for table_name, expected_rules in _PRODUCT_FK_EXPECTATIONS.items():
        if not await _table_exists(db, table_name):
            continue
        actual_rules = await _get_foreign_key_rules(db, table_name)
        for column, ref_table, expected_on_delete in expected_rules:
            actual = _normalize_on_delete(actual_rules.get((column, ref_table), "NO ACTION"))
            expected = _normalize_on_delete(expected_on_delete)
            if actual != expected:
                logger.info(
                    "Product FK migration required for %s.%s -> %s (%s != %s)",
                    table_name,
                    column,
                    ref_table,
                    actual,
                    expected,
                )
                return True
    return False


async def _copy_table_rows(
    db: aiosqlite.Connection,
    source_table: str,
    target_table: str,
    columns: list[str],
) -> None:
    if not columns:
        return
    column_list = ", ".join(columns)
    await db.execute(
        f"INSERT INTO {target_table} ({column_list}) "
        f"SELECT {column_list} FROM {source_table}"
    )


async def _rebuild_product_fk_table(db: aiosqlite.Connection, table_name: str) -> None:
    old_table = f"{table_name}_fk_old"
    old_table_exists = await _table_exists(db, old_table)
    main_table_exists = await _table_exists(db, table_name)

    if old_table_exists and main_table_exists:
        logger.warning(
            "Found orphaned backup table %s from a previous migration; dropping it.",
            old_table,
        )
        await db.execute(f"DROP TABLE {old_table}")
        old_table_exists = False

    if old_table_exists and not main_table_exists:
        logger.warning(
            "Found incomplete migration for %s; restoring backup %s.",
            table_name,
            old_table,
        )
        await db.execute(f"ALTER TABLE {old_table} RENAME TO {table_name}")
        old_table_exists = False

    columns = await _get_table_columns(db, table_name)
    if not columns:
        return

    await db.execute(f"ALTER TABLE {table_name} RENAME TO {old_table}")
    await db.execute(_PRODUCT_FK_TABLE_DEFINITIONS[table_name].format(table=table_name))
    await _copy_table_rows(db, old_table, table_name, columns)
    await db.execute(f"DROP TABLE {old_table}")


async def _migrate_product_foreign_keys(db: aiosqlite.Connection) -> None:
    """Rebuild product-related tables when legacy FK rules differ from code."""
    if not await _product_foreign_keys_need_migration(db):
        return

    logger.info("Running product foreign key migration")
    await db.execute("PRAGMA foreign_keys = OFF")
    try:
        if await _table_exists(db, "orders"):
            await _rebuild_product_fk_table(db, "orders")
            await _safe_execute(db, "CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
            await _safe_execute(db, "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
        if await _table_exists(db, "order_items"):
            await _rebuild_product_fk_table(db, "order_items")
        if await _table_exists(db, "cart"):
            await _rebuild_product_fk_table(db, "cart")
        if await _table_exists(db, "favorites"):
            await _rebuild_product_fk_table(db, "favorites")
        if await _table_exists(db, "crypto_invoices"):
            await _rebuild_product_fk_table(db, "crypto_invoices")
            await _safe_execute(db, "CREATE INDEX IF NOT EXISTS idx_crypto_invoices_invoice_id ON crypto_invoices(invoice_id)")
        if await _table_exists(db, "order_admin_actions"):
            await _rebuild_product_fk_table(db, "order_admin_actions")
            await _safe_execute(db, "CREATE INDEX IF NOT EXISTS idx_order_admin_actions_order_id ON order_admin_actions(order_id)")
    finally:
        await db.execute("PRAGMA foreign_keys = ON")

    logger.info("Product foreign key migration completed")

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
