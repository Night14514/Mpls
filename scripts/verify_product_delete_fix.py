"""Verify product FK migration and delete flow on database.db."""
from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO)

os.environ.setdefault("BOT_TOKEN", "0000000000:TEST")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///data/database.db"

DB_PATH = ROOT / "data" / "database.db"


def print_fk_rules() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    print("\n=== FK rules after init_db ===")
    for table in ("cart", "orders", "order_items", "favorites"):
        print(f"\n{table}:")
        for fk in conn.execute(f"PRAGMA foreign_key_list({table})"):
            print(
                f"  {fk['from']} -> {fk['table']}.{fk['to']} "
                f"ON DELETE {fk['on_delete']}"
            )
    conn.close()


async def main() -> None:
    from db.connection import init_db
    from services.product_service import ProductService

    await init_db()
    print_fk_rules()

    async with __import__("db.connection", fromlist=["get_db"]).get_db() as db:
        await db.execute(
            "INSERT INTO products (title, description, price) VALUES ('VerifyDelete', 'test', 50)"
        )
        pid = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]
        await db.execute(
            "INSERT INTO orders (user_id, product_id, price, payment_method, status) "
            "VALUES (1, NULL, 50, 'balance', 'COMPLETED')"
        )
        oid = (await (await db.execute("SELECT last_insert_rowid()")).fetchone())[0]
        await db.execute(
            "INSERT INTO order_items (order_id, product_id, price, quantity) VALUES (?, ?, 50, 1)",
            (oid, pid),
        )
        await db.execute(
            "INSERT INTO cart (user_id, product_id, quantity) VALUES (1, ?, 1)", (pid,)
        )
        await db.execute(
            "INSERT INTO favorites (user_id, product_id) VALUES (1, ?)", (pid,)
        )

    ok = await ProductService.delete_product(pid)
    print(f"\nProductService.delete_product({pid}) => {ok}")
    if not ok:
        raise SystemExit(1)

    conn = sqlite3.connect(DB_PATH)
    remaining = conn.execute("SELECT COUNT(*) FROM products WHERE id = ?", (pid,)).fetchone()[0]
    conn.close()
    print("remaining products with deleted id:", remaining)
    if remaining:
        raise SystemExit(1)
    print("VERIFICATION OK")


if __name__ == "__main__":
    asyncio.run(main())
