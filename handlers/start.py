"""
Стартовые команды и главное меню.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import get_settings
from handlers.registration import start_registration
from keyboards import admin_panel_kb, main_menu_kb
from models import User
from services.referral_service import ReferralService

logger = logging.getLogger(__name__)
router = Router(name="start")


def _welcome_text(user: User) -> str:
    name = user.full_name or user.username or "покупатель"
    return (
        f"👋 Добро пожаловать, <b>{name}</b>!\n\n"
        "Выберите раздел:"
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message, db_user: User, state: FSMContext, command: CommandObject
):
    """Команда /start — регистрация или главное меню."""
    await state.clear()

    referral_code = ReferralService.parse_start_payload(command.args)
    if referral_code:
        # Привязка реферера фиксируется сразу (как pending), но засчитывается
        # пригласившему только после завершения регистрации — это не должно
        # помешать обычному входу, если payload некорректный или пользователь
        # уже зарегистрирован.
        try:
            await ReferralService.attribute_pending_referral(referral_code, db_user)
        except Exception as e:
            logger.error("Ошибка привязки реферала для %s: %s", db_user.telegram_id, e)

    if not db_user.is_registered:
        await start_registration(message, state)
        return
    await message.answer(
        _welcome_text(db_user),
        reply_markup=main_menu_kb(db_user.is_admin),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, db_user: User, state: FSMContext):
    """Возврат в главное меню."""
    await state.clear()
    if not db_user.is_registered:
        await callback.answer("Сначала пройдите регистрацию", show_alert=True)
        await start_registration(callback.message, state)
        return
    try:
        await callback.message.edit_text(
            _welcome_text(db_user),
            reply_markup=main_menu_kb(db_user.is_admin),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.answer(
            _welcome_text(db_user),
            reply_markup=main_menu_kb(db_user.is_admin),
            parse_mode="HTML",
        )
    await callback.answer()


@router.callback_query(F.data == "admin:panel")
async def cb_admin_panel(callback: CallbackQuery, db_user: User):
    """Inline админ-панель."""
    if not db_user.is_admin:
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    from services.permission_service import PermissionService
    has_hidden = await PermissionService.has_hidden_access(db_user.telegram_id)
    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>\n\nВыберите раздел:",
        reply_markup=admin_panel_kb(has_hidden_access=has_hidden),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(Command("give_trust"))
async def cmd_give_trust(message: Message, db_user: User):
    """Выдать VIP-доступ: /give_trust <telegram_id>"""
    if not db_user.is_admin:
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: /give_trust <telegram_id>")
        return

    from services.user_service import UserService

    tid = int(args[1])
    ok = await UserService.set_trusted(tid, True)
    if ok:
        await message.answer(f"✅ VIP выдан пользователю {tid}")
        try:
            await message.bot.send_message(
                tid,
                "⭐ Вам выдан <b>VIP-доступ</b>!",
                parse_mode="HTML",
            )
        except Exception:
            pass
    else:
        await message.answer("❌ Пользователь не найден.")
@router.message(Command("remove_trust"))
async def cmd_remove_trust(message: Message, db_user: User):
    """Снять VIP: /remove_trust <telegram_id>"""
    if not db_user.is_admin:
        return
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("Использование: /remove_trust <telegram_id>")
        return

    from services.user_service import UserService

    tid = int(args[1])
    ok = await UserService.set_trusted(tid, False)
    await message.answer(
        f"✅ VIP снят с пользователя {tid}" if ok else "❌ Пользователь не найден."
    )