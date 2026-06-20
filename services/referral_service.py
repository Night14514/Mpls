"""
Сервис реферальной системы.

Схема данных:
    users.referral_code        — стабильный уникальный код приглашающего (генерируется лениво).
    referrals                  — связь referrer -> referred, с состоянием pending/confirmed.
                                  UNIQUE(referred_user_id) на уровне БД защищает от двойной
                                  привязки одного и того же приглашённого, в том числе при
                                  гонке параллельных апдейтов.
    referral_rewards           — выданные награды, UNIQUE(referrer_user_id, milestone)
                                  защищает от повторной выдачи за один и тот же порог.
    referral_settings          — единственная строка (id=1) с настройками программы,
                                  редактируется админом без перезапуска бота.

Состояния referrals.status:
    'pending'   — пользователь перешёл по ссылке, но ещё не завершил регистрацию.
    'confirmed' — регистрация завершена, реферал засчитан пригласившему.

Принцип идемпотентности: единственная операция, которая реально засчитывает реферала —
confirm_referral(), вызывается из registration._finish_registration после того, как
is_registered стал 1. Она атомарна (BEGIN IMMEDIATE), проверяет текущий статус строки
и переводит pending -> confirmed ровно один раз благодаря условию в WHERE.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from database import get_db, transaction
from models import Referral, ReferralReward, ReferralSettings, User
from services.promo_service import PromoService
from services.user_service import UserService

logger = logging.getLogger(__name__)

_PAYLOAD_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


@dataclass
class AttributionResult:
    """Результат попытки привязать pending-реферала к новому пользователю."""
    ok: bool
    reason: str  # 'attributed' | 'self' | 'duplicate' | 'invalid' | 'disabled' | 'already_registered'


@dataclass
class ConfirmationResult:
    """Результат засчёта реферала после завершения регистрации."""
    confirmed: bool
    referrer_user_id: Optional[int] = None
    referrer_telegram_id: Optional[int] = None
    new_referral_count: int = 0
    reward_granted: bool = False
    reward_promo_code: Optional[str] = None
    reward_amount: float = 0
    reward_milestone: int = 0


class ReferralService:
    """Бизнес-логика реферальной программы."""

    # ── Настройки ───────────────────────────────────────────────

    @staticmethod
    def _row_to_settings(row) -> ReferralSettings:
        return ReferralSettings(
            enabled=bool(row["enabled"]),
            threshold=row["threshold"],
            reward_amount=row["reward_amount"],
            updated_at=row["updated_at"],
        )

    @classmethod
    async def get_settings(cls) -> ReferralSettings:
        async with get_db() as db:
            cursor = await db.execute("SELECT * FROM referral_settings WHERE id = 1")
            row = await cursor.fetchone()
            if not row:
                # Защита на случай гонки с миграцией / ручного удаления строки.
                await db.execute(
                    "INSERT OR IGNORE INTO referral_settings (id) VALUES (1)"
                )
                cursor = await db.execute("SELECT * FROM referral_settings WHERE id = 1")
                row = await cursor.fetchone()
            return cls._row_to_settings(row)

    @classmethod
    async def update_settings(
        cls,
        enabled: Optional[bool] = None,
        threshold: Optional[int] = None,
        reward_amount: Optional[float] = None,
    ) -> ReferralSettings:
        current = await cls.get_settings()
        new_enabled = current.enabled if enabled is None else enabled
        new_threshold = current.threshold if threshold is None else threshold
        new_amount = current.reward_amount if reward_amount is None else reward_amount

        async with get_db() as db:
            await db.execute(
                """UPDATE referral_settings
                   SET enabled = ?, threshold = ?, reward_amount = ?, updated_at = datetime('now')
                   WHERE id = 1""",
                (1 if new_enabled else 0, new_threshold, new_amount),
            )
        logger.info(
            "Настройки реферальной программы изменены: enabled=%s threshold=%s reward=%s",
            new_enabled, new_threshold, new_amount,
        )
        return ReferralSettings(
            enabled=new_enabled, threshold=new_threshold, reward_amount=new_amount
        )

    # ── Ссылка ──────────────────────────────────────────────────

    @classmethod
    async def get_or_create_link(cls, bot_username: str, user_id: int) -> str:
        code = await UserService.ensure_referral_code(user_id)
        return f"https://t.me/{bot_username}?start={code}"

    # ── Парсинг payload /start ─────────────────────────────────

    @staticmethod
    def parse_start_payload(raw: Optional[str]) -> Optional[str]:
        """Извлечь реферальный код из payload /start.

        Поддерживает: '<code>' и 'ref_<code>'. Возвращает None, если payload
        отсутствует или не проходит базовую валидацию формата — бот не должен
        падать на произвольном мусоре в /start.
        """
        if not raw:
            return None
        raw = raw.strip()
        if raw.startswith("ref_"):
            raw = raw[4:]
        if not raw or not _PAYLOAD_RE.match(raw):
            return None
        return raw.upper()

    # ── Привязка pending-реферала (на входе по ссылке) ─────────

    @classmethod
    async def attribute_pending_referral(
        cls, referral_code: str, new_user: User
    ) -> AttributionResult:
        """Создать pending-связь при первом /start по реферальной ссылке.

        Засчёт (confirmed) на этом шаге НЕ происходит — это лишь фиксация того,
        кто кого пригласил, до завершения регистрации.
        """
        settings = await cls.get_settings()
        if not settings.enabled:
            return AttributionResult(False, "disabled")

        if new_user.is_registered:
            # Пользователь уже был зарегистрирован раньше — нельзя задним числом
            # назначить ему реферера.
            logger.info(
                "Реферальная привязка отклонена: пользователь %s уже зарегистрирован",
                new_user.telegram_id,
            )
            return AttributionResult(False, "already_registered")

        referrer = await UserService.get_by_referral_code(referral_code)
        if not referrer:
            logger.info("Реферальный код не найден: %s", referral_code)
            return AttributionResult(False, "invalid")

        if referrer.id == new_user.id:
            logger.warning(
                "Self-referral отклонён: user_id=%s пытался указать себя как реферера",
                new_user.id,
            )
            return AttributionResult(False, "self")

        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT id, status FROM referrals WHERE referred_user_id = ?",
                (new_user.id,),
            )
            existing = await cursor.fetchone()
            if existing:
                logger.info(
                    "Повторная реферальная привязка отклонена: referred_user_id=%s уже привязан (status=%s)",
                    new_user.id, existing["status"],
                )
                return AttributionResult(False, "duplicate")

            await db.execute(
                """INSERT INTO referrals
                   (referrer_user_id, referred_user_id, source_payload, status)
                   VALUES (?, ?, ?, 'pending')""",
                (referrer.id, new_user.id, referral_code),
            )

        logger.info(
            "Найден referrer: referrer_user_id=%s referred_user_id=%s code=%s (pending)",
            referrer.id, new_user.id, referral_code,
        )
        return AttributionResult(True, "attributed")
            # ── Засчёт реферала после завершения регистрации ───────────

    @classmethod
    async def confirm_referral(cls, referred_user_id: int) -> ConfirmationResult:
        """Атомарно засчитать реферал после успешного завершения регистрации.

        Вызывается ровно один раз — из _finish_registration, сразу после того,
        как is_registered становится 1. Идемпотентно: если строки нет или она
        уже confirmed, ничего не делает повторно.
        """
        settings = await cls.get_settings()
        if not settings.enabled:
            return ConfirmationResult(confirmed=False)

        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT id, referrer_user_id FROM referrals "
                "WHERE referred_user_id = ? AND status = 'pending'",
                (referred_user_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return ConfirmationResult(confirmed=False)

            referrer_user_id = row["referrer_user_id"]

            cursor = await db.execute(
                """UPDATE referrals SET status = 'confirmed', confirmed_at = datetime('now')
                   WHERE id = ? AND status = 'pending'""",
                (row["id"],),
            )
            if cursor.rowcount != 1:
                # Кто-то уже подтвердил эту связь параллельно — ничего не делаем повторно.
                return ConfirmationResult(confirmed=False)

            cursor = await db.execute(
                "SELECT COUNT(*) as c FROM referrals "
                "WHERE referrer_user_id = ? AND status = 'confirmed'",
                (referrer_user_id,),
            )
            new_count = (await cursor.fetchone())["c"]

            cursor = await db.execute(
                "SELECT telegram_id FROM users WHERE id = ?", (referrer_user_id,)
            )
            referrer_row = await cursor.fetchone()
            referrer_telegram_id = referrer_row["telegram_id"] if referrer_row else None

        logger.info(
            "Реферал засчитан: referrer_user_id=%s referred_user_id=%s новый счётчик=%s",
            referrer_user_id, referred_user_id, new_count,
        )

        result = ConfirmationResult(
            confirmed=True,
            referrer_user_id=referrer_user_id,
            referrer_telegram_id=referrer_telegram_id,
            new_referral_count=new_count,
        )

        if settings.threshold > 0 and new_count % settings.threshold == 0:
            milestone = new_count // settings.threshold
            reward = await cls._grant_milestone_reward(
                referrer_user_id, milestone, new_count, settings.reward_amount
            )
            if reward:
                result.reward_granted = True
                result.reward_promo_code = reward.promo_code
                result.reward_amount = reward.amount
                result.reward_milestone = milestone

        return result

    # ── Награда ─────────────────────────────────────────────────

    @classmethod
    async def _grant_milestone_reward(
        cls,
        referrer_user_id: int,
        milestone: int,
        referral_count: int,
        reward_amount: float,
    ) -> Optional[ReferralReward]:
        """Выдать одноразовый промокод за достижение очередного порога рефералов.

        UNIQUE(referrer_user_id, milestone) в referral_rewards гарантирует, что
        за один и тот же milestone награда выдаётся не более одного раза, даже
        при повторном вызове (например, из-за гонки или ретрая).
        """
        async with transaction("IMMEDIATE") as db:
            cursor = await db.execute(
                "SELECT id FROM referral_rewards WHERE referrer_user_id = ? AND milestone = ?",
                (referrer_user_id, milestone),
            )
            if await cursor.fetchone():
                logger.info(
                    "Повторная выдача награды отклонена: referrer_user_id=%s milestone=%s",
                    referrer_user_id, milestone,
                )
                return None
            code = cls._generate_promo_code(referrer_user_id, milestone)
            cursor = await db.execute(
                "INSERT INTO referral_rewards "
                "(referrer_user_id, milestone, promo_code, amount, referral_count_at_grant) "
                "VALUES (?, ?, ?, ?, ?)",
                (referrer_user_id, milestone, code, reward_amount, referral_count),
            )

        # Промокод создаётся через существующий PromoService — единая точка для
        # любых скидочных/бонусных кодов в проекте. Одноразовый: max_activations=1.
        await PromoService.create(code=code, amount=reward_amount, max_activations=1)

        logger.info(
            "Выдан промокод за рефералов: referrer_user_id=%s milestone=%s code=%s amount=%s",
            referrer_user_id, milestone, code, reward_amount,
        )

        return ReferralReward(
            id=0,
            referrer_user_id=referrer_user_id,
            milestone=milestone,
            promo_code=code,
            amount=reward_amount,
            referral_count_at_grant=referral_count,
        )

    @staticmethod
    def _generate_promo_code(referrer_user_id: int, milestone: int) -> str:
        import secrets
        import string

        suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(5))
        return f"REF{referrer_user_id}M{milestone}{suffix}"

    # ── Статистика для пользователя ────────────────────────────

    @classmethod
    async def get_user_stats(cls, user_id: int) -> dict:
        settings = await cls.get_settings()
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) as c FROM referrals "
                "WHERE referrer_user_id = ? AND status = 'confirmed'",
                (user_id,),
            )
            confirmed_count = (await cursor.fetchone())["c"]

            cursor = await db.execute(
                "SELECT COUNT(*) as c FROM referral_rewards WHERE referrer_user_id = ?",
                (user_id,),
            )
            rewards_count = (await cursor.fetchone())["c"]

        threshold = settings.threshold or 1
        progress_in_cycle = confirmed_count % threshold
        remaining = 0 if progress_in_cycle == 0 and confirmed_count == 0 else threshold - progress_in_cycle
        if confirmed_count == 0:
            remaining = threshold

        return {
            "confirmed_count": confirmed_count,
            "rewards_count": rewards_count,
            "threshold": threshold,
            "progress_in_cycle": progress_in_cycle,
            "remaining_to_next": remaining,
            "reward_amount": settings.reward_amount,
        }

    @classmethod
    async def get_user_rewards(cls, user_id: int) -> List[ReferralReward]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM referral_rewards WHERE referrer_user_id = ? ORDER BY created_at DESC",
                (user_id,),
            )
            rows = await cursor.fetchall()
            return [
                ReferralReward(
                    id=r["id"],
                    referrer_user_id=r["referrer_user_id"],
                    milestone=r["milestone"],
                    promo_code=r["promo_code"],
                    amount=r["amount"],
                    referral_count_at_grant=r["referral_count_at_grant"],
                    created_at=r["created_at"],
                )
                for r in rows
            ]

    @classmethod
    async def get_user_referrals(cls, user_id: int, limit: int = 20) -> List[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT r.*, u.username, u.full_name, u.telegram_id
                   FROM referrals r
                   JOIN users u ON u.id = r.referred_user_id
                   WHERE r.referrer_user_id = ?
                   ORDER BY r.created_at DESC
                   LIMIT ?""",
                (user_id, limit),
            )
            return [dict(r) for r in await cursor.fetchall()]
            # ── Статистика и управление для админки ────────────────────

    @classmethod
    async def get_admin_overview(cls) -> dict:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT COUNT(*) as c FROM referrals WHERE status = 'confirmed'"
            )
            total_confirmed = (await cursor.fetchone())["c"]

            cursor = await db.execute(
                "SELECT COUNT(*) as c FROM referrals "
                "WHERE status = 'confirmed' AND date(confirmed_at) = date('now')"
            )
            today = (await cursor.fetchone())["c"]

            cursor = await db.execute(
                "SELECT COUNT(*) as c FROM referrals "
                "WHERE status = 'confirmed' AND confirmed_at >= datetime('now', '-7 days')"
            )
            week = (await cursor.fetchone())["c"]

            cursor = await db.execute(
                "SELECT COUNT(DISTINCT referrer_user_id) as c FROM referrals"
            )
            participants = (await cursor.fetchone())["c"]

            cursor = await db.execute("SELECT COUNT(*) as c FROM referral_rewards")
            rewards_count = (await cursor.fetchone())["c"]

            cursor = await db.execute(
                "SELECT COUNT(DISTINCT promo_code) as c FROM referral_rewards"
            )
            promos_count = (await cursor.fetchone())["c"]

        return {
            "total_confirmed": total_confirmed,
            "today": today,
            "week": week,
            "participants": participants,
            "rewards_count": rewards_count,
            "promos_count": promos_count,
        }

    @classmethod
    async def get_top_referrers(cls, limit: int = 10) -> List[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT u.id, u.telegram_id, u.username, u.full_name, COUNT(*) as cnt
                   FROM referrals r
                   JOIN users u ON u.id = r.referrer_user_id
                   WHERE r.status = 'confirmed'
                   GROUP BY r.referrer_user_id
                   ORDER BY cnt DESC
                   LIMIT ?""",
                (limit,),
            )
            return [dict(r) for r in await cursor.fetchall()]

    @classmethod
    async def get_all_rewards(cls, limit: int = 30) -> List[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                """SELECT rr.*, u.telegram_id, u.username, u.full_name
                   FROM referral_rewards rr
                   JOIN users u ON u.id = rr.referrer_user_id
                   ORDER BY rr.created_at DESC
                   LIMIT ?""",
                (limit,),
            )
            return [dict(r) for r in await cursor.fetchall()]