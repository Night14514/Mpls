"""
Сервис получения курсов валют.
Использует API Центрального Банка России для получения курса USD к RUB.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import aiohttp

from database import get_db

logger = logging.getLogger(__name__)


class CurrencyService:
    """Сервис для работы с курсами валют."""

    # URL API ЦБ РФ для получения курса USD
    CBR_API_URL = "https://www.cbr-xml-daily.ru/daily_json.js"

    # Время кеширования курса в секундах (1 час)
    CACHE_TTL = 3600

    @staticmethod
    async def get_usd_rub_rate() -> float:
        """
        Получить текущий курс USD к RUB.
        Сначала проверяет кеш, если нет или устарел - запрашивает из API.
        """
        # Проверяем кеш в базе данных
        cached_rate = await CurrencyService._get_cached_rate()
        if cached_rate is not None:
            return cached_rate

        # Запрашиваем из API
        try:
            rate = await CurrencyService._fetch_rate_from_api()
            if rate:
                # Сохраняем в кеш
                await CurrencyService._save_cached_rate(rate)
                return rate
        except Exception as e:
            logger.error("Ошибка получения курса из API: %s", e)

        # Если не удалось получить курс, возвращаем дефолтное значение
        logger.warning("Используется дефолтный курс USD/RUB: 90.0")
        return 90.0

    @staticmethod
    async def _get_cached_rate() -> Optional[float]:
        """Получить курс из кеша базы данных."""
        try:
            async with get_db() as db:
                cursor = await db.execute(
                    """SELECT rate, updated_at FROM currency_rates 
                       WHERE currency_pair = 'USD/RUB' 
                       ORDER BY updated_at DESC LIMIT 1"""
                )
                row = await cursor.fetchone()

                if not row:
                    return None

                rate = row["rate"]
                updated_at = row["updated_at"]

                # Проверяем, не устарел ли кеш
                try:
                    updated_dt = datetime.fromisoformat(updated_at.replace("Z", ""))
                    if datetime.now() - updated_dt < timedelta(seconds=CurrencyService.CACHE_TTL):
                        return rate
                except (ValueError, AttributeError):
                    pass

                return None
        except Exception as e:
            logger.error("Ошибка получения кешированного курса: %s", e)
            return None

    @staticmethod
    async def _fetch_rate_from_api() -> Optional[float]:
        """Запросить курс из API ЦБ РФ."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(CurrencyService.CBR_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        logger.error("API ЦБ РФ вернул статус: %s", response.status)
                        return None

                    data = await response.json()

                    # Извлекаем курс USD из ответа
                    if "Valute" in data and "USD" in data["Valute"]:
                        usd_data = data["Valute"]["USD"]
                        # Курс возвращается как строка, нужно конвертировать
                        rate_str = usd_data.get("Value", "0")
                        try:
                            return float(rate_str)
                        except ValueError:
                            logger.error("Не удалось конвертировать курс в float: %s", rate_str)
                            return None

                    logger.error("Не удалось найти USD в ответе API")
                    return None
        except asyncio.TimeoutError:
            logger.error("Таймаут при запросе к API ЦБ РФ")
            return None
        except Exception as e:
            logger.error("Ошибка запроса к API ЦБ РФ: %s", e)
            return None

    @staticmethod
    async def _save_cached_rate(rate: float) -> None:
        """Сохранить курс в кеш базы данных."""
        try:
            async with get_db() as db:
                # Сначала создаём таблицу, если её нет
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS currency_rates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        currency_pair TEXT NOT NULL,
                        rate REAL NOT NULL,
                        updated_at TEXT DEFAULT (datetime('now'))
                    )
                """)

                # Вставляем или обновляем курс
                await db.execute("""
                    INSERT INTO currency_rates (currency_pair, rate)
                    VALUES ('USD/RUB', ?)
                """, (rate,))
        except Exception as e:
            logger.error("Ошибка сохранения курса в кеш: %s", e)

    @staticmethod
    async def convert_usd_to_rub(usd_amount: float) -> float:
        """Конвертировать USD в RUB по текущему курсу."""
        rate = await CurrencyService.get_usd_rub_rate()
        return round(usd_amount * rate, 2)

    @staticmethod
    async def convert_rub_to_usd(rub_amount: float) -> float:
        """Конвертировать RUB в USD по текущему курсу."""
        rate = await CurrencyService.get_usd_rub_rate()
        if rate == 0:
            return 0.0
        return round(rub_amount / rate, 2)
