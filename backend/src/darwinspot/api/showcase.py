from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from darwinspot.config import get_settings
from darwinspot.domain import now_utc
from darwinspot.execution.universe import parse_supported_symbols
from darwinspot.storage.database import get_db
from darwinspot.storage.models import AgentConfig, AgentRun, TradeIntent
from darwinspot.storage.repository import Repository

router = APIRouter(tags=["showcase"])
_DECISION_TRIGGERS = ("SCHEDULED", "RUN_ONCE")
_INTERVALS = ("15m", "1h", "4h")
_REASON_CODES = {
    "max_order_notional exceeded": "MAX_ORDER_NOTIONAL",
    "buy exceeds available budget": "BUDGET_EXCEEDED",
    "max_open_actionable_intents reached": "MAX_CONCURRENT_TRADES",
    "symbol is not in allowed_symbols": "SYMBOL_NOT_ALLOWED",
    "symbol is not in configured trading universe": "SYMBOL_NOT_CONFIGURED",
}
_CANDLE_FIELDS = (
    "open_time",
    "close_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
)
_REDACT_PRIVATE_VALUE = re.compile(
    r"(?i)(?:\b(?:api[_ -]?(?:key|secret)|secret|password|token|authorization|"
    r"cookie|session|oauth|telegram|private[_ -]?key)\b\s*[:=]\s*"
    r"(?:bearer\s+)?[^\s,;]+|\bbearer\s+[^\s,;]+)"
)
_REDACT_ACCOUNT_VALUE = re.compile(
    r"(?i)\b(?:account|balance|balances|free|locked|portfolio|wallet|equity|"
    r"funds?)\b[^\n.;,]{0,80}?[$€£]?\d+(?:\.\d+)?"
)


def _public_text(
    value: Any,
    *,
    max_length: int = 2000,
    private_account_values: tuple[tuple[str, str], ...] = (),
) -> str:
    text = value if isinstance(value, str) else str(value)
    text = _REDACT_PRIVATE_VALUE.sub("[REDACTED]", text)
    text = _REDACT_ACCOUNT_VALUE.sub("[REDACTED PRIVATE ACCOUNT DETAIL]", text)
    account_terms = (
        "available",
        "hold",
        "holds",
        "holding",
        "holdings",
        "own",
        "owns",
        "have",
        "has",
        "free",
        "locked",
        "balance",
        "balances",
        "account",
        "portfolio",
        "wallet",
        "equity",
        "funds",
    )
    term_pattern = "|".join(account_terms)
    for asset, numeric_value in private_account_values:
        if numeric_value not in text:
            continue
        escaped_value = re.escape(numeric_value)
        text = re.sub(
            rf"(?i)(?:\b(?:{term_pattern})\b[^\n.;,]{{0,80}}?{escaped_value}(?:\s+{re.escape(asset)})?"
            rf"|{escaped_value}(?:\s+{re.escape(asset)})?[^\n.;,]{{0,80}}?\b(?:{term_pattern})\b)",
            "[REDACTED PRIVATE ACCOUNT VALUE]",
            text,
        )
    return text[:max_length]


