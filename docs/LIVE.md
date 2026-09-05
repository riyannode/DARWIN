# DARWIN Live installation and profiles

This guide covers provider-backed operation. For the isolated, zero-credential walkthrough, use [DEMO.md](DEMO.md).

## Requirements declared by the repository

- Python `>=3.14,<3.15` and `uv` (`backend/pyproject.toml`)
- PostgreSQL for live durable state
- pnpm `11.25.0` (`frontend/package.json`)
- a Node.js version supported by the pinned Next.js `16.3.4`; the repository does not declare an `engines` field
- Codex App Server only for `HUMAN_APPROVAL`

## Install locked dependencies

```bash
git clone https://github.com/riyannode/DARWIN.git
cd DARWIN

cd backend
uv sync --frozen
cp .env.example .env

cd ../frontend
pnpm install --frozen-lockfile
```

Keep `backend/.env` backend-only and untracked. Do not put credentials in frontend environment variables.

## Profiles

### JUDGE DEMO

```dotenv
DEMO_MODE=true
FINANCIAL_WRITES_ENABLED=false
PUBLIC_SHOWCASE_ENABLED=false
```

Use `docker compose up --build`. This profile uses synthetic fixtures, no external LLM, no Binance connection, and no financial writes.

### PUBLIC LIVE SHOWCASE

```dotenv
DEMO_MODE=false
FINANCIAL_WRITES_ENABLED=false
PUBLIC_SHOWCASE_ENABLED=true
```

The worker creates real model/market decision evidence. Public `/showcase` projects stored evidence without private balances. A policy-passing BUY/SELL ends as `FINANCIAL_WRITES_DISABLED` before an intent, approval, or financial transport call. It does not create a Binance order.

### REAL LIVE TRADING

```dotenv
DEMO_MODE=false
FINANCIAL_WRITES_ENABLED=true
PUBLIC_SHOWCASE_ENABLED=false
```

This profile makes possible financial writes only after deterministic authorization, the mode-specific authorization flow, fresh revalidation, and reconciliation safeguards. It does not imply funded-live acceptance has occurred.

## Common live configuration

Set these values in `backend/.env` for a ready live API:

```dotenv
DEMO_MODE=false
FINANCIAL_WRITES_ENABLED=false
PUBLIC_SHOWCASE_ENABLED=false
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
OPENAI_API_KEY=<backend-only provider key>
OPENAI_MODEL=gpt-5.4-mini
OWNER_PASSWORD_HASH=<Argon2id hash>
FRONTEND_ORIGIN=https://your-real-frontend.example
```

`OPENAI_BASE_URL` is optional. Omit it for direct OpenAI, or set an absolute HTTP(S) OpenAI-compatible endpoint without embedded credentials, query, or fragment.

The worker also requires a nonempty `CODEX_APP_SERVER_COMMAND`; the repository default is:

```dotenv
CODEX_APP_SERVER_COMMAND="codex app-server --stdio"
CODEX_APP_SERVER_VERSION=0.153.0
```

The command is only used as a transport process by HUMAN_APPROVAL. `AGENT_CYCLE_SECONDS` defaults to `300`; `SIGNAL_COOLDOWN_SECONDS` defaults to `300`; `APPROVAL_TTL_SECONDS` defaults to `90` and is bounded to 30–180 seconds.

### AUTO_BOUNDED configuration

```dotenv
BINANCE_API_KEY=<dedicated backend-only Spot key>
BINANCE_API_SECRET=<dedicated backend-only Spot secret>
BINANCE_SPOT_API_BASE_URL=https://api.binance.com
BINANCE_RECV_WINDOW_MS=5000
BINANCE_ACCOUNT_LOCK_KEY=darwinspot-binance-account
```

The direct adapter accepts only approved Binance HTTPS API hosts. Use a dedicated Spot-only key, disable withdrawals, avoid Futures/Margin/transfer permissions, restrict by IP where supported, and keep the credentials server-side. `TOKEN_ENCRYPTION_KEY` is not required for AUTO_BOUNDED API readiness.

### HUMAN_APPROVAL configuration

```dotenv
BINANCE_AGENT_OS_MCP_URL=https://agent.binance.com/mcp/agentic
BINANCE_AGENT_OS_TRANSPORT=codex
CODEX_APP_SERVER_COMMAND="codex app-server --stdio"
CODEX_APP_SERVER_VERSION=0.153.0
CODEX_WRITE_CONFIRMATION_VERIFIED=false
TOKEN_ENCRYPTION_KEY=<Fernet key for persisted Agent OS/OAuth material>
```

Use the genuine Codex-managed Binance Agent OS authorization flow. Keep `CODEX_WRITE_CONFIRMATION_VERIFIED=false` until an operator has observed the real write confirmation contract. A successful setting does not prove the operator is authenticated.

### Optional Telegram

Configure all four values or none:

```dotenv
TELEGRAM_BOT_TOKEN=<backend-only bot token>
TELEGRAM_OPERATOR_CHAT_ID=<exact operator chat id>
TELEGRAM_OPERATOR_USER_ID=<exact operator user id>
TELEGRAM_WEBHOOK_SECRET=<webhook secret>
```

Telegram can deliver HUMAN_APPROVAL proposals and notifications. The same approval state machine is available via authenticated web approval. Telegram is never per-order authorization for AUTO_BOUNDED.

## Migrate and run

The repository Alembic head is `0006_canonical_trading_mandate`.

```bash
cd backend
PYTHONPATH=src uv run alembic upgrade head
```

API:

```bash
cd backend
PYTHONPATH=src uv run uvicorn darwinspot.main:app --host 0.0.0.0 --port 8000
```

Worker, in a separate process/service:

```bash
cd backend
PYTHONPATH=src uv run python -m darwinspot.worker
```

Frontend:

```bash
cd frontend
BACKEND_URL=http://127.0.0.1:8000 pnpm build
HOSTNAME=0.0.0.0 PORT=3000 pnpm start
```

`BACKEND_URL` is server-only and drives Next.js `/api/:path*` rewrites. `FRONTEND_ORIGIN` is the exact browser origin used for CORS, mutation-origin checks, cookies, and Agent OS callback URLs.

## Health

```bash
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
curl -i http://127.0.0.1:8000/docs
```

`/health/ready` returns 503 in live mode until the owner hash, model key, and mode-dependent transport requirements are present. It is configuration readiness, not funded-order acceptance.

## Current evidence

| Claim | Status |
| --- | --- |
| Demo Docker runtime, all demo scenarios, and zero durable demo rows | **VERIFIED** in a fresh non-financial Compose run |
| Chromium `/demo` rendering and scenario selection | **VERIFIED** in the same fresh run |
| Public-enabled `/showcase` Chromium rendering | **NOT VERIFIED** in this run |
| Live configuration, worker, mode transport, and safety implementation | **IMPLEMENTED** |
| Funded AUTO_BOUNDED execution | **NOT VERIFIED** |
| Authenticated HUMAN_APPROVAL Codex/Binance Agent OS acceptance | **PENDING / NOT VERIFIED** |

Do not use documentation verification as a reason to submit a funded order, withdrawal, transfer, or live transport confirmation.
