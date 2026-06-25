"""
Сервис прав доступа для админ-панели.
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

from config import get_settings
from database import get_db
from models import User
from services.secret_access_service import SecretAccessService

logger = logging.getLogger(__name__)

# Все ключи прав админ-панели (callback_data или префикс).
ADMIN_PERMISSION_DEFINITIONS: Tuple[Tuple[str, str], ...] = (
    ("admin:products", "📦 Товары"),
    ("admin:categories", "📂 Категории"),
    ("admin:balance", "💰 Баланс"),
    ("admin:promos", "🎁 Промокоды"),
    ("admin:stats", "📊 Статистика"),
    ("admin:users", "👤 Пользователи"),
    ("admin:topups", "💳 Пополнения"),
    ("admin:wallets", "💼 Кошельки"),
    ("admin:vip", "⭐ VIP"),
    ("admin:crypto", "💎 Crypto"),
    ("admin:settings", "⚙️ Настройки"),
    ("admin:ref:menu", "👥 Реф система"),
    ("admin:product_add", "➕ Добавить товар"),
    ("admin:cat_add", "➕ Добавить категорию"),
    ("admin:cat:up", "⬆️ Переместить категорию вверх"),
    ("admin:cat:down", "⬇️ Переместить категорию вниз"),
    ("admin:subcat_add", "➕ Создать подкатегорию"),
    ("admin:subcat:up", "⬆️ Переместить подкатегорию вверх"),
    ("admin:subcat:down", "⬇️ Переместить подкатегорию вниз"),
    ("admin:bal_add", "➕ Начислить баланс"),
    ("admin:bal_sub", "➖ Списать баланс"),
    ("admin:bal_info", "🔍 Инфо по ID"),
    ("admin:promo_add", "➕ Создать промокод"),
    ("admin:vip:settings", "⚙️ Настройки VIP"),
    ("admin:vip:list", "👥 Список VIP"),
    ("admin:vip:grant", "🎁 Выдать VIP"),
    ("admin:ref:stats", "📊 Статистика рефералов"),
    ("admin:ref:top", "🏆 Топ рефералов"),
    ("admin:ref:rewards", "🎁 Выданные награды"),
    ("admin:ref:settings", "⚙ Настройки реферальной системы"),
    ("admin:secret", "🔐 Секретный доступ"),
    ("admin:secret:grant", "➕ Выдать секретный доступ"),
    ("admin:secret:revoke", "➖ Забрать секретный доступ"),
    ("admin:secret:list", "📋 Список секретного доступа"),
    ("admin:secret:log", "🗒 Журнал действий"),
    ("admin:secret:permissions", "🔑 Управление полномочиями"),
    ("admin:payments", "💳 Платежи"),
    ("admin:order_confirm", "✅ Подтвердить заказ"),
    ("admin:topup_ok", "✅ Одобрить пополнение"),
    ("admin:topup_no", "❌ Отклонить пополнение"),
    ("admin:manual_paid", "✅ Подтвердить ручную оплату"),
)


class PermissionService:
    """Проверка прав доступа."""

    HIDDEN_ACTIONS: Set[str] = {
        "admin:cat:up",
        "admin:cat:down",
        "admin:subcat:up",
        "admin:subcat:down",
        "admin:secret",
        "admin:secret:grant",
        "admin:secret:revoke",
        "admin:secret:list",
        "admin:secret:log",
        "admin:secret:permissions",
        "admin:perm_toggle",
        "admin:perm_page",
    }

    _permission_cache: Optional[Dict[str, bool]] = None

    @classmethod
    def all_permission_keys(cls) -> List[str]:
        return [key for key, _ in ADMIN_PERMISSION_DEFINITIONS]

    @classmethod
    def permission_label(cls, permission_key: str) -> str:
        for key, label in ADMIN_PERMISSION_DEFINITIONS:
            if key == permission_key:
                return label
        return permission_key

    @classmethod
    def resolve_permission_key(cls, callback_data: str) -> Optional[str]:
        """Сопоставить callback_data с ключом права (самый длинный префикс)."""
        if not callback_data.startswith("admin:"):
            return None

        keys = sorted(cls.all_permission_keys(), key=len, reverse=True)
        for key in keys:
            if callback_data == key or callback_data.startswith(f"{key}:"):
                return key

        # Динамические callback: admin:product:123 -> admin:products
        dynamic_map = {
            "admin:product": "admin:products",
            "admin:product_edit": "admin:products",
            "admin:product_del": "admin:products",
            "admin:edit_field": "admin:products",
            "admin:product_cat": "admin:products",
            "admin:product_create": "admin:products",
            "admin:product_content_video": "admin:products",
            "admin:skip_content": "admin:products",
            "admin:cat": "admin:categories",
            "admin:cat_del": "admin:categories",
            "admin:cat_del_yes": "admin:categories",
            "admin:subcat": "admin:subcat_add",
            "admin:subcats": "admin:categories",
            "admin:perm_toggle": "admin:secret:permissions",
            "admin:perm_page": "admin:secret:permissions",
            "admin:promo": "admin:promos",
            "admin:promo_del": "admin:promos",
            "admin:wallet_del": "admin:wallets",
            "admin:vip": "admin:vip",
            "admin:ref": "admin:ref:menu",
            "admin:topup": "admin:topups",
        }
        parts = callback_data.split(":")
        for length in range(len(parts), 1, -1):
            prefix = ":".join(parts[:length])
            if prefix in dynamic_map:
                return dynamic_map[prefix]
        return None

    @classmethod
    async def _load_permissions(cls) -> Dict[str, bool]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT permission_key, visible_to_admins FROM admin_permissions"
            )
            rows = await cursor.fetchall()
        return {row["permission_key"]: bool(row["visible_to_admins"]) for row in rows}

    @classmethod
    async def get_permissions(cls) -> Dict[str, bool]:
        """Все права: ключ -> видимость для обычных админов."""
        stored = await cls._load_permissions()
        result = {key: stored.get(key, True) for key in cls.all_permission_keys()}
        return result

    @classmethod
    async def set_permission(cls, permission_key: str, visible_to_admins: bool) -> None:
        async with get_db() as db:
            await db.execute(
                """
                INSERT INTO admin_permissions (permission_key, visible_to_admins, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(permission_key) DO UPDATE SET
                    visible_to_admins = excluded.visible_to_admins,
                    updated_at = excluded.updated_at
                """,
                (permission_key, 1 if visible_to_admins else 0),
            )

    @classmethod
    async def toggle_permission(cls, permission_key: str) -> bool:
        perms = await cls.get_permissions()
        new_value = not perms.get(permission_key, True)
        await cls.set_permission(permission_key, new_value)
        return new_value

    @classmethod
    def is_security_admin(cls, telegram_id: int) -> bool:
        settings = get_settings()
        return telegram_id in settings.security_admin_ids

    @classmethod
    async def has_hidden_access(cls, telegram_id: int) -> bool:
        if cls.is_security_admin(telegram_id):
            return True
        return await SecretAccessService.has_access(telegram_id)

    @classmethod
    async def is_permission_visible(cls, permission_key: str) -> bool:
        perms = await cls.get_permissions()
        return perms.get(permission_key, True)

    @classmethod
    async def can_access_admin_action(cls, telegram_id: int, callback_data: str) -> bool:
        """Серверная проверка: может ли админ выполнить действие."""
        if await cls.has_hidden_access(telegram_id):
            return True

        permission_key = cls.resolve_permission_key(callback_data)
        if permission_key is None:
            return True

        if permission_key in cls.HIDDEN_ACTIONS:
            return False

        return await cls.is_permission_visible(permission_key)

    @classmethod
    async def can_perform_hidden_action(cls, telegram_id: int, action: str) -> bool:
        if action not in cls.HIDDEN_ACTIONS:
            return True
        return await cls.has_hidden_access(telegram_id)

    @classmethod
    def is_admin(cls, user: User) -> bool:
        return user.is_admin

    @classmethod
    async def filter_admin_markup(
        cls, markup, telegram_id: int
    ):
        """Скрыть кнопки админ-панели согласно правам."""
        if await cls.has_hidden_access(telegram_id):
            return markup

        from aiogram.types import InlineKeyboardMarkup

        if not isinstance(markup, InlineKeyboardMarkup):
            return markup

        perms = await cls.get_permissions()
        new_rows = []
        for row in markup.inline_keyboard:
            new_buttons = []
            for btn in row:
                if not btn.callback_data or not btn.callback_data.startswith("admin:"):
                    new_buttons.append(btn)
                    continue
                perm_key = cls.resolve_permission_key(btn.callback_data)
                if perm_key is None:
                    new_buttons.append(btn)
                    continue
                if perm_key in cls.HIDDEN_ACTIONS:
                    continue
                if perms.get(perm_key, True):
                    new_buttons.append(btn)
            if new_buttons:
                new_rows.append(new_buttons)

        return InlineKeyboardMarkup(inline_keyboard=new_rows)

    @classmethod
    async def validate_callback(cls, callback_data: str, telegram_id: int) -> bool:
        if not callback_data.startswith("admin:"):
            return True

        if not await cls.can_access_admin_action(telegram_id, callback_data):
            logger.warning(
                "Unauthorized admin callback: user=%s, action=%s",
                telegram_id,
                callback_data,
            )
            return False
        return True
