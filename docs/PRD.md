# DARWIN product contract

DARWIN is an autonomous Binance Agent OS decision and risk runtime. It monitors
markets and account state continuously, creates bounded trade intents, and routes
execution through explicit human approval.

## Required product

One owner configures one Spot trading mandate, a small structured execution
policy, a rolling 24-hour buy budget, and an operating mode. DARWIN continuously
collects evidence and produces typed BUY, SELL, or HOLD decisions. BUY/SELL
become durable `TradeIntent` proposals and Telegram signals. No unattended
monetary execution is allowed.

## Authority model

- Free-text assets/entry/sizing/exit sections are strategy context for DARWIN.
- Structured `allowed_symbols`, `max_order_notional`, and
  `max_open_actionable_intents` are deterministic backend authority.
- Budget, balances, exchange filters, freshness, open-order exposure, and
  emergency stop are deterministic execution gates.
- Telegram APPROVE authorizes revalidation, not a stale payload.
- Codex provides supported Binance OAuth identity and MCP transport only.
- Binance/Codex confirmation is never auto-answered.

## Modes

- `READ_ONLY`: analyze and display live evidence without proposals/writes.
- `APPROVAL_REQUIRED`: create durable proposals requiring operator approval.
- `AUTO_BOUNDED`: monitor, analyze, decide, and signal autonomously; every
  ordinary Binance write still requires explicit approval.

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
