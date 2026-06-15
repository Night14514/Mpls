"""
Интеграция Crypto Bot API (Crypto Pay).
Автоматическая проверка статуса инвойсов через polling.
"""

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from config import get_settings

logger = logging.getLogger(__name__)


class CryptoPaymentService:
    """Работа с Crypto Pay API."""

    def __init__(self):
        self.settings = get_settings()

    def _headers(self) -> Dict[str, str]:
        return {
            "Crypto-Pay-API-Token": self.settings.CRYPTO_TOKEN,
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, endpoint: str, params: Optional[dict] = None) -> dict:
        """Выполнить запрос к Crypto Pay API."""
        url = f"{self.settings.CRYPTO_API_URL}/{endpoint}"
        async with aiohttp.ClientSession() as session:
            if method == "GET":
                async with session.get(url, headers=self._headers(), params=params) as resp:
                    data = await resp.json()
            else:
                async with session.post(url, headers=self._headers(), json=params) as resp:
                    data = await resp.json()

        if not data.get("ok"):
            error = data.get("error", "Unknown error")
            logger.error("Crypto API ошибка: %s", error)
            raise RuntimeError(f"Crypto API: {error}")
        return data.get("result", data)

    async def create_invoice(
        self,
        amount: float,
        description: str,
        payload: str,
        asset: Optional[str] = None,
    ) -> dict:
        """
        Создать инвойс Crypto Bot.
        Возвращает dict с invoice_id, bot_invoice_url, amount, asset и т.д.
        """
        if not self.settings.CRYPTO_ENABLED:
            raise RuntimeError("Crypto Bot отключён в настройках")
        if not self.settings.CRYPTO_TOKEN:
            raise RuntimeError("CRYPTO_TOKEN не задан")

        asset = asset or self.settings.CRYPTO_ASSET
        params = {
            "currency_type": "crypto",
            "asset": asset,
            "amount": str(amount),
            "description": description[:1024],
            "payload": payload,
            "expires_in": 3600,
        }
        result = await self._request("POST", "createInvoice", params)
        logger.info("Crypto инвойс создан: %s", result.get("invoice_id"))
        return result

    async def get_invoices(self, invoice_ids: List[int]) -> List[dict]:
        """Получить статусы инвойсов по ID."""
        if not invoice_ids:
            return []
        params = {"invoice_ids": ",".join(str(i) for i in invoice_ids)}
        result = await self._request("GET", "getInvoices", params)
        if isinstance(result, dict) and "items" in result:
            return result["items"]
        if isinstance(result, list):
            return result
        return []

    async def get_invoice_by_id(self, invoice_id: str) -> Optional[dict]:
        """Получить один инвойс по ID."""
        try:
            invoices = await self.get_invoices([int(invoice_id)])
            return invoices[0] if invoices else None
        except (ValueError, IndexError):
            return None

    async def check_invoice_paid(self, invoice_id: str) -> bool:
        """Проверить, оплачен ли инвойс."""
        invoice = await self.get_invoice_by_id(invoice_id)
        if not invoice:
            return False
        return invoice.get("status") == "paid"

    async def verify_manual_payment(self, tx_hash_or_invoice_id: str) -> Optional[dict]:
        """
        Проверка ручного платежа по Invoice ID через Crypto Bot API.
        TX Hash напрямую API не проверяет — используем invoice_id если передан.
        """
        if tx_hash_or_invoice_id.isdigit():
            invoice = await self.get_invoice_by_id(tx_hash_or_invoice_id)
            if invoice and invoice.get("status") == "paid":
                return invoice
        return None