def _private_account_values(evidence: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    final_decision = _object(evidence.get("final_decision"))
    balances = _object(final_decision.get("balances"))
    values: set[tuple[str, str]] = set()
    for raw_balance in _list(balances.get("balances")):
        balance = _object(raw_balance)
        asset = balance.get("asset")
        if not isinstance(asset, str) or not asset:
            continue
        for field in ("free", "locked"):
            raw_value = balance.get(field)
            if not isinstance(raw_value, (str, int, float)):
                continue
            numeric_value = str(raw_value)
            values.add((asset, numeric_value))
            try:
                decimal_value = Decimal(numeric_value)
            except InvalidOperation:
                continue
            values.add((asset, format(decimal_value, "f")))
            values.add((asset, format(decimal_value.normalize(), "f")))
    return tuple(sorted(values, key=lambda item: len(item[1]), reverse=True))


def _object(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return cast(list[Any], value) if isinstance(value, list) else []


def _run_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return _object(parsed)


def _json_value(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _string_list(value: Any) -> list[str]:
    return [item for item in _list(value) if isinstance(item, str)]


def _safe_candle(value: Any) -> dict[str, str] | None:
    candle = _object(value)
    if not all(isinstance(candle.get(field), str) for field in _CANDLE_FIELDS):
        return None
    return {field: cast(str, candle[field]) for field in _CANDLE_FIELDS}


def _safe_history(value: Any) -> dict[str, Any] | None:
    history = _object(value)
    if not isinstance(history.get("symbol"), str) or not isinstance(history.get("interval"), str):
        return None
    candles = [_safe_candle(item) for item in _list(history.get("candles"))]
    if not candles or any(candle is None for candle in candles):
        return None
    result: dict[str, Any] = {
        "symbol": history["symbol"],
        "interval": history["interval"],
        "candles": [candle for candle in candles if candle is not None],
    }
    if isinstance(history.get("observed_at"), str):
        result["observed_at"] = history["observed_at"]
    return result


def _safe_history_map(value: Any, intervals: tuple[str, ...]) -> dict[str, Any]:
    source = _object(value)
    result: dict[str, Any] = {}
    for interval in intervals:
        history = _safe_history(source.get(interval))
        if history is not None:
            result[interval] = history
    return result


def _safe_market(value: Any) -> dict[str, str]:
    market = _object(value)
    result: dict[str, str] = {}
    for field in ("symbol", "price", "timestamp", "observed_at"):
        if isinstance(market.get(field), str):
            result[field] = cast(str, market[field])
    return result


def _safe_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    pair_selection = _object(evidence.get("pair_selection"))
    final_decision = _object(evidence.get("final_decision"))
    candidate_failures = {
        symbol: error
        for symbol, error in _object(pair_selection.get("candidate_failures")).items()
        if isinstance(error, str)
    }
    return {
        "pairSelection": {
            "selectedPair": (
                pair_selection.get("selected_pair")
                if isinstance(pair_selection.get("selected_pair"), str)
                else None
            ),
            "candidateSymbols": _string_list(pair_selection.get("candidate_symbols")),
            "effectiveSymbols": _string_list(pair_selection.get("effective_symbols")),
            "candidateFailures": candidate_failures,
        },
        "selectedPair": {
            "selectedPair": (
                final_decision.get("selected_pair")
                if isinstance(final_decision.get("selected_pair"), str)
                else None
            ),
            "market": _safe_market(final_decision.get("market")),
            "marketHistory": _safe_history_map(
                final_decision.get("market_history"), _INTERVALS
            ),
        },
    }


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _evidence_timestamp(evidence: dict[str, Any]) -> datetime | None:
    selected = _object(evidence.get("final_decision"))
    market = _object(selected.get("market"))
    raw = market.get("observed_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw).astimezone(UTC)
        except ValueError:
            pass
    history = _safe_history_map(selected.get("market_history"), _INTERVALS)
    for snapshot in history.values():
        raw_observed = snapshot.get("observed_at")
        if isinstance(raw_observed, str):
            try:
                return datetime.fromisoformat(raw_observed).astimezone(UTC)
            except ValueError:
                continue
    return None


def _policy(run: AgentRun, intent: TradeIntent | None, action: str | None) -> dict[str, Any]:
    if action == "HOLD":
        return {"result": "NOT_APPLICABLE", "reason": "HOLD does not create an execution policy"}
    if run.result_state == "FINANCIAL_WRITES_DISABLED":
        stored = _object(_run_json(run.evidence_timestamps).get("policy"))
        checks = {
            key: value
            for key, value in stored.items()
            if key.endswith("_result") and isinstance(value, str)
        }
        return {
            "result": "PASS",
            "reason": "deterministic policy passed before financial write closure",
            "reasonCode": "FINANCIAL_WRITES_DISABLED",
            "checks": checks,
            "computedNotional": stored.get("computed_notional")
            if isinstance(stored.get("computed_notional"), str)
            else None,
        }
    if run.result_state == "POLICY_REJECTED":
        stored = _object(_run_json(run.evidence_timestamps).get("policy"))
        raw_reason = stored.get("reason")
        reason = raw_reason if isinstance(raw_reason, str) else None
        rejected_result: dict[str, Any] = {
            "result": "REJECTED",
            "reason": _public_text(reason) if reason is not None else None,
            "reasonCode": _REASON_CODES.get(reason, "POLICY_REJECTED")
            if reason is not None
            else "POLICY_REJECTED",
            "checks": {
                key: value
                for key, value in stored.items()
                if key.endswith("_result") and isinstance(value, str)
            },
        }
        if isinstance(stored.get("computed_notional"), str):
            rejected_result["computedNotional"] = stored["computed_notional"]
        return rejected_result
    if intent is not None:
        stored = _run_json(intent.policy_evidence)
        checks = {
            key: stored.get(key)
            for key in (
                "mandate_result",
                "risk_result",
                "budget_result",
                "execution_policy_result",
            )
            if isinstance(stored.get(key), str)
        }
        reason = stored.get("reason")
        if all(value == "PASS" for value in checks.values()) and len(checks) == 4:
            result = "PASS"
        else:
            result = "REJECTED"
        return {
            "result": result,
            "reason": _public_text(reason) if isinstance(reason, str) else None,
            "reasonCode": _REASON_CODES.get(reason) if isinstance(reason, str) else None,
            "checks": checks,
            "computedNotional": stored.get("computed_notional")
            if isinstance(stored.get("computed_notional"), str)
            else None,
        }
    return {"result": "NOT_AVAILABLE", "reason": _public_text(run.rationale)}


def _system_result(
    run: AgentRun, intent: TradeIntent | None, action: str | None
) -> tuple[str, str | None]:
    if run.result_state == "FAILED":
        return "FAILED", _public_text(run.rationale or "latest scheduled run failed")
    if intent is not None:
        intent_state = intent.local_state
        if intent_state == "FILLED":
            return "EXECUTED", None
        if intent_state == "FINANCIAL_WRITES_DISABLED":
            return "SKIPPED", "FINANCIAL_WRITES_DISABLED"
        if intent_state in {"REJECTED_EXCHANGE", "EXPIRED"}:
            return "FAILED", intent_state
        if intent_state in {
            "REJECTED",
            "APPROVAL_EXPIRED",
            "REVALIDATION_FAILED",
            "REJECTED_BUDGET",
            "BLOCKED",
            "CANCELED",
        }:
            return "SKIPPED", intent_state
        if intent_state in {
            "WAITING_FOR_APPROVAL",
            "APPROVED",
            "AUTO_AUTHORIZED",
            "REVALIDATING",
            "WAITING_FOR_EXECUTION_CONFIRMATION",
            "SUBMITTING",
            "SUBMISSION_UNKNOWN",
            "OPEN",
            "PARTIALLY_FILLED",
            "CANCEL_PENDING",
            "CANCEL_BLOCKED",
        }:
            return "PENDING", intent_state
    if action == "HOLD":
        return "SKIPPED", "NO_TRADE"
    if run.result_state in {
        "POLICY_REJECTED",
        "SIGNAL_SUPPRESSED",
        "NO_EFFECTIVE_SYMBOLS",
        "EMERGENCY_STOP",
        "FINANCIAL_WRITES_DISABLED",
    }:
        return "SKIPPED", (
            "FINANCIAL_WRITES_DISABLED"
            if run.result_state == "FINANCIAL_WRITES_DISABLED"
            else run.result_state
        )
    if run.result_state in {"WAITING_FOR_APPROVAL", "AUTO_AUTHORIZED"}:
        return "PENDING", run.result_state
    return run.result_state, None


def _decision(
    run: AgentRun, private_account_values: tuple[tuple[str, str], ...]
) -> dict[str, Any]:
    raw = _run_json(run.decision)
    result: dict[str, Any] = {}
    for field in (
        "action",
        "pair",
        "order_type",
        "side",
        "quantity",
        "price",
        "rationale",
        "confidence",
    ):
        value = raw.get(field)
        if field == "rationale" and isinstance(value, str):
            result[field] = _public_text(value, private_account_values=private_account_values)
        elif isinstance(value, (str, int, float)) or value is None:
            result[field] = value
    result["supporting_factors"] = [
        _public_text(item, private_account_values=private_account_values)
        for item in _string_list(raw.get("supporting_factors"))
    ]
    result["risk_factors"] = [
        _public_text(item, private_account_values=private_account_values)
        for item in _string_list(raw.get("risk_factors"))
    ]
    return result


def _summary(
    run: AgentRun,
    intent: TradeIntent | None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    private_account_values = _private_account_values(_run_json(run.evidence_timestamps))
    decision = _decision(run, private_account_values)
    action = decision.get("action") if isinstance(decision.get("action"), str) else None
    outcome, reason = _system_result(run, intent, action)
    result: dict[str, Any] = {
        "id": run.id,
        "trigger": run.trigger_type,
        "model": run.model,
        "state": run.result_state,
        "startedAt": run.started_at,
        "completedAt": run.completed_at,
        "decision": {
            "action": decision.get("action"),
            "pair": decision.get("pair"),
            "confidence": decision.get("confidence"),
        },
        "systemOutcome": outcome,
        "reason": reason,
    }
    if evidence is not None:
        result.update(
            {
                "decision": decision,
                "rationale": decision.get("rationale"),
                "supportingFactors": decision["supporting_factors"],
                "riskFactors": decision["risk_factors"],
                "policy": _policy(run, intent, action),
                "evidence": evidence,
            }
        )
    return result


def _freshness(
    latest: AgentRun | None,
    evidence_at: datetime | None,
    agent_state: str,
    next_run_at: datetime | None,
    schedule_interval: int,
) -> tuple[str, bool, str | None]:
    if latest is None:
        return "STALE", True, "NO_COMPLETED_DECISION"
    if latest.result_state == "FAILED":
        return "STALE", True, "LATEST_RUN_FAILED"
    if evidence_at is None:
        return "STALE", True, "NO_STORED_MARKET_EVIDENCE"
    now = now_utc()
    if now - evidence_at > timedelta(seconds=max(schedule_interval * 2, 600)):
        return "STALE", True, "STORED_MARKET_EVIDENCE_IS_OLD"
    aware_next = _aware(next_run_at)
    if agent_state == "RUNNING" and aware_next is not None and aware_next < now:
        return "STALE", True, "SCHEDULE_OVERDUE"
    return "FRESH", False, None


@router.get("/api/showcase")
def showcase(db: Session = Depends(get_db)) -> dict[str, Any]:
    settings = get_settings()
    if (
        not settings.public_showcase_enabled
        or settings.demo_mode
        or settings.financial_writes_enabled
    ):
        raise HTTPException(status_code=404, detail="public showcase is disabled")

    repo = Repository(db)
    config = db.scalar(select(AgentConfig).limit(1))
    if config is None:
        raise HTTPException(status_code=404, detail="public showcase state is unavailable")
    mandate = repo.current_mandate()
    runs = list(
        db.scalars(
            select(AgentRun)
            .where(
                AgentRun.trigger_type.in_(_DECISION_TRIGGERS),
                AgentRun.completed_at.is_not(None),
            )
            .order_by(AgentRun.started_at.desc())
            .limit(20)
        ).all()
    )
    latest = runs[0] if runs else None
    intents = {
        intent.agent_run_id: intent
        for intent in db.scalars(
            select(TradeIntent).where(TradeIntent.agent_run_id.in_([run.id for run in runs]))
        ).all()
    }
    latest_evidence_raw = _run_json(latest.evidence_timestamps) if latest is not None else {}
    latest_evidence = _safe_evidence(latest_evidence_raw)
    latest_intent = intents.get(latest.id) if latest is not None else None
    last_evidence_at = _evidence_timestamp(latest_evidence_raw) if latest is not None else None
    freshness, stale, stale_reason = _freshness(
        latest,
        last_evidence_at,
        config.state,
        config.next_run_at,
        config.schedule_interval,
    )
    allowed_symbols: list[str] = []
    if mandate is not None:
        allowed_symbols = _string_list(_json_value(mandate.allowed_symbols))
    latest_summary = (
        _summary(latest, latest_intent, latest_evidence) if latest is not None else None
    )
    recent = [
        _summary(run, intents.get(run.id))
        for run in runs
    ]
    state = "AVAILABLE" if latest is not None and not stale else "STALE"
    return {
        "showcaseState": state,
        "demoMode": settings.demo_mode,
        "financialWritesEnabled": settings.financial_writes_enabled,
        "executionMode": config.mode,
        "agentState": config.state,
        "emergencyStop": config.emergency_stop,
        "configuredUniverse": list(parse_supported_symbols(config.supported_symbols)),
        "allowedSymbols": allowed_symbols,
        "effectiveUniverse": latest_evidence["pairSelection"]["effectiveSymbols"],
        "mandate": _public_text(repo.mandate_text(mandate)) if mandate is not None else None,
        "lastDecisionAt": latest.completed_at if latest is not None else None,
        "lastEvidenceAt": last_evidence_at,
        "freshness": freshness,
        "stale": stale,
        "staleReason": stale_reason,
        "latestDecision": latest_summary,
        "recentDecisions": recent,
    }
