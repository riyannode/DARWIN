# DARWIN JUDGE DEMO

The root Compose runtime is a deterministic, zero-credential judge walkthrough. It is not paper trading, a Binance session, or a production deployment.

## Run

Requirements: Git, Docker Engine, and Docker Compose v2.

```bash
git clone https://github.com/riyannode/DARWIN.git
cd DARWIN
docker compose up --build
```

Open [http://localhost:3000/demo](http://localhost:3000/demo).

Reset the demo's named volume and containers when finished:

```bash
docker compose down -v --remove-orphans
```

## Runtime contract

The checked-in `docker-compose.yml` explicitly sets:

```dotenv
DATABASE_URL=sqlite:////data/darwinspot.db
DEMO_MODE=true
FINANCIAL_WRITES_ENABLED=false
PUBLIC_SHOWCASE_ENABLED=false
```

It runs `alembic upgrade head`, starts FastAPI, waits for `/health/live`, and starts the frontend with its server-side `BACKEND_URL` pointed at the Compose backend.

The demo uses deterministic Binance-format fixtures and deterministic model decisions. It does **not** require or use:

- a `.env` file;
- an OpenAI or OpenAI-compatible provider key;
- Binance credentials, a funded account, or a Binance connection;
- Codex, Binance Agent OS OAuth, or Telegram; or
- the scheduled worker.

`DEMO_MODE=true` blocks financial writes at shared submission, approved-execution, emergency-cancellation, direct Binance Spot API, and Codex/Agent OS write seams. Demo requests do not create `AgentRun` or `TradeIntent` rows.

## Routes and scenarios

| Route | Behavior |
| --- | --- |
| `GET /api/demo` | demo metadata and scenario summaries |
| `GET /api/demo/scenarios` | all scenario summaries |
| `GET /api/demo/scenarios/valid-buy` | policy-passing BUY, blocked before execution |
| `GET /api/demo/scenarios/max-notional` | over-limit BUY, policy rejected |
| `GET /api/demo/scenarios/hold` | HOLD, no intent |

| Scenario | Decision | Policy | System outcome |
| --- | --- | --- | --- |
| `valid-buy` | `BUY BTCUSDT` | `PASS` | `SKIPPED / DEMO_EXECUTION_BLOCKED` |
| `max-notional` | `BUY SOLUSDT` | `REJECTED / MAX_ORDER_NOTIONAL` | `SKIPPED` |
| `hold` | `HOLD ETHUSDT` | `NOT_APPLICABLE` | `SKIPPED / NO_TRADE` |

`BUY`, `SELL`, and `HOLD` are model decisions. `SKIPPED` is a system outcome; a demo BUY is never an executed order.

## What judges can inspect

- Trading Mandate and Configured/Allowed/Effective Universe presentation;
- typed decision evidence, confidence, rationale, supporting factors, and risk factors;
- candidate scan, selected-pair closed OHLCV evidence, and deterministic policy evaluation;
- budget, balance, filter, and concurrency checks; and
- explicit no-write semantics.

## Evidence status

- **IMPLEMENTED BUT NOT VERIFIED by a fresh runtime/browser exercise in this documentation-only review:** Docker JUDGE DEMO, the port-3000 `/demo` path, demo API scenarios, zero-row financial-write proof, and Chromium rendering for `/demo`.
- **NOT VERIFIED by this demo:** external LLM inference, Binance connectivity/authentication, Binance Agent OS/Codex OAuth, order submission, reconciliation against a funded account, or a funded live order.

For safe live evidence rather than fixtures, see [LIVE.md](LIVE.md) and the optional PUBLIC LIVE SHOWCASE profile at `/showcase`.
