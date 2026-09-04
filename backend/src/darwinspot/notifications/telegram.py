from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import httpx2

from darwinspot.config import Settings
from darwinspot.storage.models import TradeIntent, TradeIntentApproval


class TelegramNotConfigured(RuntimeError):
    pass


class TelegramDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class DeliveryResult:
    message_id: int | None
    chat_id: str


def _list_value(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    values = cast(list[Any], parsed)
    return [item for item in values if isinstance(item, str)][:6]


class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if not all(
            (
                settings.telegram_bot_token,
                settings.telegram_operator_chat_id is not None,
                settings.telegram_operator_user_id is not None,
                settings.telegram_webhook_secret,
            )
        ):
            raise TelegramNotConfigured("Telegram Bot API is not configured")
        self._base_url = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

    @staticmethod
    def callback_data(action: str, approval_id: str) -> str:
        if action not in {"approve", "reject"}:
            raise ValueError("unsupported Telegram approval action")
        if len(approval_id) != 36:
            raise ValueError("approval reference must be an opaque UUID")
        return f"{action}:{approval_id}"

    @staticmethod
    def format_proposal(
        intent: TradeIntent, approval: TradeIntentApproval, *, now: datetime | None = None
    ) -> str:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        expires = max(0, int((_aware(approval.expires_at) - current).total_seconds()))
        policy: dict[str, Any]
        try:
            policy_value = json.loads(intent.policy_evidence)
            policy = cast(dict[str, Any], policy_value) if isinstance(policy_value, dict) else {}
        except json.JSONDecodeError:
            policy = {}
        mandate_result = str(policy.get("mandate_result", "PASS"))
        risk_result = str(policy.get("risk_result", "PASS"))
        budget_result = str(policy.get("budget_result", intent.budget_result))
        rationale = html.escape(intent.rationale[:1000])
        supporting = "\n".join(
            f"+ {html.escape(item[:200])}" for item in _list_value(intent.supporting_factors)
        )
        risks = "\n".join(
            f"- {html.escape(item[:200])}" for item in _list_value(intent.risk_factors)
        )
        confidence = (
            format(
                (Decimal(str(intent.confidence)) * Decimal("100")).quantize(Decimal("0.01")), "f"
            )
            .rstrip("0")
            .rstrip(".")
        )
        notional = intent.committed_notional or intent.quote_notional or Decimal("0")
        price = intent.price or policy.get("reference_price") or "unavailable"
        return (
            "<b>DARWIN SIGNAL</b>\n\n"
            f"<b>Pair:</b> {html.escape(intent.pair)} · {html.escape(intent.side)}\n"
            f"<b>Order type:</b> {html.escape(intent.order_type)}\n"
            f"<b>Proposed notional:</b> {html.escape(str(notional))} USDT\n"
            f"<b>Reference price:</b> {html.escape(str(price))}\n"
            f"<b>Confidence:</b> {confidence}%\n\n"
            f"<b>Why {html.escape(intent.side)}:</b>\n{rationale}\n\n"
            f"<b>Supporting factors:</b>\n{supporting or '+ none returned'}\n\n"
            f"<b>Risks:</b>\n{risks or '- none returned'}\n\n"
            f"<b>Mandate:</b> {html.escape(mandate_result)}\n"
            f"<b>Risk:</b> {html.escape(risk_result)}\n"
            f"<b>Budget:</b> {html.escape(budget_result)}\n"
            "<b>Mode:</b> HUMAN_APPROVAL\n"
            f"<b>Intent ID:</b> <code>{html.escape(intent.id)}</code>\n"
            f"<b>Expires in:</b> {expires} seconds"
        )

    @staticmethod
    def format_result(intent: TradeIntent, result: str, reason: str | None = None) -> str:
        suffix = f"\nReason: {html.escape(reason[:512])}" if reason else ""
        return (
            f"<b>DARWIN RESULT</b>\n\n"
            f"Intent <code>{html.escape(intent.id)}</code>\n"
            f"{html.escape(intent.pair)} · {html.escape(intent.side)}\n"
            f"State: <b>{html.escape(result)}</b>{suffix}"
        )

    @staticmethod
    def format_auto_signal(intent: TradeIntent) -> str:
        try:
            value = json.loads(intent.policy_evidence)
            policy = cast(dict[str, Any], value) if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            policy = {}
        notional = intent.committed_notional or intent.quote_notional or Decimal("0")
        confidence = format(
            (Decimal(str(intent.confidence)) * Decimal("100")).quantize(Decimal("0.01")), "f"
        ).rstrip("0").rstrip(".")
        return (
            "<b>DARWIN AUTO SIGNAL</b>\n\n"
            f"<b>Pair:</b> {html.escape(intent.pair)} · {html.escape(intent.side)}\n"
            f"<b>Notional:</b> {html.escape(str(notional))} USDT\n"
            f"<b>Confidence:</b> {confidence}%\n"
            f"<b>Why:</b> {html.escape(intent.rationale[:1000])}\n"
            f"<b>Mode:</b> {html.escape(intent.execution_mode)}\n"
            f"<b>Policy:</b> {html.escape(str(policy.get('execution_policy_result', 'PASS')))}\n"
            "<b>Execution:</b> pending"
        )

    async def send_proposal(
        self, intent: TradeIntent, approval: TradeIntentApproval
    ) -> DeliveryResult:
        return await self._send(
            "sendMessage",
            {
                "chat_id": approval.operator_chat_id,
                "text": self.format_proposal(intent, approval),
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "APPROVE",
                                "callback_data": self.callback_data(
                                    "approve", approval.approval_id
                                ),
                            },
                            {
                                "text": "REJECT",
                                "callback_data": self.callback_data("reject", approval.approval_id),
                            },
                        ]
                    ]
                },
            },
        )

    async def send_auto_signal(self, intent: TradeIntent) -> DeliveryResult:
        return await self._send(
            "sendMessage",
            {
                "chat_id": self.settings.telegram_operator_chat_id,
                "text": self.format_auto_signal(intent),
                "parse_mode": "HTML",
            },
        )

    async def send_result(
        self, intent: TradeIntent, result: str, reason: str | None = None
    ) -> DeliveryResult:
        return await self._send(
            "sendMessage",
            {
                "chat_id": self.settings.telegram_operator_chat_id,
                "text": self.format_result(intent, result, reason),
                "parse_mode": "HTML",
            },
        )

    async def answer_callback(self, callback_query_id: str, text: str) -> None:
        await self._send(
            "answerCallbackQuery", {"callback_query_id": callback_query_id, "text": text[:200]}
        )

    async def _send(self, method: str, payload: dict[str, Any]) -> DeliveryResult:
        try:
            async with httpx2.AsyncClient(timeout=10.0) as client:
                response = await client.post(f"{self._base_url}/{method}", json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            raise TelegramDeliveryError("Telegram Bot API request failed") from exc
        if not isinstance(body, dict):
            raise TelegramDeliveryError("Telegram Bot API returned an invalid response")
        body = cast(dict[str, Any], body)
        if body.get("ok") is not True:
            raise TelegramDeliveryError("Telegram Bot API returned an unsuccessful response")
        raw_result = body.get("result")
        result = cast(dict[str, Any], raw_result) if isinstance(raw_result, dict) else {}
        raw_chat = result.get("chat")
        chat = cast(dict[str, Any], raw_chat) if isinstance(raw_chat, dict) else {}
        message_id = result.get("message_id")
        chat_id = str(chat.get("id", self.settings.telegram_operator_chat_id))
        return DeliveryResult(
            message_id=message_id if isinstance(message_id, int) else None, chat_id=chat_id
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
