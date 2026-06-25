"""
Модели данных (dataclass) для типизации в сервисах.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class User:
    """Пользователь бота."""
    id: int
    telegram_id: int
    username: Optional[str]
    full_name: Optional[str]
    balance: float
    is_admin: bool
    is_trusted: bool
    created_at: str = ""
    country: Optional[str] = None
    city: Optional[str] = None
    is_registered: bool = False
    is_vip: bool = False
    vip_purchased_at: Optional[str] = None
    vip_expiry: Optional[str] = None
    vip_plan: Optional[str] = None


@dataclass
class PromoCode:
    """Промокод."""
    id: int
    code: str
    amount: float
    max_activations: int
    used_count: int
    is_active: bool = True
    created_at: str = ""


@dataclass
class BalanceTopup:
    """Заявка на пополнение баланса."""
    id: int
    user_id: int
    amount: float
    status: str
    receipt_file_id: Optional[str]
    receipt_type: Optional[str]
    created_at: str = ""


@dataclass
class Subcategory:
    """Подкатегория товаров."""
    id: int
    category_id: int
    name: str
    is_hidden: bool = False
    sort_order: int = 0


@dataclass
class Category:
    """Категория товаров."""
    id: int
    name: str
    is_hidden: bool = False
    sort_order: int = 0


@dataclass
class Product:
    """Товар маркетплейса."""
    id: int
    title: str
    description: Optional[str]
    price: float
    price_usd: Optional[float] = None
    price_rub: Optional[float] = None
    photo: Optional[str] = None
    category_id: Optional[int] = None
    subcategory_id: Optional[int] = None
    is_hidden: bool = False
    is_active: bool = True
    content_data: Optional[str] = None
    created_at: str = ""
    category_name: Optional[str] = None
    video: Optional[str] = None
    content_type: Optional[str] = None


@dataclass
class CartItem:
    """Позиция в корзине."""
    id: int
    user_id: int
    product_id: int
    quantity: int
    product: Optional[Product] = None


@dataclass
class Order:
    """Заказ."""
    id: int
    user_id: int
    product_id: Optional[int]
    price: float
    payment_method: Optional[str]
    payment_id: Optional[str]
    status: str
    created_at: str = ""
    product_title: Optional[str] = None
    confirmed_by: Optional[int] = None
    confirmed_at: Optional[str] = None


@dataclass
class Payment:
    """Платёж."""
    id: int
    user_id: int
    order_id: Optional[int]
    provider: str
    provider_payment_id: Optional[str]
    amount: float
    currency: Optional[str]
    status: str
    created_at: str = ""


@dataclass
class Wallet:
    """Криптокошелёк для ручных переводов."""
    id: int
    network: str
    address: str
    is_active: bool = True


@dataclass
class CryptoInvoice:
    """Инвойс Crypto Bot, ожидающий оплаты."""
    id: int
    user_id: int
    order_id: Optional[int]
    invoice_id: str
    amount: float
    asset: Optional[str]
    status: str
    created_at: str = ""


@dataclass
class Stats:
    """Сводная статистика для админ-панели."""
    total_users: int
    total_orders: int
    paid_orders: int

    crypto_revenue: float
    new_users_today: int
    popular_products: list


@dataclass
class Referral:
    """Связь «пригласивший → приглашённый»."""
    id: int
    referrer_user_id: int
    referred_user_id: int
    source_payload: Optional[str]
    status: str  # 'pending' | 'confirmed'
    created_at: str = ""
    confirmed_at: Optional[str] = None


@dataclass
class ReferralReward:
    """Выданная награда за достижение порога рефералов."""
    id: int
    referrer_user_id: int
    milestone: int
    promo_code: str
    amount: float
    referral_count_at_grant: int
    created_at: str = ""


@dataclass
class ReferralSettings:
    """Настройки реферальной программы (singleton-строка)."""
    enabled: bool
    threshold: int
    reward_amount: float
    updated_at: str = ""


@dataclass
class VIPPlan:
    """Тариф VIP-подписки."""
    key: str
    label: str
    price: float
    days: int


@dataclass
class VIPSettings:
    """Настройки VIP-доступа (singleton-строка)."""
    enabled: bool
    price: float
    discount_percent: int
    updated_at: str = ""
