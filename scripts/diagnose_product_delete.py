"""Диагностика FOREIGN KEY при удалении товара."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "0000000000:TEST_TOKEN_FOR_DIAGNOSTICS")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///data/diagnostic.db")

from db.connection import get_db, init_db  # noqa: E402
from services.product_service import ProductService  # noqa: E402


def inspect_sqlite_schema(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    print("\n=== PRAGMA foreign_keys ===")
    print(conn.execute("PRAGMA foreign_keys").fetchone()[0])

    print("\n=== CREATE TABLE products ===")
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='products'"
    ).fetchone()
    print(row["sql"] if row else "MISSING")

    print("\n=== Tables referencing products (product_id) ===")
    tables = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    for table in tables:
        fk_rows = conn.execute(f"PRAGMA foreign_key_list({table['name']})").fetchall()
        for fk in fk_rows:
            if fk["table"] == "products":
                print(
                    f"  {table['name']}.{fk['from']} -> products.{fk['to']} "
                    f"ON DELETE {fk['on_delete']} ON UPDATE {fk['on_update']}"
                )

    print("\n=== Full FK list for product-related tables ===")
    for name in ("cart", "orders", "order_items", "favorites", "payments"):
        print(f"\n-- {name} --")
        for fk in conn.execute(f"PRAGMA foreign_key_list({name})").fetchall():
            print(dict(fk))
        cols = conn.execute(f"PRAGMA table_info({name})").fetchall()
        for col in cols:
            if col["name"] == "product_id":
                print(f"  product_id: notnull={col['notnull']} dflt={col['dflt_value']}")

    conn.close()


async def seed_and_delete(product_id: int | None = None) -> None:
    async with get_db() as db:
        await db.execute("INSERT INTO users (telegram_id, username) VALUES (1, 'tester')")
        uid = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]
        await db.execute("INSERT INTO categories (name) VALUES ('Cat')")
        cid = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]
        await db.execute(
            "INSERT INTO products (title, description, price, category_id) VALUES ('P', 'D', 10, ?)",
            (cid,),
        )
        pid = product_id or (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]
        await db.execute(
            "INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, 1)",
            (uid, pid),
        )
        await db.execute(
            "INSERT INTO favorites (user_id, product_id) VALUES (?, ?)",
            (uid, pid),
        )
        await db.execute(
            "INSERT INTO orders (user_id, product_id, price, status) VALUES (?, ?, 10, 'PENDING')",
            (uid, pid),
        )
        oid = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]
        await db.execute(
            "INSERT INTO order_items (order_id, product_id, price, quantity) VALUES (?, ?, 10, 1)",
            (oid, pid),
        )

    print(f"\n=== Related rows before delete (product_id={pid}) ===")
    async with get_db() as db:
        for table, col in (
            ("cart", "product_id"),
            ("favorites", "product_id"),
            ("orders", "product_id"),
            ("order_items", "product_id"),
        ):
            cur = await db.execute(f"SELECT * FROM {table} WHERE {col} = ?", (pid,))
            rows = await cur.fetchall()
            print(f"  {table}: {len(rows)} row(s) -> {[dict(r) for r in rows]}")

    print("\n=== Step-by-step delete (same as ProductService) ===")
    try:
        async with get_db() as db:
            steps = [
                ("DELETE FROM order_items WHERE product_id = ?", (pid,)),
                ("DELETE FROM cart WHERE product_id = ?", (pid,)),
                ("DELETE FROM favorites WHERE product_id = ?", (pid,)),
                ("UPDATE orders SET product_id = NULL WHERE product_id = ?", (pid,)),
                ("DELETE FROM products WHERE id = ?", (pid,)),
            ]
            for sql, params in steps:
                print(f"EXEC: {sql} {params}")
                try:
                    cur = await db.execute(sql, params)
                    print(f"  -> rowcount={cur.rowcount}")
                except Exception as exc:
                    print(f"  -> FAILED: {type(exc).__name__}: {exc}")
                    traceback.print_exc()
                    raise
    except Exception:
        print("\nDelete sequence FAILED")
        return

    print("\nDelete sequence OK")


async def main() -> None:
    db_path = ROOT / "data" / "diagnostic.db"
    if db_path.exists():
        db_path.unlink()

    await init_db()
    inspect_sqlite_schema(str(db_path))
    await seed_and_delete()

    # Simulate legacy schema: orders.product_id NOT NULL + FK without ON DELETE SET NULL
    print("\n\n========== LEGACY SCHEMA SIMULATION ==========")
    legacy_path = ROOT / "data" / "legacy_diagnostic.db"
    if legacy_path.exists():
        legacy_path.unlink()

    conn = sqlite3.connect(legacy_path)
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL
        );
        CREATE TABLE products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            price REAL NOT NULL
        );
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        CREATE TABLE order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            price REAL NOT NULL,
            quantity INTEGER DEFAULT 1,
            FOREIGN KEY (order_id) REFERENCES orders(id),
            FOREIGN KEY (product_id) REFERENCES products(id)
        );
        INSERT INTO users (telegram_id) VALUES (1);
        INSERT INTO products (title, price) VALUES ('Legacy', 5);
        INSERT INTO orders (user_id, product_id, price) VALUES (1, 1, 5);
        INSERT INTO order_items (order_id, product_id, price) VALUES (1, 1, 5);
        PRAGMA foreign_keys = ON;
        """
    )
    conn.close()

    inspect_sqlite_schema(str(legacy_path))
    conn = sqlite3.connect(legacy_path)
    conn.execute("PRAGMA foreign_keys = ON")
    pid = 1
    for sql in (
        "DELETE FROM order_items WHERE product_id = ?",
        "UPDATE orders SET product_id = NULL WHERE product_id = ?",
        "DELETE FROM products WHERE id = ?",
    ):
        print(f"\nLEGACY EXEC: {sql}")
        try:
            cur = conn.execute(sql, (pid,))
            conn.commit()
            print(f"  -> rowcount={cur.rowcount}")
        except Exception as exc:
            print(f"  -> FAILED: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            break
    conn.close()


if __name__ == "__main__":
    asyncio.run(main())
