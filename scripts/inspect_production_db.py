"""Inspect production database.db schema and reproduce product delete error."""
import asyncio
import os
import sqlite3
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("BOT_TOKEN", "0000000000:TEST_TOKEN_FOR_DIAGNOSTICS")
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///data/database.db"

DB_PATH = ROOT / "data" / "database.db"


def inspect_db(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    print("DB:", db_path, "size:", db_path.stat().st_size)
    print("PRAGMA foreign_keys:", conn.execute("PRAGMA foreign_keys").fetchone()[0])

    print("\n=== products ===")
    print(conn.execute("SELECT sql FROM sqlite_master WHERE name='products'").fetchone()["sql"])

    print("\n=== All tables with product_id column ===")
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    for t in tables:
        cols = conn.execute(f"PRAGMA table_info({t['name']})").fetchall()
        for col in cols:
            if col["name"] == "product_id":
                print(f"\nTABLE {t['name']}:")
                print(conn.execute(
                    f"SELECT sql FROM sqlite_master WHERE name='{t['name']}'"
                ).fetchone()["sql"])
                for fk in conn.execute(f"PRAGMA foreign_key_list({t['name']})").fetchall():
                    if fk["table"] == "products":
                        print(
                            f"  FK: {t['name']}.{fk['from']} -> products.{fk['to']} "
                            f"ON DELETE {fk['on_delete']} ON UPDATE {fk['on_update']}"
                        )
                print(f"  product_id notnull={col['notnull']}")

    print("\n=== Product counts ===")
    pc = conn.execute("SELECT COUNT(*) c FROM products").fetchone()["c"]
    print("products:", pc)
    if pc:
        rows = conn.execute(
            "SELECT id, title FROM products ORDER BY id LIMIT 10"
        ).fetchall()
        for r in rows:
            pid = r["id"]
            print(f"\n--- product #{pid} {r['title']!r} ---")
            for table in ("cart", "favorites", "orders", "order_items"):
                try:
                    cnt = conn.execute(
                        f"SELECT COUNT(*) c FROM {table} WHERE product_id = ?", (pid,)
                    ).fetchone()["c"]
                    if cnt:
                        print(f"  {table}: {cnt}")
                        sample = conn.execute(
                            f"SELECT * FROM {table} WHERE product_id = ? LIMIT 3", (pid,)
                        ).fetchall()
                        for s in sample:
                            print(f"    {dict(s)}")
                except sqlite3.Error as e:
                    print(f"  {table}: ERROR {e}")

    conn.close()


async def try_delete_products() -> None:
    from db.connection import get_db
    from services.product_service import ProductService

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    products = conn.execute("SELECT id, title FROM products ORDER BY id").fetchall()
    conn.close()

    for p in products:
        pid = p["id"]
        print(f"\n========== TRY DELETE product #{pid} ==========")
        async with get_db() as db:
            for table in ("order_items", "cart", "favorites", "orders"):
                try:
                    cur = await db.execute(
                        f"SELECT COUNT(*) c FROM {table} WHERE product_id = ?", (pid,)
                    )
                    print(f"  before {table}: {(await cur.fetchone())['c']}")
                except Exception as e:
                    print(f"  before {table}: {e}")

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
                    print(f"EXEC: {sql}")
                    cur = await db.execute(sql, params)
                    print(f"  rowcount={cur.rowcount}")
        except Exception as exc:
            print(f"FAILED on product #{pid}: {type(exc).__name__}: {exc}")
            traceback.print_exc()


if __name__ == "__main__":
    inspect_db(DB_PATH)
    asyncio.run(try_delete_products())
