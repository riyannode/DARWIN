# Demo Mode

Demo Mode is a deterministic judge walkthrough, not a paper-trading claim and
not a live Binance session.

## Runtime contract

The root Compose path sets `DEMO_MODE=true`, runs the existing Alembic schema
against local SQLite, and starts the existing backend/frontend pair. No
credentials are required.

The backend demo runner builds fixed Binance-format market payloads, sends them
through the existing typed mappers and closed-candle models, computes the
configured/allowed/effective universe, creates a validated `AgentDecision`, and
runs the existing deterministic execution policy and budget calculation.

Demo replaces only external providers that cannot be called without credentials:

- fixed market fixtures replace public/live market reads;
- deterministic pair selection replaces the live decision provider;
- fixed account, open-order, recent-activity, and filter snapshots replace
  authenticated account reads.

The existing production components reused by Demo Mode are:

- `map_candidate_market_history` and `map_market_history`;
- `MarketCandle` and market snapshot models;
- `effective_symbols`;
- `AgentDecision` validation;
- `ExecutionPolicy` and `evaluate_execution_policy`;
- rolling budget calculation;
- the backend financial write guard.

## Read-only endpoints

When `DEMO_MODE=true`:

```text
GET /api/demo
GET /api/demo/scenarios
GET /api/demo/scenarios/valid-buy
GET /api/demo/scenarios/max-notional
GET /api/demo/scenarios/hold
```

No demo route creates an intent, submits an order, cancels an order, transfers
funds, or withdraws funds.

## Required scenarios

- `valid-buy`: `BUY BTCUSDT`, policy `PASS`, system outcome `SKIPPED`, reason
  `DEMO_EXECUTION_BLOCKED`.
- `max-notional`: `BUY SOLUSDT`, policy rejection from the real policy evaluator,
  system outcome `SKIPPED`, reason `MAX_ORDER_NOTIONAL`.
- `hold`: `HOLD ETHUSDT`, no intent, system outcome `SKIPPED`, reason `NO_TRADE`.

The API exposes model decision and system outcome as separate fields. `SKIPPED`
is never an `AgentDecision.action`.

## Safety barrier

`DemoFinancialWriteBlocked` is raised by the shared demo guard when
`DEMO_MODE=true`. It is checked before:

- shared order submission;
- approved execution submission;
- emergency cancellation;
- direct Binance Spot `post_order` and `delete_order` calls;
- Codex/Agent OS tools classified as financial writes.

`DEMO_MODE=false` leaves the live transport behavior unchanged.

## Proof boundary

Demo proves:

- mandate and universe presentation;
- typed evidence mapping and decision schema;
- deterministic policy, budget, balance, filter, and concurrency evaluation;
- explicit no-write outcome semantics;
- inspectable evidence and product UX.

Demo does not prove:

- live OpenAI or OpenAI-compatible inference;
- live Binance authentication or market connectivity;
- Codex OAuth or Agent OS MCP behavior;
- live order submission, reconciliation, or funded-account execution.
