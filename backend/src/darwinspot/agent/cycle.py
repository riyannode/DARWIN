from __future__ import annotations

from typing import Any

from darwinspot.agent.runtime import AgentRuntime
from darwinspot.binance.client import (
    AgentOSAuthInvalid,
    AgentOSUnavailable,
    BinanceAgentOSClient,
    ToolCatalog,
    UnsupportedCapability,
)
from darwinspot.binance.mapper import (
    BinanceMappingError,
    OrderCorrelationError,
    map_order_submission,
    order_submission_evidence,
    validate_order_submission_correlation,
)
from darwinspot.execution.orders import SubmissionBlocked
from darwinspot.observability import log_event
from darwinspot.storage.models import TradeIntent
from darwinspot.storage.repository import Repository


class CycleUnavailable(RuntimeError):
    pass


class CycleConfigurationError(CycleUnavailable):
    pass


class SubmissionUncertain(AgentOSUnavailable):
    pass


async def run_cycle(
    repo: Repository, client: BinanceAgentOSClient, runtime: AgentRuntime, run_id: str
) -> str:
    from darwinspot.agent.decision_cycle import DecisionCycle

    return await DecisionCycle().run(repo, client, runtime, run_id)


async def submit_intent(
    repo: Repository, client: Any, catalog: ToolCatalog, intent: TradeIntent
) -> str:
    upstream: Any = None
    try:
        repo.ensure_submission_allowed()
        submission_call = catalog.arguments("submit_order", {"intent": intent})
        upstream = await client.call_tool(submission_call)
        submission = map_order_submission(upstream)
        validate_order_submission_correlation(
            upstream,
            submission=submission,
            expected_symbol=intent.pair,
            expected_client_order_id=intent.idempotency_key,
            expected_side=intent.side,
        )
    except SubmissionBlocked:
        raise
    except UnsupportedCapability:
        raise
    except AgentOSAuthInvalid as exc:
        _record_submission_unknown(repo, intent, upstream, exc)
        raise
    except (AgentOSUnavailable, BinanceMappingError, TimeoutError) as exc:
        _record_submission_unknown(repo, intent, upstream, exc)
        raise SubmissionUncertain("order submission outcome is uncertain") from exc
    repo.apply_order_status(
        intent,
        order_id=submission.order_id,
        status=submission.status,
        filled_quantity=submission.executed_quantity,
        filled_notional=submission.quote_notional,
        exchange_timestamp=submission.updated_at,
        evidence=order_submission_evidence(
            upstream,
            intent_id=intent.id,
            client_order_id=intent.idempotency_key,
            submission=submission,
        ),
    )
    repo.db.commit()
    return intent.local_state


def _record_submission_unknown(
    repo: Repository, intent: TradeIntent, upstream: Any, error: BaseException
) -> None:
    intent.local_state = "SUBMISSION_UNKNOWN"
    repo.record_order_event(
        intent=intent,
        event_type="SUBMISSION_FAILED",
        filled_quantity=None,
        filled_notional=None,
        exchange_timestamp=None,
        evidence=order_submission_evidence(
            upstream,
            intent_id=intent.id,
            client_order_id=intent.idempotency_key,
            error=error,
        ),
    )
    repo.db.commit()
    log_event(
        "ORDER_SUBMIT_UNKNOWN",
        intent_id=intent.id,
        pair=intent.pair,
        error_code=type(error).__name__,
    )


async def reconcile_open_intents(repo: Repository, client: Any) -> None:
    intents = [
        intent
        for intent in repo.non_terminal_intents()
        if intent.local_state
        in {"SUBMITTING", "SUBMISSION_UNKNOWN", "OPEN", "PARTIALLY_FILLED", "CANCEL_PENDING"}
    ]
    if not intents:
        return
    try:
        catalog = ToolCatalog(await client.discover_tools())
    except (AgentOSUnavailable, ValueError) as exc:
        log_event("RECONCILIATION_FAILED", reason=str(exc))
        raise
    for intent in intents:
        try:
            raw = await client.call_tool(
                catalog.arguments(
                    "order_status",
                    {
                        "symbol": intent.pair,
                        "order_id": intent.binance_order_id,
                        "client_order_id": intent.idempotency_key,
                    },
                )
            )
            status = map_order_submission(raw)
            validate_order_submission_correlation(
                raw,
                submission=status,
                expected_symbol=intent.pair,
                expected_client_order_id=intent.idempotency_key,
                expected_side=intent.side,
            )
            repo.apply_order_status(
                intent,
                order_id=status.order_id,
                status=status.status,
                filled_quantity=status.executed_quantity,
                filled_notional=status.quote_notional,
                exchange_timestamp=status.updated_at,
                evidence=order_submission_evidence(
                    raw,
                    intent_id=intent.id,
                    client_order_id=intent.idempotency_key,
                    submission=status,
                ),
            )
        except UnsupportedCapability:
            raise
        except AgentOSAuthInvalid:
            raise
        except OrderCorrelationError as exc:
            log_event("RECONCILIATION_FAILED", intent_id=intent.id, reason=str(exc))
            raise SubmissionUncertain(
                "order reconciliation response did not match the intent"
            ) from exc
        except (AgentOSUnavailable, BinanceMappingError, ValueError) as exc:
            log_event("RECONCILIATION_FAILED", intent_id=intent.id, reason=str(exc))
            raise SubmissionUncertain("order reconciliation is temporarily unavailable") from exc
    repo.db.commit()
