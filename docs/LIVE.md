# DARWIN LIVE Installation and Runtime Profiles

This document covers the real provider-backed deployment and the public
read-only showcase. Do not use the public showcase as an operator control room;
use [DEMO.md](DEMO.md) for the zero-credential judge path.

## Runtime profiles

### JUDGE DEMO

```dotenv
DEMO_MODE=true
FINANCIAL_WRITES_ENABLED=false
PUBLIC_SHOWCASE_ENABLED=false
```

Synthetic fixtures, zero credentials, no external LLM, no live Binance reads, and
financial writes blocked. The root Compose path serves `/demo`.

### PUBLIC LIVE SHOWCASE

```dotenv
DEMO_MODE=false
FINANCIAL_WRITES_ENABLED=false
PUBLIC_SHOWCASE_ENABLED=true
```

Real LLM inference, real public Binance market evidence, real scheduled worker
cycles, persisted AgentRun decisions, and public read-only `/showcase`. A full
`AUTO_BOUNDED` cycle also requires authenticated Binance account reads; the
public projection intentionally excludes private balances. No real financial
write is allowed; a policy-passing BUY/SELL completes the cycle as a local
`FINANCIAL_WRITES_DISABLED` safe-live outcome before any intent or proposal is
created. No owner login is required for `/showcase`.

### REAL LIVE TRADING

```dotenv
DEMO_MODE=false
FINANCIAL_WRITES_ENABLED=true
PUBLIC_SHOWCASE_ENABLED=false
```

Recommended operator profile. Financial execution may proceed only through the
existing policy, budget, emergency-stop, HUMAN_APPROVAL/Codex confirmation,
revalidation, idempotency, and transport gates. This repository does not claim
funded E2E verification.

## Requirements

- Git
- Python 3.14.x
- `uv`
- Node.js compatible with the current frontend package
- pnpm 11 (`pnpm 11.25.0` is locked by this repository)
- PostgreSQL
- Codex CLI/App Server only for `HUMAN_APPROVAL`

## Fresh installation

Clone the repository and install the locked dependencies:

```bash
git clone https://github.com/riyannode/DARWIN.git
cd DARWIN

cd backend
uv sync --frozen
cp .env.example .env

cd ../frontend
pnpm install --frozen-lockfile
```

Set the backend environment in `backend/.env` before starting live processes.
Keep the file backend-only with restrictive permissions, and never commit it.

## Database and backend processes

Use a PostgreSQL URL in `backend/.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
```

Run migrations from `backend/`:

```bash
cd backend
PYTHONPATH=src uv run alembic upgrade head
```

Start the API in one process:

```bash
PYTHONPATH=src uv run uvicorn darwinspot.main:app \
  --host 0.0.0.0 \
  --port 8000
```

Start the worker in a separate process or service:

```bash
PYTHONPATH=src uv run python -m darwinspot.worker
```

The worker is required for scheduled autonomous cycles and durable outbox work.
Starting only FastAPI is not a complete live trading deployment.

The worker validates `OPENAI_API_KEY`, `OPENAI_MODEL`, and
`CODEX_APP_SERVER_COMMAND` at startup. It keeps bounded provider/auth failures
in the retry path and must not fabricate exchange state.

## Frontend

Build the frontend against the backend origin:

```bash
cd ../frontend
BACKEND_URL=http://127.0.0.1:8000 pnpm build
HOSTNAME=0.0.0.0 PORT=3000 pnpm start
```

For production, use HTTPS and a reverse proxy or ingress. Set
`FRONTEND_ORIGIN` to the exact real frontend origin, including scheme and
port when applicable. Do not expose a development HTTP origin as production
configuration.

The root `docker-compose.yml` is the safe JUDGE/DEMO runtime, not the
production live deployment.

## Common LIVE settings

Both live profiles require:

```dotenv
DEMO_MODE=false
FINANCIAL_WRITES_ENABLED=false  # public showcase; true only for real trading
PUBLIC_SHOWCASE_ENABLED=false   # true only for the public read-only showcase
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE
OPENAI_API_KEY=<real backend-only model-provider key>
OWNER_PASSWORD_HASH=<Argon2id hash; never plaintext>
FRONTEND_ORIGIN=https://your-real-frontend.example
```

`FINANCIAL_WRITES_ENABLED=false` is an additional final write authorization
boundary. `DEMO_MODE=true` always wins and blocks writes even if the flag is
mistakenly set to true. Neither flag bypasses existing policy, budget,
emergency-stop, approval, Codex confirmation, revalidation, or transport gates.

`OPENAI_MODEL` defaults to the current configured model:

```dotenv
OPENAI_MODEL=gpt-5.4-mini
```

`OPENAI_BASE_URL` is optional. Leave it unset for direct OpenAI, or set an
absolute HTTP(S) URL for an OpenAI-compatible gateway.

## AUTO_BOUNDED credentials

`AUTO_BOUNDED` uses the backend Binance Spot API:

