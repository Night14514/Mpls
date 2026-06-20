"""
FSM-состояния для диалогов бота.
"""

from aiogram.fsm.state import State, StatesGroup


class AdminProductStates(StatesGroup):
    """Добавление/редактирование товара."""
    title = State()
    description = State()
    price_usd = State()
    price_rub = State()
    category = State()
    photo = State()
    content = State()
    confirm = State()
    video = State()


class AdminCategoryStates(StatesGroup):
    """Добавление/редактирование категории."""
    name = State()
    is_hidden = State()


class AdminWalletStates(StatesGroup):
    """Управление кошельками."""
    currency = State()
    network = State()
    address = State()
    edit_address = State()


class AdminUserStates(StatesGroup):
    """Поиск пользователя."""
    search = State()


class ManualPaymentStates(StatesGroup):
    """Ручная оплата — ввод TX Hash / Invoice ID."""
    amount = State()
    tx_hash = State()


class AdminBroadcastStates(StatesGroup):
    """Рассылка (опционально)."""
    message = State()


class RegistrationStates(StatesGroup):
    """Регистрация пользователя."""
    country = State()
    city = State()
    city_manual = State()


class TopUpStates(StatesGroup):
    """Пополнение баланса."""
    currency = State()
    amount = State()
    receipt = State()


class AdminBalanceStates(StatesGroup):
    """Управление балансом в админке."""
    user_id = State()
    amount = State()
    view_user_id = State()


class PromoActivateStates(StatesGroup):
    """Активация промокода пользователем."""
    code = State()


class AdminPromoStates(StatesGroup):
    """Управление промокодами."""
    code = State()
    discount = State()
    max_uses = State()


class AdminProductEditStates(StatesGroup):
    """Редактирование товара."""
    field = State()
    value = State()
