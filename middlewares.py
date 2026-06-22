"""
Middleware: регистрация пользователей, проверка ролей, защита FSM.
"""

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import get_settings
from services.user_service import UserService

logger = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    """Автоматическая регистрация пользователя при любом апдейте."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = None
        if isinstance(event, Message) and event.from_user:
            user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            user = event.from_user

        if user:
            settings = get_settings()
            is_admin_cfg = user.id in settings.admin_ids
            db_user = await UserService.get_or_create(
                telegram_id=user.id,
                username=user.username,
                full_name=user.full_name or user.first_name,
                force_admin=is_admin_cfg,
            )
            data["db_user"] = db_user

        return await handler(event, data)


class AdminMiddleware(BaseMiddleware):
    """Проверка прав администратора."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        db_user = data.get("db_user")
        if not db_user or not db_user.is_admin:
            if isinstance(event, CallbackQuery):
                await event.answer("⛔ Доступ запрещён", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("⛔ У вас нет прав администратора.")
            return None
        return await handler(event, data)


class ThrottleMiddleware(BaseMiddleware):
    """Простая защита от спама callback-кнопок."""

    def __init__(self, rate_limit: float = 0.3):
        self.rate_limit = rate_limit
        self._last_click: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        import time

        if isinstance(event, CallbackQuery) and event.from_user:
            uid = event.from_user.id
            now = time.monotonic()
            last = self._last_click.get(uid, 0)
            if now - last < self.rate_limit:
                await event.answer("⏳ Подождите...", show_alert=False)
                return None
            self._last_click[uid] = now

        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Расширенная защита от rate limiting и brute force."""

    def __init__(self, max_requests: int = 30, window: int = 60):
        self.max_requests = max_requests
        self.window = window
        self._requests: Dict[int, List[float]] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        import time

        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            uid = event.from_user.id
            now = time.monotonic()
            
            # Clean old requests
            if uid not in self._requests:
                self._requests[uid] = []
            self._requests[uid] = [t for t in self._requests[uid] if now - t < self.window]
            
            # Check rate limit
            if len(self._requests[uid]) >= self.max_requests:
                logger.warning("Rate limit exceeded for user %s", uid)
                if isinstance(event, CallbackQuery):
                    await event.answer("⚠️ Слишком много запросов. Подождите.", show_alert=True)
                elif isinstance(event, Message):
                    await event.answer("⚠️ Слишком много запросов. Подождите.")
                return None
            
            self._requests[uid].append(now)

        return await handler(event, data)
