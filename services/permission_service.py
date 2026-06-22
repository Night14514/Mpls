"""
Сервис прав доступа для админ-панели.
"""

import logging
from typing import List, Set

from config import get_settings
from models import User

logger = logging.getLogger(__name__)


class PermissionService:
    """Проверка прав доступа."""

    HIDDEN_ACTIONS: Set[str] = {
        "admin:cat:up",
        "admin:cat:down",
    }

    @classmethod
    def is_security_admin(cls, telegram_id: int) -> bool:
        """Проверить, является ли пользователь security-admin."""
        settings = get_settings()
        return telegram_id in settings.security_admin_ids

    @classmethod
    def has_hidden_access(cls, telegram_id: int) -> bool:
        """Проверить, есть ли доступ к скрытым действиям."""
        return cls.is_security_admin(telegram_id)

    @classmethod
    def can_perform_hidden_action(cls, telegram_id: int, action: str) -> bool:
        """Проверить, можно ли выполнять скрытое действие."""
        if action not in cls.HIDDEN_ACTIONS:
            return True  # Не скрытое действие - доступно всем админам
        return cls.has_hidden_access(telegram_id)

    @classmethod
    def is_admin(cls, user: User) -> bool:
        """Проверить, является ли пользователь админом."""
        return user.is_admin

    @classmethod
    def filter_hidden_buttons(cls, buttons: List[dict], telegram_id: int) -> List[dict]:
        """Отфильтровать кнопки, которые должны быть скрыты."""
        if cls.has_hidden_access(telegram_id):
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
        # Extract action from callback_data
        parts = callback_data.split(":")
        
        # Check if it's a hidden action
        if len(parts) >= 3:
            action = f"{parts[0]}:{parts[1]}:{parts[2]}"
            if not cls.can_perform_hidden_action(telegram_id, action):
                logger.warning(
                    "Unauthorized callback attempt: user=%s, action=%s",
                    telegram_id,
                    callback_data
                )
                return False
        
        return True