""" 
Inline-клавиатуры бота. 
""" 
 
from typing import List, Optional 
 
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup 
from aiogram.utils.keyboard import InlineKeyboardBuilder 
 
from core.order_engine import ( 
    STATUS_CANCELLED, 
    STATUS_COMPLETED, 
    STATUS_CONFIRMED, 
    STATUS_PENDING, 
    group_orders_by_status, 
    normalize_order_status, 
) 
from data.countries import COUNTRIES, POPULAR_CITIES 
from config import get_settings 
from models import Category, Order, Product, PromoCode, Wallet 
 
 
ORDER_STATUS_LABELS = { 
    STATUS_PENDING: "⏳ Ожидающие", 
    STATUS_CONFIRMED: "✅ Подтверждённые", 
    STATUS_COMPLETED: "🏁 Завершённые", 
    STATUS_CANCELLED: "❌ Отменённые", 
} 
 
 
def main_menu_kb(is_admin: bool = False) -> InlineKeyboardMarkup: 
    """Главное меню.""" 
    builder = InlineKeyboardBuilder() 
    builder.row( 
        InlineKeyboardButton(text="🛍 Маркет", callback_data="menu:market"), 
        InlineKeyboardButton(text="👤 Профиль", callback_data="menu:profile"), 
    ) 
    builder.row( 
        InlineKeyboardButton(text="📦 Мои заказы", callback_data="menu:my_orders"), 
        InlineKeyboardButton(text="🎁 Промокоды", callback_data="menu:promo"), 
    ) 
    builder.row(
        InlineKeyboardButton(text="👥 Реферальная система", callback_data="ref:menu"),
    )
     
    # Добавляем кнопку "Админ панель" для администраторов
    if is_admin:
        builder.row(
            InlineKeyboardButton(text="⚙️ Админ панель", callback_data="admin:panel")
        )
     
    # Добавляем кнопку "Отзывы" если настроен канал 
    settings = get_settings()
    if settings.REVIEWS_CHANNEL: 
        builder.row( 
            InlineKeyboardButton(text="💬 Отзывы", url=settings.REVIEWS_CHANNEL) 
        ) 
     
    return builder.as_markup()
 
 
def promo_menu_kb() -> InlineKeyboardMarkup: 
    """Раздел промокодов.""" 
    builder = InlineKeyboardBuilder() 
    builder.row( 
        InlineKeyboardButton(text="✨ Активировать промокод", callback_data="promo:activate"), 
    ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")) 
    return builder.as_markup() 
 
 
def promo_back_kb() -> InlineKeyboardMarkup: 
    """После ввода кода — назад в раздел промокодов.""" 
    builder = InlineKeyboardBuilder() 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:promo")) 
    builder.row(InlineKeyboardButton(text="🏠 Главное меню", callback_data="menu:main")) 
    return builder.as_markup() 
 
 
def back_kb(callback_data: str = "menu:main") -> InlineKeyboardMarkup: 
    """Универсальная кнопка «Назад».""" 
    return InlineKeyboardMarkup( 
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=callback_data)]] 
    ) 
 
 
def back_to_menu_kb() -> InlineKeyboardMarkup: 
    """Назад в главное меню.""" 
    return back_kb("menu:main") 
 
 
