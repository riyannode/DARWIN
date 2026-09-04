# DARWIN submission copy

## One-line description

DARWIN is a 24/7 autonomous Binance Spot trading agent. The owner provides a
high-level Trading Mandate and hard risk boundaries; DARWIN decides what, when,
and how to trade within those limits.

## Short description

DARWIN continuously monitors current market and account evidence, asks its own
`AgentRuntime` for typed BUY/SELL/HOLD decisions, applies deterministic symbol,
risk, budget, exposure, and exchange-filter checks, and creates durable
`TradeIntent` records. `AUTO_BOUNDED` is the primary autonomous execution path
and does not require per-order human approval. `HUMAN_APPROVAL` is the secondary
supervised alternative.

DARWIN owns the autonomous strategy context, policy, budget, intent lifecycle,
approval, idempotency, execution gating, reconciliation, emergency stop, and
audit evidence. Codex is only the supported Binance OAuth identity and MCP
transport for HUMAN_APPROVAL. DARWIN sends no natural-language trading prompt to
Codex, and Codex never chooses trades.

## Configuration and authority

The owner configures one Trading Mandate, exact allowed symbols, Max Per Trade,
Max Concurrent Trades, a rolling 24-hour BUY budget, and an execution mode.
Configured Spot Universe and Emergency Stop remain separate backend controls.
The Trading Mandate is strategy context only and is never authorization.

BUY acquires a Spot asset. SELL sells a Spot asset already held by the account;
SELL does not open a short position. Futures, margin, leverage, transfers,
withdrawals, and options are outside DARWIN execution scope.

## Safety claims

- `AUTO_BOUNDED` uses `AUTO_POLICY` authorization and does not bypass
  deterministic policy, account locking, or fresh revalidation.
- `HUMAN_APPROVAL` requires explicit operator approval before ordinary writes.
- Allowed symbols, configured universe, per-trade notional, concurrent workflow
  count, rolling BUY budget, balances, filters, freshness, open-order conflict,
  and emergency stop remain backend-authoritative.
- Telegram callbacks contain only opaque `approval_id` references.
- Rejected, expired, stale, policy-failed, or unauthenticated paths perform no
  financial write.
- Binance/Codex confirmation is never auto-answered.
- Transfers and withdrawals are unsupported and fail closed.

## Evidence scope

DARWIN reasons from current ticker, account, order, and filter snapshots plus
real typed CLOSED Binance Spot OHLCV: 48 candles each for 15m, 1h, and 4h.
The bounded historical bars inform model reasoning but do not authorize trades
or guarantee trend prediction. Their newest closed candle must be no more than
two interval periods old; the currently forming candle is excluded.

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
3. Configure one Trading Mandate, hard guardrails, budget, and mode.
4. Show the 24/7 monitoring/decision architecture.
5. In `AUTO_BOUNDED`, show an autonomous signal and bounded execution path
   without per-order approval.
6. In `HUMAN_APPROVAL`, show a supervised proposal and fresh revalidation.
7. Decline the first transport confirmation and show zero trade.

## Replication

See [RUNBOOK.md](RUNBOOK.md), [DEPLOYMENT.md](DEPLOYMENT.md), and
[ARCHITECTURE.md](ARCHITECTURE.md). No hosted URL is claimed by this repository.
