"""
Раздел промокодов для пользователей.
"""

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from handlers.registration import start_registration
from keyboards import promo_back_kb, promo_menu_kb
from models import User
from services.promo_service import PromoService
from services.user_service import UserService
from states import PromoActivateStates
from utils import format_price

logger = logging.getLogger(__name__)
router = Router(name="promo")

_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{3,32}$")


def _promo_section_text(balance: float) -> str:
    return (
        "🎁 <b>Промокоды</b>\n\n"
        "Активируйте промокод и получите бонус на баланс.\n\n"
        f"💰 Текущий баланс: <b>{format_price(balance)}</b>\n\n"
        "Нажмите кнопку ниже и введите код."
    )


async def _activate_and_reply(user: User, code: str) -> str:
    """Активировать промокод и сформировать ответ."""
    ok, msg, _ = await PromoService.activate(user.id, code)
    fresh = await UserService.get_by_telegram_id(user.telegram_id)
    balance = fresh.balance if fresh else user.balance

    if ok:
        return (
            f"✅ <b>Промокод активирован!</b>\n\n"
            f"{msg}\n"
            f"💰 Ваш баланс: <b>{format_price(balance)}</b>"
        )
    return f"❌ {msg}"


@router.callback_query(F.data == "menu:promo")
async def cb_promo_menu(callback: CallbackQuery, db_user: User, state: FSMContext):
    """Раздел промокодов."""
    await state.clear()
    if not db_user.is_registered:
        await callback.answer("Сначала пройдите регистрацию", show_alert=True)
        await start_registration(callback.message, state)
        return

    user = await UserService.get_by_telegram_id(db_user.telegram_id)
    from utils import safe_edit_or_send

    await safe_edit_or_send(
        callback,
        _promo_section_text(user.balance),
        reply_markup=promo_menu_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "promo:activate")
async def cb_promo_activate(callback: CallbackQuery, state: FSMContext, db_user: User):
    """Начать ввод промокода."""
    if not db_user.is_registered:
        await callback.answer("Сначала пройдите регистрацию", show_alert=True)
        return

    await state.set_state(PromoActivateStates.code)
    from utils import safe_edit_or_send

    await safe_edit_or_send(
        callback,
        "✨ <b>Активация промокода</b>\n\n"
        "Введите промокод (латиница, цифры):",
        reply_markup=promo_back_kb(),
    )
    await callback.answer()


@router.message(PromoActivateStates.code)
async def on_promo_code_input(message: Message, state: FSMContext, db_user: User):
    """Пользователь ввёл промокод."""
    code = message.text.strip().upper()
    if not _CODE_RE.match(code):
        await message.answer(
            "❌ Некорректный формат промокода.\n"
            "Введите код ещё раз (3–32 символа, латиница и цифры):",
            reply_markup=promo_back_kb(),
        )
        return

    text = await _activate_and_reply(db_user, code)
    await state.clear()
    await message.answer(text, reply_markup=promo_menu_kb(), parse_mode="HTML")


@router.message(Command("promo"))
async def cmd_promo(message: Message, db_user: User, state: FSMContext):
    """Команда /promo КОД — быстрая активация."""
    await state.clear()
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        user = await UserService.get_by_telegram_id(db_user.telegram_id)
        await message.answer(
            _promo_section_text(user.balance),
            reply_markup=promo_menu_kb(),
            parse_mode="HTML",
        )
        return

    code = args[1].strip().upper()
    if not _CODE_RE.match(code):
        await message.answer("❌ Некорректный формат промокода.")
        return

    text = await _activate_and_reply(db_user, code)
    await message.answer(text, reply_markup=promo_menu_kb(), parse_mode="HTML")