def currency_selection_kb() -> InlineKeyboardMarkup:
    """Подтверждение валюты пополнения (только рубли)."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🇷🇺 Пополнить в рублях", callback_data="topup:currency:RUB"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:profile"))
    return builder.as_markup()


def topup_methods_kb() -> InlineKeyboardMarkup:
    """Выбор способа пополнения баланса."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💎 Crypto Bot", callback_data="topup:method:crypto"),
    )
    builder.row(
        InlineKeyboardButton(text="💳 Ручной перевод", callback_data="topup:method:manual"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:profile"))
    return builder.as_markup()


def profile_kb(is_vip: bool = False) -> InlineKeyboardMarkup:
    """Кнопки профиля."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="profile:topup"))
    if not is_vip:
        builder.row(InlineKeyboardButton(text="⭐ VIP доступ", callback_data="vip:info"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"))
    return builder.as_markup() 
 
 
def insufficient_balance_kb() -> InlineKeyboardMarkup: 
    """Недостаточно средств — предложить пополнение.""" 
    builder = InlineKeyboardBuilder() 
    builder.row(InlineKeyboardButton(text="💳 Пополнить баланс", callback_data="profile:topup")) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")) 
    return builder.as_markup() 
 
 
def countries_kb() -> InlineKeyboardMarkup: 
    """Выбор страны при регистрации.""" 
    builder = InlineKeyboardBuilder() 
    for key, name in COUNTRIES.items(): 
        builder.row(InlineKeyboardButton(text=name, callback_data=f"reg:country:{key}")) 
    return builder.as_markup() 
 
 
def cities_kb(country_key: str) -> InlineKeyboardMarkup: 
    """Выбор города — популярные + «Другой город».""" 
    builder = InlineKeyboardBuilder() 
    cities = POPULAR_CITIES.get(country_key, []) 
    for city in cities: 
        builder.row(
            InlineKeyboardButton(text=f"🏙 {city}", callback_data=f"reg:city:{city}") 
        ) 
    builder.row(InlineKeyboardButton(text="✏️ Другой город", callback_data="reg:city:other")) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="reg:back_country")) 
    return builder.as_markup() 
 
 
def categories_kb(categories: List[Category], prefix: str = "cat") -> InlineKeyboardMarkup: 
    """Список категорий маркета.""" 
    builder = InlineKeyboardBuilder() 
    for cat in categories: 
        builder.row( 
            InlineKeyboardButton( 
                text=f"📂 {cat.name}", 
                callback_data=f"{prefix}:{cat.id}", 
            ) 
        ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")) 
    return builder.as_markup() 
 
 
def products_kb( 
    products: List[Product], category_id: int, page: int = 0, per_page: int = 5 
) -> InlineKeyboardMarkup: 
    """Список товаров с пагинацией.""" 
    builder = InlineKeyboardBuilder() 
    start = page * per_page 
    chunk = products[start : start + per_page] 
 
    for p in chunk: 
        price = p.price_rub if p.price_rub is not None else p.price
        builder.row( 
            InlineKeyboardButton( 
                text=f"🛍 {p.title} — {int(price)} ₽", 
                callback_data=f"product:{p.id}", 
            ) 
        ) 
 
    nav = [] 
    if page > 0: 
        nav.append( 
            InlineKeyboardButton(text="◀️", callback_data=f"products_page:{category_id}:{page - 1}") 
        ) 
    if start + per_page < len(products): 
        nav.append( 
            InlineKeyboardButton(text="▶️", callback_data=f"products_page:{category_id}:{page + 1}") 
        ) 
    if nav: 
        builder.row(*nav) 
 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:market")) 
    return builder.as_markup() 
 
 
def product_card_kb(product_id: int, category_id: Optional[int] = None) -> InlineKeyboardMarkup: 
    """Карточка товара — Купить и Назад.""" 
    back_data = f"cat:{category_id}" if category_id else "menu:market" 
    builder = InlineKeyboardBuilder() 
    builder.row(InlineKeyboardButton(text="🛒 Купить", callback_data=f"buy_balance:{product_id}")) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=back_data)) 
    return builder.as_markup() 
 
 
def topup_wallets_kb() -> InlineKeyboardMarkup: 
    """После показа реквизитов — ожидание чека.""" 
    builder = InlineKeyboardBuilder() 
    builder.row(InlineKeyboardButton(text="⬅️ Отмена", callback_data="menu:profile")) 
    return builder.as_markup() 
 
 
def topup_approve_kb(topup_id: int) -> InlineKeyboardMarkup: 
    """Кнопки подтверждения пополнения для админа.""" 
    return InlineKeyboardMarkup( 
        inline_keyboard=[ 
            [ 
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin:topup_ok:{topup_id}"), 
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin:topup_no:{topup_id}"), 
            ] 
        ] 
    ) 
 
 
# ── Legacy-клавиатуры (Crypto, корзина) ─────────────── 
 
def cart_kb(product_ids: List[int]) -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    for pid in product_ids: 
        builder.row( 
            InlineKeyboardButton(text="➖", callback_data=f"cart_dec:{pid}"), 
            InlineKeyboardButton(text=f"ID {pid}", callback_data=f"product:{pid}"), 
            InlineKeyboardButton(text="➕", callback_data=f"cart_inc:{pid}"), 
        ) 
    builder.row(InlineKeyboardButton(text="🗑 Очистить", callback_data="cart_clear")) 
    builder.row( 
 
        InlineKeyboardButton(text="💎 Crypto Bot", callback_data="checkout:crypto"), 
    ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"))
    return builder.as_markup() 
 
 
def payment_kb(pay_url: str, invoice_id: str) -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    builder.row(InlineKeyboardButton(text="💳 Перейти к оплате", url=pay_url)) 
    builder.row( 
        InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"crypto_check:{invoice_id}") 
    ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")) 
    return builder.as_markup() 
 
 
def orders_kb(orders: List[Order], page: int = 0, per_page: int = 5) -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    grouped = group_orders_by_status(orders) 
    ordered = [] 
    for status in (STATUS_PENDING, STATUS_CONFIRMED, STATUS_COMPLETED, STATUS_CANCELLED): 
        ordered.extend(grouped.get(status, [])) 
 
    start = page * per_page 
    current_status = None 
    for order in ordered[start : start + per_page]: 
        status = normalize_order_status(order.status) 
        if status != current_status: 
            current_status = status 
            builder.row( 
                InlineKeyboardButton( 
                    text=ORDER_STATUS_LABELS.get(status, status), 
                    callback_data=f"orders_section:{status}", 
                ) 
            ) 
        builder.row( 
            InlineKeyboardButton( 
                text=f"📦 #{order.id}", 
                callback_data=f"order:{order.id}", 
            ) 
        ) 
    nav = [] 
    if page > 0: 
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"orders_page:{page - 1}")) 
    if start + per_page < len(ordered): 
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"orders_page:{page + 1}")) 
    if nav: 
        builder.row(*nav) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")) 
    return builder.as_markup() 
 
 
def wallets_kb(wallets: List[Wallet]) -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    for w in wallets: 
        if w.is_active: 
            builder.row( 
                InlineKeyboardButton( 
                    text=f"💼 {w.network}", 
                    callback_data=f"wallet_select:{w.id}", 
                ) 
            ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")) 
    return builder.as_markup() 
 
 
def manual_paid_kb(order_id: int) -> InlineKeyboardMarkup: 
    return InlineKeyboardMarkup( 
        inline_keyboard=[ 
            [InlineKeyboardButton(text="✅ Я оплатил", callback_data=f"manual_paid:{order_id}")], 
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main")], 
        ] 
    ) 
 
 
def admin_order_confirm_kb(order_id: int) -> InlineKeyboardMarkup: 
    return InlineKeyboardMarkup( 
        inline_keyboard=[ 
            [ 
                InlineKeyboardButton( 
                    text="✅ Подтвердить заказ", 
                    callback_data=f"admin:order_confirm:{order_id}", 
                ) 
            ] 
        ] 
    )

def admin_product_content_video_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎥 Видео", callback_data="admin:product_content_video"))
    return builder.as_markup()
 
 
def admin_panel_kb(has_hidden_access: bool = False) -> InlineKeyboardMarkup:
    """Админ-панель."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📦 Товары", callback_data="admin:products"),
        InlineKeyboardButton(text="📂 Категории", callback_data="admin:categories"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 Баланс", callback_data="admin:balance"),
        InlineKeyboardButton(text="🎁 Промокоды", callback_data="admin:promos"),
    )
    builder.row(
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin:stats"),
        InlineKeyboardButton(text="👤 Пользователи", callback_data="admin:users"),
    )
    builder.row(
        InlineKeyboardButton(text="💳 Пополнения", callback_data="admin:topups"),
        InlineKeyboardButton(text="💼 Кошельки", callback_data="admin:wallets"),
    )
    builder.row(
        InlineKeyboardButton(text="⭐ VIP", callback_data="admin:vip"),
        InlineKeyboardButton(text="💎 Crypto", callback_data="admin:crypto"),
    )
    builder.row(
        InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin:settings"),
    )
    builder.row(
        InlineKeyboardButton(text="👥 Реф система", callback_data="admin:ref:menu"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:main"))
    return builder.as_markup()
 
 
def admin_vip_kb() -> InlineKeyboardMarkup:
    """VIP-меню админки."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚙️ Настройки VIP", callback_data="admin:vip:settings"),
    )
    builder.row(
        InlineKeyboardButton(text="👥 Список VIP", callback_data="admin:vip:list"),
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Выдать VIP", callback_data="admin:vip:grant"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:panel"))
    return builder.as_markup()


def admin_vip_settings_kb(settings: dict) -> InlineKeyboardMarkup:
    """Клавиатура настроек VIP."""
    builder = InlineKeyboardBuilder()
    status = "✅" if settings.get("enabled") else "❌"
    builder.row(
        InlineKeyboardButton(text=f"{status} Включено", callback_data="admin:vip:toggle_enabled"),
    )
    builder.row(
        InlineKeyboardButton(text="💰 Цена", callback_data="admin:vip:set_price"),
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Скидка %", callback_data="admin:vip:set_discount"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:vip"))
    return builder.as_markup()


def admin_balance_kb() -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    builder.row(InlineKeyboardButton(text="➕ Начислить", callback_data="admin:bal_add")) 
    builder.row(InlineKeyboardButton(text="➖ Списать", callback_data="admin:bal_sub")) 
    builder.row(InlineKeyboardButton(text="🔍 Инфо по ID", callback_data="admin:bal_info")) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:panel")) 
    return builder.as_markup() 
 
 
def admin_promos_kb(promos: List[PromoCode]) -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    builder.row(InlineKeyboardButton(text="➕ Создать промокод", callback_data="admin:promo_add")) 
    for p in promos[:15]: 
        status = "✅" if p.is_active else "❌" 
        builder.row( 
            InlineKeyboardButton( 
                text=f"{status} {p.code} — {p.amount} ({p.used_count}/{p.max_activations})", 
                callback_data=f"admin:promo:{p.id}", 
            ) 
        ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:panel")) 
    return builder.as_markup() 
 
 
def admin_products_kb(products: List[Product]) -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    builder.row(InlineKeyboardButton(text="➕ Добавить товар", callback_data="admin:product_add")) 
    for p in products[:20]: 
        status = "✅" if p.is_active else "❌" 
        price = p.price_rub if p.price_rub is not None else p.price
        builder.row( 
            InlineKeyboardButton( 
                text=f"{status} {p.title} — {int(price)} ₽", 
                callback_data=f"admin:product:{p.id}", 
            ) 
        ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:panel")) 
    return builder.as_markup() 
 
 
def admin_product_actions_kb(product_id: int) -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    builder.row( 
        InlineKeyboardButton(text="✏️ Редактировать", callback_data=f"admin:product_edit:{product_id}"), 
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:product_del:{product_id}"), 
    ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:products")) 
    return builder.as_markup() 
 
 
def admin_product_edit_fields_kb(product_id: int) -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    fields = [ 
        ("📝 Название", "title"), 
        ("📄 Описание", "description"), 
        ("💰 Цена", "price"), 
        ("📂 Категория", "category"), 
        ("🖼 Фото", "photo"), 
        ("📎 Контент", "content"), 
        ("🎥 Видео", "video"),
    ] 
    for label, field in fields: 
        builder.row( 
            InlineKeyboardButton( 
                text=label, 
                callback_data=f"admin:edit_field:{product_id}:{field}", 
            ) 
        ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"admin:product:{product_id}")) 
    return builder.as_markup() 
 
 
def admin_category_actions_kb(category_id: int, has_hidden_access: bool = False) -> InlineKeyboardMarkup:
    """Действия с категорией."""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ Название", callback_data=f"admin:cat:edit:{category_id}"),
    )
    if has_hidden_access:
        builder.row(
            InlineKeyboardButton(text="⬆️ Вверх", callback_data=f"admin:cat:up:{category_id}"),
            InlineKeyboardButton(text="⬇️ Вниз", callback_data=f"admin:cat:down:{category_id}"),
        )
    builder.row(
        InlineKeyboardButton(text="🗑 Удалить", callback_data=f"admin:cat:del:{category_id}"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:categories"))
    return builder.as_markup()


def admin_categories_kb(categories: List[Category], has_hidden_access: bool = False) -> InlineKeyboardMarkup: 
    builder = InlineKeyboardBuilder() 
    builder.row(InlineKeyboardButton(text="➕ Добавить", callback_data="admin:cat_add")) 
    for c in categories: 
        builder.row( 
            InlineKeyboardButton( 
                text=f"📂 {c.name}", 
                callback_data=f"admin:cat:{c.id}", 
            ) 
        ) 
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="admin:panel"))
    return builder.as_markup() 
 
 
def confirm_kb(yes_data: str, no_data: str = "admin:panel") -> InlineKeyboardMarkup: 
    return InlineKeyboardMarkup( 
        inline_keyboard=[ 
            [ 
                InlineKeyboardButton(text="✅ Да", callback_data=yes_data), 
                InlineKeyboardButton(text="❌ Нет", callback_data=no_data), 
            ] 
        ] 
    ) 
 
 
def skip_kb(next_data: str) -> InlineKeyboardMarkup: 
    return InlineKeyboardMarkup( 
        inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data=next_data)]] 
    )

# ── Реферальная система: пользователь ───────────────────────

def referral_menu_kb() -> InlineKeyboardMarkup:
    """Раздел «Реферальная система» для пользователя."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔗 Получить ссылку", callback_data="ref:link"))
    builder.row(InlineKeyboardButton(text="📋 Показать моих рефералов", callback_data="ref:list"))
    builder.row(InlineKeyboardButton(text="🎁 Мои награды", callback_data="ref:rewards"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="menu:main"))
    return builder.as_markup()


def referral_back_kb() -> InlineKeyboardMarkup:
    """Назад в раздел реферальной системы."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="ref:menu"))
    return builder.as_markup()


# ── Реферальная система: админ ──────────────────────────────

def admin_referral_menu_kb() -> InlineKeyboardMarkup:
    """Меню управления реферальной системой в админке."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📊 Статистика", callback_data="admin:ref:stats"))
    builder.row(InlineKeyboardButton(text="🏆 Топ рефералов", callback_data="admin:ref:top"))
    builder.row(InlineKeyboardButton(text="🎁 Выданные награды", callback_data="admin:ref:rewards"))
    builder.row(InlineKeyboardButton(text="⚙ Настройки системы", callback_data="admin:ref:settings"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin:panel"))
    return builder.as_markup()


def admin_referral_back_kb() -> InlineKeyboardMarkup:
    """Назад в меню реферальной системы (админ)."""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin:ref:menu"))
    return builder.as_markup()


def admin_referral_settings_kb(enabled: bool) -> InlineKeyboardMarkup:
    """Настройки реферальной программы — переключатель и изменяемые параметры."""
    builder = InlineKeyboardBuilder()
    toggle_text = "🔴 Выключить программу" if enabled else "🟢 Включить программу"
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data="admin:ref:toggle"))
    builder.row(InlineKeyboardButton(text="🔢 Порог рефералов", callback_data="admin:ref:set_threshold"))
    builder.row(InlineKeyboardButton(text="💰 Размер награды", callback_data="admin:ref:set_amount"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="admin:ref:menu"))
    return builder.as_markup()