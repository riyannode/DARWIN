# DARWIN Demo Mode

Demo Mode is the deterministic judge walkthrough. It is not paper trading and
not a live Binance session.

## Requirements

- Git
- Docker Engine
- Docker Compose v2+

## Install and run

```bash
git clone https://github.com/riyannode/DARWIN.git
cd DARWIN
docker compose up --build
```

Open:

```text
http://localhost:3000/demo
```

No `.env` is required.

## Stop and reset

```bash
docker compose down -v --remove-orphans
```

## Runtime contract

The root `docker-compose.yml` is the safe JUDGE/DEMO runtime. It is **not** the
production live-trading deployment.

Compose sets `DEMO_MODE=true`, runs the existing Alembic schema against local
SQLite, and starts the existing backend/frontend pair. It uses deterministic
synthetic Binance-format fixtures and does not use a model provider, live
Binance authentication, Codex, Telegram, or a funded account.

The backend financial-write guard blocks new orders, cancellations, transfers,
and withdrawals before an execution transport can be reached. No demo route
creates an intent, submits an order, or writes financial state.

## Read-only endpoints

When `DEMO_MODE=true`:

```text
GET /api/demo
GET /api/demo/scenarios
GET /api/demo/scenarios/valid-buy
GET /api/demo/scenarios/max-notional
GET /api/demo/scenarios/hold
```

## Required scenarios

- `valid-buy`: `BUY BTCUSDT`, policy `PASS`, system outcome `SKIPPED`, reason
  `DEMO_EXECUTION_BLOCKED`.
- `max-notional`: `BUY SOLUSDT`, policy field `REJECTED` (policy-rejected),
  system outcome `SKIPPED`, reason `MAX_ORDER_NOTIONAL`.
- `hold`: `HOLD ETHUSDT`, no intent, system outcome `SKIPPED`, reason
  `NO_TRADE`.

The API exposes the model decision and system outcome as separate fields.
`SKIPPED` is never an `AgentDecision.action`.

## What the demo proves

- mandate and effective-universe presentation;
- typed evidence mapping and decision schema;
- deterministic policy, budget, balance, filter, and concurrency evaluation;
- explicit no-write outcome semantics;
- inspectable evidence and product UX.

## What the demo does not prove

- live OpenAI or OpenAI-compatible inference;
- live Binance authentication or market connectivity;
- Codex OAuth or Agent OS MCP behavior;
- live order submission, reconciliation, or funded-account execution.

## Verification status

The Docker judge runtime and exact localhost port-3000 path are VERIFIED. Judge-facing
Chromium rendering for `/demo` and public-enabled `/showcase` is VERIFIED. Full
operator/control-room browser acceptance remains NOT CLAIMED. No live funded order
or authenticated Codex/Binance write acceptance has been performed.
