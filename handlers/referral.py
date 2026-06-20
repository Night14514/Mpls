"""
Реферальная система: пользовательский раздел.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards import referral_back_kb, referral_menu_kb
from models import User
from services.referral_service import ReferralService
from utils import escape, format_price, safe_edit_or_send

logger = logging.getLogger(__name__)
router = Router(name="referral")


async def _build_menu_text(bot_username: str, db_user: User) -> str:
    code = await ReferralService.get_or_create_link(bot_username, db_user.id)
    stats = await ReferralService.get_user_stats(db_user.id)
    return (
        "👥 <b>Реферальная программа</b>\n\n"
        "Приглашайте новых пользователей по своей ссылке.\n\n"
        f"За каждые {stats['threshold']} пользователей, которые зарегистрируются "
        f"через вашу ссылку и завершат регистрацию, вы получите промокод на "
        f"{stats['reward_amount']:g} ₽.\n\n"
        f"📈 Приглашено: {stats['confirmed_count']} "
        f"(до награды: {stats['progress_in_cycle']}/{stats['threshold']})\n"
        f"🎁 Получено наград: {stats['rewards_count']}\n\n"
        f"🔗 Ваша ссылка:\n{code}"
    )


@router.callback_query(F.data == "ref:menu")
async def cb_ref_menu(callback: CallbackQuery, db_user: User):
    """Открыть раздел реферальной системы."""
    if not db_user.is_registered:
        await callback.answer("Сначала пройдите регистрацию", show_alert=True)
        return

    me = await callback.bot.get_me()
    text = await _build_menu_text(me.username, db_user)

    logger.info("Пользователь открыл раздел реферальной системы: user_id=%s", db_user.id)

    await safe_edit_or_send(callback, text, reply_markup=referral_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "ref:link")
async def cb_ref_link(callback: CallbackQuery, db_user: User):
    """Показать персональную реферальную ссылку."""
    me = await callback.bot.get_me()
    link = await ReferralService.get_or_create_link(me.username, db_user.id)
    await safe_edit_or_send(
        callback,
        "🔗 <b>Ваша реферальная ссылка</b>\n\n"
        f"{link}\n\n"
        "Отправьте её друзьям — после их регистрации реферал будет засчитан автоматически.",
        reply_markup=referral_back_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "ref:list")
async def cb_ref_list(callback: CallbackQuery, db_user: User):
    """Список приглашённых пользователей (только свои, не чужие)."""
    referrals = await ReferralService.get_user_referrals(db_user.id, limit=20)
    if not referrals:
        text = "📋 <b>Ваши рефералы</b>\n\nПока никто не зарегистрировался по вашей ссылке."
    else:
        lines = []
        for r in referrals:
            name = r["full_name"] or (f"@{r['username']}" if r["username"] else f"ID {r['telegram_id']}")
            status_icon = "✅" if r["status"] == "confirmed" else "⏳"
            lines.append(f"{status_icon} {escape(name)}")
        confirmed_total = sum(1 for r in referrals if r["status"] == "confirmed")
        text = (
            "📋 <b>Ваши рефералы</b>\n\n"
            + "\n".join(lines)
            + f"\n\nЗасчитано: {confirmed_total}"
        )
    await safe_edit_or_send(callback, text, reply_markup=referral_back_kb())
    await callback.answer()


@router.callback_query(F.data == "ref:rewards")
async def cb_ref_rewards(callback: CallbackQuery, db_user: User):
    """Список наград, полученных пользователем."""
    rewards = await ReferralService.get_user_rewards(db_user.id)
    if not rewards:
        text = "🎁 <b>Мои награды</b>\n\nНаград пока нет — приглашайте друзей, чтобы получить первую!"
    else:
        lines = [
            f"🎟 <code>{r.promo_code}</code> — {format_price(r.amount)} "
            f"(порог: {r.referral_count_at_grant})"
            for r in rewards
        ]
        text = "🎁 <b>Мои награды</b>\n\n" + "\n".join(lines)
    await safe_edit_or_send(callback, text, reply_markup=referral_back_kb())
    await callback.answer()