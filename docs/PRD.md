# DARWIN product contract

Give DARWIN a trading mandate and hard risk boundaries. DARWIN decides what,
when, and how to trade within those limits.

DARWIN is an autonomous Binance Spot decision and execution runtime. It monitors
current market and account evidence, creates bounded trade intents, and supports
an autonomous path without per-order human approval.

## Required product

One owner configures one high-level Spot Trading Mandate, a small structured
execution policy, a rolling 24-hour BUY budget, and an operating mode. DARWIN
produces typed BUY, SELL, or HOLD decisions. BUY/SELL become durable
`TradeIntent` records. `AUTO_BOUNDED` executes through the bounded Spot API;
`HUMAN_APPROVAL` is the secondary supervised alternative.

## Configuration model

The Trading Mandate is one required free-text field containing high-level
trading objectives and preferences. It is strategy context for DARWIN and is
never execution authority. The owner does not need to define separate assets,
entry rules, sizing rules, exit rules, or exact trading logic.

The hard backend guardrails are separate:

- `allowed_symbols` is the exact owner-configured symbol allowlist;
- `max_order_notional` is the maximum USDT notional for one trade;
- `max_open_actionable_intents` is the maximum concurrent active trade workflow
  count, not an open-position count;
- the rolling 24-hour BUY budget is stored separately in `BudgetVersion`;
- the configured Spot universe is persisted separately in
  `AgentConfig.supported_symbols`, bootstrapping to `BTCUSDT`, `ETHUSDT`,
  `BNBUSDT`, `SOLUSDT`, and `XRPUSDT`;
- emergency stop remains backend-authoritative.

Effective symbols are the intersection of the configured universe, allowed
symbols, and currently valid Binance Spot/USDT metadata with required filters.
Configured symbols do not automatically authorize trading. DARWIN scans every
effective symbol with 10 closed `15m` and `1h` candles before pair selection,
then fetches 48 closed candles for `15m`, `1h`, and `4h` only for the selected
pair. The five-symbol bootstrap is not a runtime scan limit or top-five strategy.

## Authority model

- Trading Mandate text is strategy context only.
- The model chooses the pair, BUY/SELL/HOLD action, quantity, order type, LIMIT
  price when applicable, rationale, confidence, supporting factors, and risk
  factors.
- Structured symbols, notional, concurrency, budget, balances, filters,
  freshness, open-order conflict, emergency stop, and execution authorization
  remain deterministic backend authority.
- `AUTO_BOUNDED` uses `AUTO_POLICY` authorization and does not require per-order
  Telegram approval.
- `HUMAN_APPROVAL` creates a supervised proposal and uses the approval flow.
- BUY acquires a Spot asset. SELL sells a Spot asset already held by the
  account. SELL is not a short-opening operation.
- Futures, margin, leverage, transfers, withdrawals, and options are outside
  DARWIN execution scope.

## Modes

- `AUTO_BOUNDED`: the primary autonomous path using the same deterministic
  policy, account lock, fresh revalidation, idempotency, and reconciliation
  flow, then the narrow backend-only Binance Spot API.
- `HUMAN_APPROVAL`: the secondary supervised path using operator authorization,
  fresh revalidation, and Codex Agent OS MCP transport.

Both modes are bounded by the configured Spot universe, allowed symbols,
USDT-only Spot metadata, maximum notional, concurrent workflow limit, rolling
BUY budget, balances, filters, open-order conflict, freshness, and emergency
stop.

DARWIN reasons from current ticker/account/order evidence plus real typed
CLOSED Binance Spot OHLCV. Candidate scanning uses 10 closed candles each for
`15m` and `1h` across every effective symbol; detailed reasoning uses 48 closed
candles each for `15m`, `1h`, and `4h` only for the selected pair. Historical
bars inform BUY/SELL/HOLD reasoning, do not authorize trades, exclude the
currently forming candle, and do not guarantee trend prediction.

Candidate history failures exclude only the affected symbol and are retained as
sanitized structured logs plus original-cycle `pair_selection` evidence; they do
not create child `AgentRun` rows. If every candidate fails validation, pair
selection is skipped and the cycle returns a fail-closed no-candidate result.

## State and safety

Approval is single-use with a backend TTL default of 90 seconds and bounds of
30..180 seconds. Telegram callback data is only an opaque approval reference.
The same durable approval state machine serves Telegram and web fallback.

`APPROVAL_EXPIRED` means the operator decision window expired. Binance exchange
`EXPIRED` remains an exchange-order terminal state. `SUBMISSION_UNKNOWN` always
reconciles before retry. One account cannot perform concurrent ordinary writes.

Emergency stop is the only special operator-command cancellation path. Model
CANCEL/CANCEL_REPLACE, direct web cancellation, transfers, withdrawals, futures,
margin, leverage, and options are unsupported or disabled.

## Verification status

```text
Codex/Binance transport implementation: IMPLEMENTED
Authenticated live bridge verification: PENDING
Production readiness: PARTIALLY VERIFIED
```

Manual operator verification is required for genuine Codex OAuth, authenticated
MCP status/tool inventory, harmless structured reads, and the real write
confirmation contract. The first write confirmation must be declined and proven
to create zero trade.
