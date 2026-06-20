"""
Сервис товаров и категорий.
"""

import logging
from typing import List, Optional

from core.order_engine import STATUS_COMPLETED, STATUS_CONFIRMED
from database import get_db
from models import Category, Product

logger = logging.getLogger(__name__)

_PRODUCT_DEPENDENCY_QUERIES = (
    ("order_items", "SELECT id, order_id, quantity FROM order_items WHERE product_id = ?"),
    ("cart", "SELECT id, user_id, quantity FROM cart WHERE product_id = ?"),
    ("favorites", "SELECT id, user_id FROM favorites WHERE product_id = ?"),
    ("orders", "SELECT id, user_id, status FROM orders WHERE product_id = ?"),
)

_PRODUCT_DELETE_STEPS = (
    ("DELETE FROM order_items WHERE product_id = ?", "order_items.product_id -> products.id"),
    ("DELETE FROM cart WHERE product_id = ?", "cart.product_id -> products.id"),
    ("DELETE FROM favorites WHERE product_id = ?", "favorites.product_id -> products.id"),
    ("UPDATE orders SET product_id = NULL WHERE product_id = ?", "orders.product_id -> products.id"),
    ("DELETE FROM products WHERE id = ?", "products.id"),
)


class ProductService:
    """Управление каталогом."""

    @staticmethod
    def _row_to_product(row) -> Product:
        return Product(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            price=row["price"],
            price_usd=row["price_usd"],
            price_rub=row["price_rub"],
            photo=row["photo"],
            category_id=row["category_id"],
            is_hidden=bool(row["is_hidden"]),
            is_active=bool(row["is_active"]),
            content_data=row["content_data"],
            created_at=row["created_at"],
            category_name=row["category_name"] if "category_name" in row.keys() else None,
            video=row["video"] if "video" in row.keys() else None,
            content_type=row["content_type"] if "content_type" in row.keys() else None,
        )

    @staticmethod
    def _row_to_category(row) -> Category:
        return Category(id=row["id"], name=row["name"], is_hidden=bool(row["is_hidden"]))

    # ── Категории ─────────────────────────────────────────────

    @classmethod
    async def get_categories(cls, include_hidden: bool = False, trusted: bool = False) -> List[Category]:
        async with get_db() as db:
            if include_hidden and trusted:
                cursor = await db.execute("SELECT * FROM categories ORDER BY name")
            elif include_hidden:
                cursor = await db.execute(
                    "SELECT * FROM categories WHERE is_hidden = 0 ORDER BY name"
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM categories WHERE is_hidden = 0 ORDER BY name"
                )
            rows = await cursor.fetchall()
            result = [cls._row_to_category(r) for r in rows]
            if trusted:
                cursor = await db.execute(
                    "SELECT * FROM categories WHERE is_hidden = 1 ORDER BY name"
                )
                hidden_rows = await cursor.fetchall()
                result.extend([cls._row_to_category(r) for r in hidden_rows])
            return result

    @classmethod
    async def get_category(cls, category_id: int) -> Optional[Category]:
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM categories WHERE id = ?", (category_id,))
            row = await cursor.fetchone()
            return cls._row_to_category(row) if row else None

    @classmethod
    async def create_category(cls, name: str, is_hidden: bool = False) -> Optional[Category]:
        async with get_db() as db:
            await db.execute(
                "INSERT INTO categories (name, is_hidden) VALUES (?, ?)",
                (name, 1 if is_hidden else 0),
            )
            cursor = await db.execute("SELECT last_insert_rowid() as id")
            cid = (await cursor.fetchone())["id"]
            cursor = await db.execute(
                "SELECT * FROM categories WHERE id = ?", (cid,)
            )
            row = await cursor.fetchone()
            return cls._row_to_category(row) if row else None

    @classmethod
    async def delete_category(cls, category_id: int) -> bool:
        async with get_db() as db:
            cursor = await db.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            return cursor.rowcount > 0

    # ── Товары ────────────────────────────────────────────────

    @classmethod
    async def get_product(cls, product_id: int) -> Optional[Product]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT p.*, c.name as category_name
                   FROM products p
                   LEFT JOIN categories c ON p.category_id = c.id
                   WHERE p.id = ?""",
                (product_id,),
            )
            row = await cursor.fetchone()
            return cls._row_to_product(row) if row else None

    @classmethod
    async def get_products_by_category(
        cls, category_id: int, trusted: bool = False
    ) -> List[Product]:
        async with get_db() as db:
            if trusted:
                cursor = await db.execute(
                    """SELECT p.*, c.name as category_name
                       FROM products p
                       LEFT JOIN categories c ON p.category_id = c.id
                       WHERE p.category_id = ? AND p.is_active = 1
                       ORDER BY p.created_at DESC""",
                    (category_id,),
                )
            else:
                cursor = await db.execute(
                    """SELECT p.*, c.name as category_name
                       FROM products p
                       LEFT JOIN categories c ON p.category_id = c.id
                       WHERE p.category_id = ? AND p.is_active = 1 AND p.is_hidden = 0
                       ORDER BY p.created_at DESC""",
                    (category_id,),
                )
            rows = await cursor.fetchall()
            return [cls._row_to_product(r) for r in rows]

    @classmethod
    async def get_all_products(cls, active_only: bool = False) -> List[Product]:
        async with get_db() as db:
            q = """SELECT p.*, c.name as category_name
                   FROM products p LEFT JOIN categories c ON p.category_id = c.id"""
            if active_only:
                q += " WHERE p.is_active = 1"
            q += " ORDER BY p.created_at DESC"
            cursor = await db.execute(q)
            rows = await cursor.fetchall()
            return [cls._row_to_product(r) for r in rows]

    @classmethod
    async def create_product(
        cls,
        title: str,
        description: str,
        price: float,
        category_id: Optional[int],
        photo: Optional[str] = None,
        content_data: Optional[str] = None,
        is_hidden: bool = False,
        price_usd: Optional[float] = None,
        price_rub: Optional[float] = None,
        video: Optional[str] = None,
    ) -> Optional[Product]:
        async with get_db() as db:
            await db.execute(
                """INSERT INTO products
                   (title, description, price, photo, category_id, is_hidden, content_data, price_usd, price_rub)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (title, description, price, photo, category_id, 1 if is_hidden else 0, content_data, price_usd, price_rub),
            )
            cursor = await db.execute("SELECT last_insert_rowid() as id")
            pid = (await cursor.fetchone())["id"]
            cursor = await db.execute(
                """SELECT p.*, c.name as category_name
                   FROM products p
                   LEFT JOIN categories c ON p.category_id = c.id
                   WHERE p.id = ?""",
                (pid,),
            )
            row = await cursor.fetchone()
            return cls._row_to_product(row) if row else None

    @classmethod
    async def update_product(cls, product_id: int, **kwargs) -> Optional[Product]:
        allowed = {"title", "description", "price", "photo", "category_id", "is_hidden", "is_active", "content_data", "price_usd", "price_rub"}
        fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not fields:
            return await cls.get_product(product_id)

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [product_id]
        async with get_db() as db:
            await db.execute(f"UPDATE products SET {set_clause} WHERE id = ?", values)
        return await cls.get_product(product_id)

    @classmethod
    async def _log_product_dependencies(cls, db, product_id: int) -> None:
        for table, query in _PRODUCT_DEPENDENCY_QUERIES:
            cursor = await db.execute(query, (product_id,))
            rows = [dict(row) for row in await cursor.fetchall()]
            logger.info(
                "delete_product(%s): related rows in %s: %s",
                product_id,
                table,
                rows,
            )

    @classmethod
    async def delete_product(cls, product_id: int) -> bool:
        """Безопасное удаление товара с зависимыми записями."""
        try:
            async with get_db() as db:
                await cls._log_product_dependencies(db, product_id)
                for sql, fk_label in _PRODUCT_DELETE_STEPS:
                    logger.info(
                        "delete_product(%s): executing %s (%s)",
                        product_id,
                        sql,
                        fk_label,
                    )
                    cursor = await db.execute(
                        sql,
                        (product_id,),
                    )
                    logger.info(
                        "delete_product(%s): %s affected %s row(s)",
                        product_id,
                        sql,
                        cursor.rowcount,
                    )
                    if sql.startswith("DELETE FROM products") and cursor.rowcount == 0:
                        return False
                return True
        except Exception as exc:
            logger.exception(
                "delete_product(%s): failed on SQL cleanup/delete: %s",
                product_id,
                exc,
            )
            return False

    @classmethod
    async def get_popular_products(cls, limit: int = 5) -> List[dict]:
        """Популярные товары по количеству оплаченных заказов."""
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT p.title, COUNT(oi.id) as cnt
                   FROM order_items oi
                   JOIN products p ON oi.product_id = p.id
                   JOIN orders o ON oi.order_id = o.id
                   WHERE o.status IN (?, ?, 'paid', 'completed')
                   GROUP BY p.id
                   ORDER BY cnt DESC
                   LIMIT ?""",
                (STATUS_CONFIRMED, STATUS_COMPLETED, limit),
            )
            rows = await cursor.fetchall()
            return [{"title": r["title"], "count": r["cnt"]} for r in rows]

    # ── Корзина ─────────────────────────────────────────────

    @classmethod
    async def add_to_cart(cls, user_id: int, product_id: int, qty: int = 1) -> None:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, quantity FROM cart WHERE user_id = ? AND product_id = ?",
                (user_id, product_id),
            )
            row = await cursor.fetchone()
            if row:
                await db.execute(
                    "UPDATE cart SET quantity = quantity + ? WHERE id = ?",
                    (qty, row["id"]),
                )
            else:
                await db.execute(
                    "INSERT INTO cart (user_id, product_id, quantity) VALUES (?, ?, ?)",
                    (user_id, product_id, qty),
                )

    @classmethod
    async def update_cart_qty(cls, user_id: int, product_id: int, delta: int) -> None:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, quantity FROM cart WHERE user_id = ? AND product_id = ?",
                (user_id, product_id),
            )
            row = await cursor.fetchone()
            if not row:
                return
            new_qty = row["quantity"] + delta
            if new_qty <= 0:
                await db.execute("DELETE FROM cart WHERE id = ?", (row["id"],))
            else:
                await db.execute(
                    "UPDATE cart SET quantity = ? WHERE id = ?",
                    (new_qty, row["id"]),
                )

    @classmethod
    async def clear_cart(cls, user_id: int) -> None:
        async with get_db() as db:
            await db.execute("DELETE FROM cart WHERE user_id = ?", (user_id,))

    @classmethod
    async def get_cart(cls, user_id: int) -> List[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT c.*, p.title, p.price, p.photo, p.is_active
                   FROM cart c
                   JOIN products p ON c.product_id = p.id
                   WHERE c.user_id = ?""",
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    @classmethod
    async def cart_total(cls, user_id: int) -> tuple:
        items = await cls.get_cart(user_id)
        total = sum(i["price"] * i["quantity"] for i in items)
        count = sum(i["quantity"] for i in items)
        return items, total, count

    # ── Избранное ───────────────────────────────────────────

    @classmethod
    async def toggle_favorite(cls, user_id: int, product_id: int) -> bool:
        """Возвращает True если добавлено, False если удалено."""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id FROM favorites WHERE user_id = ? AND product_id = ?",
                (user_id, product_id),
            )
            row = await cursor.fetchone()
            if row:
                await db.execute("DELETE FROM favorites WHERE id = ?", (row["id"],))
                return False
            await db.execute(
                "INSERT INTO favorites (user_id, product_id) VALUES (?, ?)",
                (user_id, product_id),
            )
            return True

    @classmethod
    async def is_favorite(cls, user_id: int, product_id: int) -> bool:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id FROM favorites WHERE user_id = ? AND product_id = ?",
                (user_id, product_id),
            )
            return await cursor.fetchone() is not None
