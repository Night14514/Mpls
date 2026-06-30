"""
Сервис товаров и категорий.
"""

import logging
from typing import List, Optional

from core.order_engine import STATUS_COMPLETED, STATUS_CONFIRMED
from database import get_db
from models import Category, Product, Subcategory
from database import get_db, transaction

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
        keys = row.keys() if hasattr(row, "keys") else []
        return Product(
            id=row["id"],
            title=row["title"],
            description=row["description"],
            price=row["price"],
            price_usd=row["price_usd"],
            price_rub=row["price_rub"],
            photo=row["photo"],
            category_id=row["category_id"],
            subcategory_id=row["subcategory_id"] if "subcategory_id" in keys else None,
            is_hidden=bool(row["is_hidden"]),
            is_active=bool(row["is_active"]),
            content_data=row["content_data"],
            created_at=row["created_at"],
            category_name=row["category_name"] if "category_name" in keys else None,
            video=row["video"] if "video" in keys else None,
            content_type=row["content_type"] if "content_type" in keys else None,
        )

    @staticmethod
    def _row_to_subcategory(row) -> Subcategory:
        keys = row.keys() if hasattr(row, "keys") else []
        sort_order = row["sort_order"] if "sort_order" in keys else 0
        return Subcategory(
            id=row["id"],
            category_id=row["category_id"],
            name=row["name"],
            is_hidden=bool(row["is_hidden"]),
            sort_order=sort_order,
        )

    @staticmethod
    def _row_to_category(row) -> Category:
        keys = row.keys() if hasattr(row, "keys") else []
        sort_order = row["sort_order"] if "sort_order" in keys else 0
        return Category(id=row["id"], name=row["name"], is_hidden=bool(row["is_hidden"]), sort_order=sort_order)

    # ── Категории ─────────────────────────────────────────────

    @classmethod
    async def get_categories(cls, include_hidden: bool = False, trusted: bool = False) -> List[Category]:
        async with get_db() as db:
            if include_hidden and trusted:
                cursor = await db.execute("SELECT * FROM categories ORDER BY sort_order ASC, name ASC")
            elif include_hidden:
                cursor = await db.execute(
                    "SELECT * FROM categories WHERE is_hidden = 0 ORDER BY sort_order ASC, name ASC"
                )
            else:
                cursor = await db.execute(
                    "SELECT * FROM categories WHERE is_hidden = 0 ORDER BY sort_order ASC, name ASC"
                )
            rows = await cursor.fetchall()
            result = [cls._row_to_category(r) for r in rows]
            if trusted:
                cursor = await db.execute(
                    "SELECT * FROM categories WHERE is_hidden = 1 ORDER BY sort_order ASC, name ASC"
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
        async with transaction("IMMEDIATE") as db:
            await db.execute(
                "UPDATE products SET subcategory_id = NULL WHERE category_id = ?",
                (category_id,),
            )
            await db.execute(
                "DELETE FROM subcategories WHERE category_id = ?", (category_id,)
            )
            cursor = await db.execute(
                "DELETE FROM categories WHERE id = ?", (category_id,)
            )
            return cursor.rowcount > 0

    @classmethod
    async def move_category_up(cls, category_id: int) -> bool:
        """Переместить категорию вверх (уменьшить sort_order)."""
        async with transaction("IMMEDIATE") as db:
            # Get current category and its sort_order
            cursor = await db.execute(
                "SELECT id, sort_order FROM categories WHERE id = ?", (category_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return False
            
            current_order = row["sort_order"]
            
            # Find the category above (with lower sort_order)
            cursor = await db.execute(
                """SELECT id, sort_order FROM categories
                   WHERE sort_order < ?
                   ORDER BY sort_order DESC
                   LIMIT 1""",
                (current_order,),
            )
            above_row = await cursor.fetchone()
            if not above_row:
                return False  # Already at the top
            
            # Swap sort_orders
            await db.execute(
                "UPDATE categories SET sort_order = ? WHERE id = ?",
                (above_row["sort_order"], category_id),
            )
            await db.execute(
                "UPDATE categories SET sort_order = ? WHERE id = ?",
                (current_order, above_row["id"]),
            )
            return True

    @classmethod
    async def move_category_down(cls, category_id: int) -> bool:
        """Переместить категорию вниз (увеличить sort_order)."""
        async with transaction("IMMEDIATE") as db:
            # Get current category and its sort_order
            cursor = await db.execute(
                "SELECT id, sort_order FROM categories WHERE id = ?", (category_id,)
            )
            row = await cursor.fetchone()
            if not row:
                return False
            
            current_order = row["sort_order"]
            
            # Find the category below (with higher sort_order)
            cursor = await db.execute(
                """SELECT id, sort_order FROM categories
                   WHERE sort_order > ?
                   ORDER BY sort_order ASC
                   LIMIT 1""",
                (current_order,),
            )
            below_row = await cursor.fetchone()
            if not below_row:
                return False  # Already at the bottom
            
            # Swap sort_orders
            await db.execute(
                "UPDATE categories SET sort_order = ? WHERE id = ?",
                (below_row["sort_order"], category_id),
            )
            await db.execute(
                "UPDATE categories SET sort_order = ? WHERE id = ?",
                (current_order, below_row["id"]),
            )
            return True

    @classmethod
    async def set_category_sort_order(cls, category_id: int, new_order: int) -> bool:
        """Установить конкретный sort_order для категории."""
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT id FROM categories WHERE id = ?", (category_id,)
            )
            if not await cursor.fetchone():
                return False
            
            await db.execute(
                "UPDATE categories SET sort_order = ? WHERE id = ?",
                (new_order, category_id),
            )
            return True

            return True

    # ── Подкатегории ──────────────────────────────────────────

    @classmethod
    async def get_subcategories(
        cls, category_id: int, include_hidden: bool = False, trusted: bool = False
    ) -> List[Subcategory]:
        async with get_db() as db:
            if include_hidden or trusted:
                cursor = await db.execute(
                    """SELECT * FROM subcategories
                       WHERE category_id = ?
                       ORDER BY sort_order ASC, name ASC""",
                    (category_id,),
                )
            else:
                cursor = await db.execute(
                    """SELECT * FROM subcategories
                       WHERE category_id = ? AND is_hidden = 0
                       ORDER BY sort_order ASC, name ASC""",
                    (category_id,),
                )
            rows = await cursor.fetchall()
            return [cls._row_to_subcategory(r) for r in rows]

    @classmethod
    async def has_subcategories(cls, category_id: int, trusted: bool = False) -> bool:
        subs = await cls.get_subcategories(category_id, trusted=trusted)
        return len(subs) > 0

    @classmethod
    async def get_subcategory(cls, subcategory_id: int) -> Optional[Subcategory]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM subcategories WHERE id = ?", (subcategory_id,)
            )
            row = await cursor.fetchone()
            return cls._row_to_subcategory(row) if row else None

    @classmethod
    async def create_subcategory(
        cls, category_id: int, name: str, is_hidden: bool = False
    ) -> Optional[Subcategory]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM subcategories WHERE category_id = ?",
                (category_id,),
            )
            next_order = (await cursor.fetchone())["next_order"]
            await db.execute(
                """INSERT INTO subcategories (category_id, name, is_hidden, sort_order)
                   VALUES (?, ?, ?, ?)""",
                (category_id, name, 1 if is_hidden else 0, next_order),
            )
            cursor = await db.execute("SELECT last_insert_rowid() AS id")
            sid = (await cursor.fetchone())["id"]
        return await cls.get_subcategory(sid)

    @classmethod
    async def update_subcategory(cls, subcategory_id: int, **kwargs) -> Optional[Subcategory]:
        allowed = {"name", "is_hidden", "sort_order", "category_id"}
        fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
        if not fields:
            return await cls.get_subcategory(subcategory_id)
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [subcategory_id]
        async with get_db() as db:
            await db.execute(
                f"UPDATE subcategories SET {set_clause} WHERE id = ?", values
            )
        return await cls.get_subcategory(subcategory_id)

    @classmethod
    async def delete_subcategory(cls, subcategory_id: int) -> bool:
        async with transaction("IMMEDIATE") as db:
            await db.execute(
                "UPDATE products SET subcategory_id = NULL WHERE subcategory_id = ?",
                (subcategory_id,),
            )
            cursor = await db.execute(
                "DELETE FROM subcategories WHERE id = ?", (subcategory_id,)
            )
            return cursor.rowcount > 0

    @classmethod
    async def move_subcategory_up(cls, subcategory_id: int) -> bool:
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT id, category_id, sort_order FROM subcategories WHERE id = ?",
                (subcategory_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return False
            cursor = await db.execute(
                """SELECT id, sort_order FROM subcategories
                   WHERE category_id = ? AND sort_order < ?
                   ORDER BY sort_order DESC LIMIT 1""",
                (row["category_id"], row["sort_order"]),
            )
            above = await cursor.fetchone()
            if not above:
                return False
            await db.execute(
                "UPDATE subcategories SET sort_order = ? WHERE id = ?",
                (above["sort_order"], subcategory_id),
            )
            await db.execute(
                "UPDATE subcategories SET sort_order = ? WHERE id = ?",
                (row["sort_order"], above["id"]),
            )
            return True

    @classmethod
    async def move_subcategory_down(cls, subcategory_id: int) -> bool:
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT id, category_id, sort_order FROM subcategories WHERE id = ?",
                (subcategory_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return False
            cursor = await db.execute(
                """SELECT id, sort_order FROM subcategories
                   WHERE category_id = ? AND sort_order > ?
                   ORDER BY sort_order ASC LIMIT 1""",
                (row["category_id"], row["sort_order"]),
            )
            below = await cursor.fetchone()
            if not below:
                return False
            await db.execute(
                "UPDATE subcategories SET sort_order = ? WHERE id = ?",
                (below["sort_order"], subcategory_id),
            )
            await db.execute(
                "UPDATE subcategories SET sort_order = ? WHERE id = ?",
                (row["sort_order"], below["id"]),
            )
            return True

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
        cls, category_id: int, trusted: bool = False, subcategory_id: Optional[int] = None
    ) -> List[Product]:
        async with get_db() as db:
            params = [category_id]
            subcategory_filter = ""
            if subcategory_id is not None:
                subcategory_filter = " AND p.subcategory_id = ?"
                params.append(subcategory_id)
            else:
                subcategory_filter = " AND p.subcategory_id IS NULL"

            hidden_filter = "" if trusted else " AND p.is_hidden = 0"
            cursor = await db.execute(
                f"""SELECT p.*, c.name as category_name
                    FROM products p
                    LEFT JOIN categories c ON p.category_id = c.id
                    WHERE p.category_id = ? AND p.is_active = 1
                    {subcategory_filter}{hidden_filter}
                    ORDER BY p.created_at DESC""",
                tuple(params),
            )
            rows = await cursor.fetchall()
            return [cls._row_to_product(r) for r in rows]

    @classmethod
    async def get_products_by_subcategory(
        cls, subcategory_id: int, trusted: bool = False
    ) -> List[Product]:
        async with get_db() as db:
            hidden_filter = "" if trusted else " AND p.is_hidden = 0"
            cursor = await db.execute(
                f"""SELECT p.*, c.name as category_name
                    FROM products p
                    LEFT JOIN categories c ON p.category_id = c.id
                    WHERE p.subcategory_id = ? AND p.is_active = 1
                    {hidden_filter}
                    ORDER BY p.created_at DESC""",
                (subcategory_id,),
            )
            rows = await cursor.fetchall()
            return [cls._row_to_product(r) for r in rows]

    @classmethod
    async def get_all_products_in_category(
        cls, category_id: int, trusted: bool = False
    ) -> List[Product]:
        """Все товары категории (с подкатегориями и без)."""
        async with get_db() as db:
            hidden_filter = "" if trusted else " AND p.is_hidden = 0"
            cursor = await db.execute(
                f"""SELECT p.*, c.name as category_name
                    FROM products p
                    LEFT JOIN categories c ON p.category_id = c.id
                    WHERE p.category_id = ? AND p.is_active = 1
                    {hidden_filter}
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
        subcategory_id: Optional[int] = None,
    ) -> Optional[Product]:
        async with get_db() as db:
            await db.execute(
                """INSERT INTO products
                   (title, description, price, photo, category_id, subcategory_id,
                    is_hidden, content_data, price_usd, price_rub)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    title,
                    description,
                    price,
                    photo,
                    category_id,
                    subcategory_id,
                    1 if is_hidden else 0,
                    content_data,
                    price_usd,
                    price_rub,
                ),
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
    allowed = {
        "title", "description", "price", "photo", "category_id", "subcategory_id",
        "is_hidden", "is_active", "content_data", "price_usd", "price_rub",
    }
    # category_id/subcategory_id допускают явный сброс в NULL,
    # остальные поля при None просто игнорируются (не были переданы для изменения)
    nullable = {"category_id", "subcategory_id"}
    fields = {
        k: v for k, v in kwargs.items()
        if k in allowed and (v is not None or k in nullable)
    }
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
