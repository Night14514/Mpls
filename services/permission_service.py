"""
Сервис прав доступа для админ-панели.
"""

import logging
from typing import List, Set

from config import get_settings
from models import User
from services.secret_access_service import SecretAccessService

logger = logging.getLogger(__name__)


class PermissionService:
    """Проверка прав доступа."""

    HIDDEN_ACTIONS: Set[str] = {
        "admin:cat:up",
        "admin:cat:down",
        "admin:secret",
    }

    @classmethod
    def is_security_admin(cls, telegram_id: int) -> bool:
        """Проверить, является ли пользователь security-admin (бутстрап через .env)."""
        settings = get_settings()
        return telegram_id in settings.security_admin_ids

    @classmethod
    async def has_hidden_access(cls, telegram_id: int) -> bool:
        """Проверить, есть ли доступ к скрытым действиям (БД + .env-бутстрап)."""
        if cls.is_security_admin(telegram_id):
            return True
        return await SecretAccessService.has_access(telegram_id)

    @classmethod
    async def can_perform_hidden_action(cls, telegram_id: int, action: str) -> bool:
        """Проверить, можно ли выполнять скрытое действие."""
        if action not in cls.HIDDEN_ACTIONS:
            return True  # Не скрытое действие - доступно всем админам
        return await cls.has_hidden_access(telegram_id)

    @classmethod
    def is_admin(cls, user: User) -> bool:
        """Проверить, является ли пользователь админом."""
        return user.is_admin

    @classmethod
    async def filter_hidden_buttons(cls, buttons: List[dict], telegram_id: int) -> List[dict]:
        """Отфильтровать кнопки, которые должны быть скрыты."""
        if await cls.has_hidden_access(telegram_id):
            return buttons

        return [
            btn for btn in buttons
            if not any(
                btn.get("callback_data", "").startswith(action)
                for action in cls.HIDDEN_ACTIONS
            )
        ]

    @classmethod
    async def validate_callback(cls, callback_data: str, telegram_id: int) -> bool:
        """Проверить валидность callback на серверной стороне."""
        parts = callback_data.split(":")

        # Проверяем по нарастающим префиксам (admin:cat:up, admin:secret, ...)
        for length in (2, 3):
            if len(parts) >= length:
                action = ":".join(parts[:length])
                if action in cls.HIDDEN_ACTIONS:
                    if not await cls.has_hidden_access(telegram_id):
                        logger.warning(
                            "Unauthorized callback attempt: user=%s, action=%s",
                            telegram_id,
                            callback_data,
                        )
                        return False

        return True