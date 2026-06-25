"""
Точка входа: Telegram бот.
Базовый функционал для работы бота.
"""

import asyncio
import logging
import sys
from pathlib import Path

from config import get_settings
from database import init_db
from utils import setup_logging


logger = logging.getLogger(__name__)


async def main() -> None:
    """Запуск бота."""
    settings = get_settings()
    setup_logging(settings.LOG_LEVEL)

    if not settings.BOT_TOKEN:
        logger.critical("BOT_TOKEN не установлен в .env")
        sys.exit(1)

    # Инициализация базы данных
    await init_db()
    logger.info("База данных готова")

    # Импорт и инициализация бота
    try:
        from aiogram import Bot, Dispatcher
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.fsm.storage.memory import MemoryStorage
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        from middlewares import ThrottleMiddleware, UserMiddleware, RateLimitMiddleware
        from handlers import admin, catalog, orders, payments, profile, promo, registration, start, referral

        bot = Bot(
            token=settings.BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        dp = Dispatcher(storage=MemoryStorage())

        # Middleware
        dp.message.middleware(UserMiddleware())
        dp.callback_query.middleware(UserMiddleware())
        dp.message.middleware(ThrottleMiddleware())
        dp.callback_query.middleware(ThrottleMiddleware())
        dp.message.middleware(RateLimitMiddleware())
        dp.callback_query.middleware(RateLimitMiddleware())

        # Роутеры (порядок важен: payments перед catalog для pre_checkout)
        dp.include_router(registration.router)
        dp.include_router(start.router)
        dp.include_router(promo.router)
        dp.include_router(profile.router)
        dp.include_router(referral.router)
        dp.include_router(orders.router)
        dp.include_router(payments.router)
        dp.include_router(catalog.router)
        dp.include_router(admin.router)

        # APScheduler — проверка Crypto платежей и очистка VIP
        scheduler = AsyncIOScheduler()
        if settings.CRYPTO_ENABLED and settings.CRYPTO_TOKEN:
            async def crypto_poll_job(bot: Bot) -> None:
                try:
                    await payments.poll_crypto_invoices(bot)
                except Exception as e:
                    logger.error("crypto_poll_job ошибка: %s", e)

            scheduler.add_job(
                crypto_poll_job,
                "interval",
                seconds=settings.CRYPTO_POLL_INTERVAL,
                args=[bot],
                id="crypto_poll",
                replace_existing=True,
            )

        async def vip_cleanup_job() -> None:
            try:
                from services.vip_service import VIPService
                removed = await VIPService.cleanup_expired_vips()
                if removed:
                    logger.info("VIP cleanup: removed %s expired subscriptions", removed)
            except Exception as e:
                logger.error("vip_cleanup_job ошибка: %s", e)

        scheduler.add_job(
            vip_cleanup_job,
            "interval",
            hours=1,
            id="vip_cleanup",
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Фоновые задачи запущены (crypto poll, VIP cleanup)")

        logger.info("🚀 Запуск бота...")
        try:
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            if scheduler.running:
                scheduler.shutdown()
            await bot.session.close()

    except Exception as e:
        logger.error("Ошибка инициализации бота: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
