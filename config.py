""" 
Конфигурация бота — Pydantic Settings. 
Все секреты и настройки загружаются из .env 
""" 
 
from functools import lru_cache 
from typing import List 
 
from pydantic import Field, computed_field 
from pydantic_settings import BaseSettings, SettingsConfigDict 
 
 
class Settings(BaseSettings): 
    """Главный класс настроек приложения.""" 
 
    model_config = SettingsConfigDict( 
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore", 
    ) 
 
    # ── Telegram Bot ────────────────────────────────────────── 
    BOT_TOKEN: str = Field(..., description="Токен бота от @BotFather") 
    # Строка вида "123,456" — pydantic-settings не умеет List[int] из .env без JSON 
    ADMIN_IDS: str = Field(default="", description="Telegram ID администраторов через запятую") 
 
    @computed_field  # type: ignore[prop-decorator] 
    @property 
    def admin_ids(self) -> List[int]: 
        """Список ID администраторов.""" 
        if not self.ADMIN_IDS.strip(): 
            return [] 
        return [int(x.strip()) for x in self.ADMIN_IDS.split(",") if x.strip()] 
 
    # ── База данных ─────────────────────────────────────────── 
    # SQLite по умолчанию; для PostgreSQL: postgresql+asyncpg://user:pass@host/db 
    DATABASE_URL: str = Field( 
        default="sqlite+aiosqlite:///data/database.db", 
        description="URL подключения к БД", 
    ) 
 
    # ── Crypto Bot API ──────────────────────────────────────── 
    CRYPTO_ENABLED: bool = Field(default=True, description="Включить оплату через Crypto Bot") 
    CRYPTO_TOKEN: str = Field(default="", description="API-токен @CryptoBot / @CryptoTestnetBot") 
    CRYPTO_API_URL: str = Field( 
        default="https://pay.crypt.bot/api", 
        description="Базовый URL Crypto Pay API", 
    ) 
    CRYPTO_POLL_INTERVAL: int = Field(default=30, description="Интервал проверки инвойсов (сек)") 
    CRYPTO_ASSET: str = Field(default="USDT", description="Криптовалюта по умолчанию") 
 
    # ── Ручные криптопереводы ───────────────────────────────── 
    MANUAL_CRYPTO_ENABLED: bool = Field( 
        default=False, 
        description="Показывать реквизиты кошельков для ручного перевода", 
    ) 
 
    # ── Прочее ──────────────────────────────────────────────── 
    REVIEWS_CHANNEL: str = Field(default="", description="Отзывы (https://t.me/+PX5XyGhCAFM1OTkx)")
    SUPPORT_USERNAME: str = Field(default="", description="Username поддержки (@ без @)") 
    LOG_LEVEL: str = Field(default="INFO", description="Уровень логирования") 
 
 
@lru_cache 
def get_settings() -> Settings: 
    """Кэшированный singleton настроек.""" 
    return Settings()
