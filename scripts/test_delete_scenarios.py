"""Test product delete against legacy FK schema."""
from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "0000000000:TEST")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///data/test_delete.db"

SRC = ROOT / "data" / "database.db"
DST = ROOT / "data" / "test_delete.db"


def seed() -> int:
    if DST.exists():
        DST.unlink()
    shutil.copy2(SRC, DST)
    conn = sqlite3.connect(DST)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO products (title, description, price) VALUES ('TestCart', 'd', 100)"
    )
    pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO orders (user_id, product_id, price, payment_method, status) "
        "VALUES (1, NULL, 100, 'balance', 'COMPLETED')"
    )
    oid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO order_items (order_id, product_id, price, quantity) VALUES (?, ?, 100, 1)",
        (oid, pid),
    )
    conn.execute(
        "INSERT INTO cart (user_id, product_id, quantity) VALUES (1, ?, 1)", (pid,)
    )
    conn.execute(
        "INSERT INTO favorites (user_id, product_id) VALUES (1, ?)", (pid,)
    )
    conn.commit()
    conn.close()
    return pid


async def run_delete(pid: int) -> None:
    from db.connection import get_db

    async with get_db() as db:
        steps = [
            ("DELETE FROM order_items WHERE product_id = ?", (pid,)),
            ("DELETE FROM cart WHERE product_id = ?", (pid,)),
            ("DELETE FROM favorites WHERE product_id = ?", (pid,)),
            ("UPDATE orders SET product_id = NULL WHERE product_id = ?", (pid,)),
            ("DELETE FROM products WHERE id = ?", (pid,)),
        ]
        for sql, params in steps:
            print(f"EXEC: {sql}")
            try:
                cur = await db.execute(sql, params)
                print(f"  rowcount={cur.rowcount}")
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                return
    print("DELETE OK")


async def run_delete_without_order_items_cleanup(pid: int) -> None:
    from db.connection import get_db

    print("\n--- delete WITHOUT order_items cleanup ---")
    async with get_db() as db:
        steps = [
            ("DELETE FROM cart WHERE product_id = ?", (pid,)),
            ("DELETE FROM favorites WHERE product_id = ?", (pid,)),
            ("UPDATE orders SET product_id = NULL WHERE product_id = ?", (pid,)),
            ("DELETE FROM products WHERE id = ?", (pid,)),
        ]
        for sql, params in steps:
            print(f"EXEC: {sql}")
            try:
                cur = await db.execute(sql, params)
                print(f"  rowcount={cur.rowcount}")
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {exc}")
                traceback.print_exc()
                return


if __name__ == "__main__":
    pid = seed()
    print("seeded product_id=", pid)
    asyncio.run(run_delete(pid))
    pid2 = seed()
    asyncio.run(run_delete_without_order_items_cleanup(pid2))
