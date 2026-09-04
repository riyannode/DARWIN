# DarwinSpot submission copy

## One-line description

DARWIN is a 24/7 autonomous Binance Agent OS decision and risk runtime with
HUMAN_APPROVAL and AUTO_BOUNDED execution modes sharing one agent and policy
pipeline.

## Short description

DARWIN continuously monitors market and account evidence, asks its own
`AgentRuntime` for typed BUY/SELL/HOLD decisions, applies deterministic mandate,
risk, budget, exposure, and exchange-filter checks, and creates durable
`TradeIntent` proposals. Telegram is the primary operator approval surface;
the existing web UI is a fallback. Approve always triggers fresh revalidation
before any exact Binance write.

DARWIN owns the autonomous strategy, policy, budget, intent lifecycle,
approval, idempotency, execution gating, reconciliation, emergency stop, and
audit evidence. Codex is only the supported Binance OAuth identity and MCP
transport. DARWIN sends no natural-language trading prompt to Codex, and Codex
never chooses trades.

## Safety claims

- `HUMAN_APPROVAL` requires explicit operator approval before ordinary writes.
- `AUTO_BOUNDED` is bounded autonomous Spot execution through the direct API;
  it does not bypass deterministic policy or fresh revalidation.
- Telegram callbacks contain only opaque `approval_id` references.
- Rejected, expired, stale, policy-failed, or unauthenticated paths perform no
  financial write.
- Binance/Codex confirmation is never auto-answered.
- Emergency-stop cancellation is an explicit operator-command path and remains
  reconciliation-backed.
- Transfers and withdrawals are unsupported and fail closed.

## Verification status

```text
Codex/Binance transport implementation: IMPLEMENTED
Authenticated live bridge verification: PENDING
Production readiness: PARTIALLY VERIFIED
```

Manual verification remains operator-owned:

1. genuine Codex/Binance OAuth;
2. authenticated `mcpServerStatus/list`;
3. populated Binance tools;
4. exact harmless read-only tool call and structured result;
5. observed write confirmation/elicitation;
6. decline the first write confirmation and prove zero trade.

Telegram has no official sandbox. Use a dedicated test bot/private chat for real
Bot API verification. No funded trade is required for the initial acceptance.

## Demo flow

1. Start DARWIN safely before Binance authentication.
2. Show `AUTH_REQUIRED`/`UNVERIFIED` Codex state.
3. Configure the four-part mandate, structured policy, budget, and mode.
4. Show the 24/7 monitoring/decision architecture.
5. Show a bounded Telegram proposal with rationale and risk/budget status.
6. Reject or allow expiry and show zero write.
7. Approve a proposal, show fresh revalidation, and reach the real confirmation
   boundary after manual transport verification.
8. Decline the first confirmation and show zero trade.

## Replication

See [RUNBOOK.md](RUNBOOK.md), [DEPLOYMENT.md](DEPLOYMENT.md), and
[ARCHITECTURE.md](ARCHITECTURE.md). No hosted URL is claimed by this repository.