```dotenv
BINANCE_API_KEY=<dedicated backend-only Spot API key>
BINANCE_API_SECRET=<dedicated backend-only Spot API secret>
BINANCE_SPOT_API_BASE_URL=https://api.binance.com
BINANCE_RECV_WINDOW_MS=5000
BINANCE_ACCOUNT_LOCK_KEY=darwinspot-binance-account
```

Requirements and behavior:

- `BINANCE_API_KEY` and `BINANCE_API_SECRET` are the required financial
  credentials for this transport.
- No per-order human approval is required.
- Codex OAuth is not required for AUTO_BOUNDED execution.
- Use a dedicated Spot-trading-only key, disable withdrawals, do not grant
  Futures or Margin permissions unless separately required outside DARWIN, and
  avoid unnecessary transfer permissions.
- Restrict the key by IP where Binance supports it.
- Keep both values backend-only; never put them in frontend configuration.
- The defaults are `https://api.binance.com`, `5000` ms receive window, and
  `darwinspot-binance-account` lock key.
- `TOKEN_ENCRYPTION_KEY` is **not required for the AUTO_BOUNDED readiness
  path**. It is used for persisted connection/OAuth material in other paths.

A configured key only establishes readiness for the Spot adapter. Funded live
execution remains NOT VERIFIED until a controlled operator acceptance is
performed.

## HUMAN_APPROVAL credentials

`HUMAN_APPROVAL` uses Codex App Server and Binance Agent OS MCP:

```dotenv
BINANCE_AGENT_OS_MCP_URL=https://agent.binance.com/mcp/agentic
BINANCE_AGENT_OS_TRANSPORT=codex
CODEX_APP_SERVER_COMMAND="codex app-server --stdio"
CODEX_APP_SERVER_VERSION=0.153.0
CODEX_WRITE_CONFIRMATION_VERIFIED=false
TOKEN_ENCRYPTION_KEY=<Fernet key protecting persisted connection/OAuth material>
```

Requirements and behavior:

- Use the genuine supported Codex-managed Binance Agent OS OAuth flow.
- The current readiness/auth path requires `TOKEN_ENCRYPTION_KEY` to protect
  persisted connection/OAuth material.
- `HUMAN_APPROVAL` does not use `BINANCE_API_KEY`/
  `BINANCE_API_SECRET` as its primary write transport.
- `CODEX_WRITE_CONFIRMATION_VERIFIED=false` must remain false until a real
  operator manually verifies the live write elicitation/confirmation contract.
- The authenticated Codex/Binance live bridge remains manually unverified.

The current pinned Codex configuration is App Server `0.153.0`, command
`codex app-server --stdio`, transport `codex`, and the official MCP endpoint
shown above. These values do not prove that the operator is authenticated.

## Generate OWNER_PASSWORD_HASH

Generate an Argon2id hash locally and put only the hash in `OWNER_PASSWORD_HASH`:

```bash
cd backend
uv run python - <<'PY'
from argon2 import PasswordHasher
import getpass

password = getpass.getpass("Owner password: ")
print(PasswordHasher().hash(password))
PY
```

Never store the plaintext owner password in `.env`, source control, logs, or
shell history. The current `verify_owner_password()` implementation was
verified with a temporary random password/hash pair; the plaintext was not
stored or printed.

## Generate TOKEN_ENCRYPTION_KEY

Generate a Fernet key locally and put only that key in
`TOKEN_ENCRYPTION_KEY`:

```bash
cd backend
uv run python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

This key protects persisted connection/OAuth material. Never commit a real key,
print it in logs, or replace it casually after persisted material exists. A
fresh temporary key was verified with the current encryption/decryption helpers
using a non-secret round-trip value.

## Optional Telegram configuration

Telegram is optional. If enabled, configure all four current settings together:

```dotenv
TELEGRAM_BOT_TOKEN=<backend-only bot token>
TELEGRAM_OPERATOR_CHAT_ID=<exact operator chat id>
TELEGRAM_OPERATOR_USER_ID=<exact operator user id>
TELEGRAM_WEBHOOK_SECRET=<Telegram webhook secret>
```

Leave all four unset when Telegram is disabled. HUMAN_APPROVAL also supports web
approval. Telegram can deliver proposals, approvals, and notifications, while
AUTO_BOUNDED does not require Telegram approval. Notification delivery is not
financial authorization.

## Live acceptance boundary

Implementation is present, but live provider acceptance is not claimed:

- AUTO_BOUNDED funded live order acceptance: NOT VERIFIED.
- HUMAN_APPROVAL genuine authenticated Codex/Binance acceptance: PENDING /
  NOT VERIFIED.
- **Judge-facing `/demo` and public-enabled `/showcase` Chromium rendering:** VERIFIED.
- **Full operator/control-room browser acceptance:** NOT CLAIMED / not exhaustively verified.

Do not submit a funded order, withdrawal, transfer, or live Codex financial
confirmation as part of documentation verification.
