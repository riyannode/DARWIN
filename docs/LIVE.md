# DARWIN Live installation and profiles

This guide covers provider-backed operation. For the isolated, zero-credential walkthrough, use [DEMO.md](DEMO.md).

## Requirements declared by the repository

- Python `>=3.14,<3.15` and `uv` (`backend/pyproject.toml`)
- PostgreSQL for live durable state
- pnpm `11.25.0` (`frontend/package.json`)
- a Node.js version supported by the pinned Next.js `16.3.4`; the repository does not declare an `engines` field
- Codex App Server only for `HUMAN_APPROVAL`

## Clone and install dependencies

```bash
git clone https://github.com/riyannode/DARWIN.git
cd DARWIN

cd backend
uv sync --frozen
cp .env.example .env

cd ../frontend
pnpm install --frozen-lockfile
cd ..
```

On Windows PowerShell, replace `cp` with:

```powershell
Copy-Item .env.example .env
```

Keep `backend/.env` backend-only and untracked. Do not put credentials in frontend environment variables.

## Create `backend/.env` and local secrets

From the repository root, enter `backend`, copy the example to `.env`, then generate each secret without putting plaintext credentials in the file or command history:

```bash
cd backend
uv run python -c "from getpass import getpass; from argon2 import PasswordHasher; print(PasswordHasher().hash(getpass('Owner password: ')))"
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
uv run python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Use the three outputs for `OWNER_PASSWORD_HASH`, `TOKEN_ENCRYPTION_KEY`, and `DARWIN_MCP_BEARER_TOKEN`. The same commands work in PowerShell after `cd backend`; `getpass` does not echo the owner password.

For a local HUMAN_APPROVAL deployment, set these values in `backend/.env`:

```dotenv
DEMO_MODE=false
FINANCIAL_WRITES_ENABLED=false
PUBLIC_SHOWCASE_ENABLED=false
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@127.0.0.1:5432/DATABASE
FRONTEND_ORIGIN=http://127.0.0.1:3000
OWNER_PASSWORD_HASH=<generated Argon2id hash>
TOKEN_ENCRYPTION_KEY=<generated Fernet key>
DARWIN_MCP_BEARER_TOKEN=<generated bearer token>
BINANCE_AGENT_OS_MCP_URL=https://agent.binance.com/mcp/agentic
BINANCE_AGENT_OS_TRANSPORT=codex
CODEX_APP_SERVER_COMMAND="codex app-server --stdio"
CODEX_APP_SERVER_VERSION=0.153.0
CODEX_WRITE_CONFIRMATION_VERIFIED=false
```

Do not add `OPENAI_API_KEY`, `BINANCE_API_KEY`, or `BINANCE_API_SECRET` for HUMAN_APPROVAL. Binance account reads still require the genuine Binance Agent OS authorization available to the configured Codex App Server. A fresh database defaults to `HUMAN_APPROVAL`; confirm the mode with `darwin.get_status` after startup. On an existing database, select `HUMAN_APPROVAL` from the owner `/agent` control panel before using the MCP proposal path.

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
OWNER_PASSWORD_HASH=<Argon2id hash>
FRONTEND_ORIGIN=https://your-real-frontend.example
```

`OPENAI_BASE_URL` is optional for `AUTO_BOUNDED`. Omit it for direct OpenAI, or set an absolute HTTP(S) OpenAI-compatible endpoint without embedded credentials, query, or fragment. The external MCP host supplies reasoning for the MCP-native `HUMAN_APPROVAL` path; DARWIN does not require `OPENAI_API_KEY` for that mode's readiness.

### AUTO_BOUNDED configuration

`AUTO_BOUNDED` continues to use DARWIN's AgentRuntime and requires its LLM configuration plus direct Binance credentials:

```dotenv
OPENAI_API_KEY=<backend-only provider key>
OPENAI_MODEL=gpt-5.4-mini
BINANCE_API_KEY=<dedicated backend-only Spot key>
BINANCE_API_SECRET=<dedicated backend-only Spot secret>
BINANCE_SPOT_API_BASE_URL=https://api.binance.com
BINANCE_RECV_WINDOW_MS=5000
BINANCE_ACCOUNT_LOCK_KEY=darwinspot-binance-account
```

The direct adapter accepts only approved Binance HTTPS API hosts. Use a dedicated Spot-only key, disable withdrawals, avoid Futures/Margin/transfer permissions, restrict by IP where supported, and keep the credentials server-side. `TOKEN_ENCRYPTION_KEY` is not required for AUTO_BOUNDED API readiness.

A fresh database defaults to `HUMAN_APPROVAL`. After startup, sign in to the owner UI, open `/agent`, and select `AUTO_BOUNDED`. `/health/ready` reflects the currently persisted mode, so check it again after changing the mode.

### HUMAN_APPROVAL configuration

`HUMAN_APPROVAL` is MCP-native: an external MCP-compatible host reasons and proposes through DARWIN's private `/mcp` control plane. DARWIN validates the untrusted proposal, persists `WAITING_FOR_APPROVAL`, and keeps explicit owner approval separate from model reasoning.

```dotenv
BINANCE_AGENT_OS_MCP_URL=https://agent.binance.com/mcp/agentic
BINANCE_AGENT_OS_TRANSPORT=codex
CODEX_APP_SERVER_COMMAND="codex app-server --stdio"
CODEX_APP_SERVER_VERSION=0.153.0
CODEX_WRITE_CONFIRMATION_VERIFIED=false
TOKEN_ENCRYPTION_KEY=<Fernet key for persisted Agent OS/OAuth material>
DARWIN_MCP_BEARER_TOKEN=<private bearer token for the inbound /mcp control plane>
```

Use a compatible MCP host such as Codex, Claude Code, Cursor, or ChatGPT with the configured bearer token. The host may read authorized projections, reason, propose, and present controls; it cannot provide trusted balances, filters, policy results, final Binance arguments, or unrestricted raw order tools. `darwin.approve_trade` and `darwin.reject_trade` are explicit owner actions through the existing approval service. Keep `CODEX_WRITE_CONFIRMATION_VERIFIED=false` until an operator has observed the real write confirmation contract. A successful setting does not prove the operator is authenticated.

Scheduling defaults:

```dotenv
AGENT_CYCLE_SECONDS=300
SIGNAL_COOLDOWN_SECONDS=300
APPROVAL_TTL_SECONDS=90
```

The Codex command above is used as a transport process after HUMAN_APPROVAL, not as the reasoning engine. `APPROVAL_TTL_SECONDS` is bounded to 30–180 seconds.

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

Terminal 1 — migrate once, then API:

```bash
cd backend
PYTHONPATH=src uv run alembic upgrade head
PYTHONPATH=src uv run uvicorn darwinspot.main:app --host 127.0.0.1 --port 8000
```

Terminal 2 — required worker:

```bash
cd backend
PYTHONPATH=src uv run python -m darwinspot.worker
```

Terminal 3 — frontend:

```bash
cd frontend
BACKEND_URL=http://127.0.0.1:8000 pnpm build
HOSTNAME=127.0.0.1 PORT=3000 pnpm start
```

On Windows PowerShell, use these environment assignments in the corresponding terminals:

```powershell
# Terminal 1
cd backend
$env:PYTHONPATH = "src"
uv run alembic upgrade head
uv run uvicorn darwinspot.main:app --host 127.0.0.1 --port 8000

# Terminal 2
cd backend
$env:PYTHONPATH = "src"
uv run python -m darwinspot.worker

# Terminal 3
cd frontend
$env:BACKEND_URL = "http://127.0.0.1:8000"
$env:HOSTNAME = "127.0.0.1"
$env:PORT = "3000"
pnpm build
pnpm start
```

`BACKEND_URL` is server-only and drives Next.js `/api/:path*` rewrites. `FRONTEND_ORIGIN` is the exact browser origin used for CORS, mutation-origin checks, cookies, and Agent OS callback URLs.

The worker is required for durable outbox work in both modes. HUMAN_APPROVAL does not schedule internal `AgentRuntime` reasoning, but FastAPI without the worker is not a complete live operation.

## Connect an MCP host

The local DARWIN MCP endpoint is:

```text
http://127.0.0.1:8000/mcp
```

Send `Authorization: Bearer <DARWIN_MCP_BEARER_TOKEN>` on every request. Current PR #10 acceptance found 17 DARWIN tools through `tools/list`. The inbound reasoning host and the outbound provider transport are separate: Codex, Claude Code, Cursor, or ChatGPT may reason through DARWIN's `/mcp`, while the configured outbound Binance Agent OS transport remains Codex App Server.

### Codex

The Windows Codex acceptance used the endpoint and bearer token above. For Codex CLI, the current official command is:

```powershell
$env:DARWIN_MCP_BEARER_TOKEN = "<same value as backend/.env>"
codex mcp add darwin --url http://127.0.0.1:8000/mcp --bearer-token-env-var DARWIN_MCP_BEARER_TOKEN
codex mcp list
```

Codex desktop, Codex CLI, and the IDE extension share this MCP configuration. Restart or reload the Windows Codex App as required, use `/mcp` to confirm `darwin` is active, then verify `darwin.get_status` and the 17-tool catalog. The bearer token is configured through the supported CLI/config entry above; do not assume a separate UI bearer-header field, and do not use `codex mcp login darwin` for this locally generated bearer token.

### Outbound Binance Agent OS authorization

This is a separate connection from the inbound DARWIN bearer-protected MCP:

| Connection | Server name | Endpoint | Authentication |
| --- | --- | --- | --- |
| External host → DARWIN | `darwin` | `http://127.0.0.1:8000/mcp` | `DARWIN_MCP_BEARER_TOKEN` |
| DARWIN → Codex App Server → Binance Agent OS | `binance` | `https://agent.binance.com/mcp/agentic` | Binance OAuth stored by Codex |

Configure the outbound server once from PowerShell, then start the genuine OAuth flow:

```powershell
codex mcp add binance --url https://agent.binance.com/mcp/agentic
codex mcp login binance
codex mcp list
```

Complete the Binance browser authorization and approve only the scopes needed for the intended read acceptance. Return to Codex after the callback, confirm `binance` is listed and authenticated with `codex mcp list`, and use `/mcp` in the Codex App to confirm the active authenticated server. Do not put Binance API keys in DARWIN or Codex configuration. Do not fund the Agentic sub-account or grant trade/transfer scopes for a read-only first run.

Only after `binance` is authenticated should you start DARWIN and call its read tools. DARWIN's outbound transport passes the server name `binance` to Codex App Server; changing that name breaks the provider connection.

### Claude Code

Claude Code's HTTP MCP configuration accepts a static bearer header:

```powershell
$env:DARWIN_MCP_BEARER_TOKEN = "<same value as backend/.env>"
claude mcp add --transport http darwin --scope user http://127.0.0.1:8000/mcp --header "Authorization: Bearer $env:DARWIN_MCP_BEARER_TOKEN"
```

### Cursor

For a private fork-user setup, use the personal/global `~/.cursor/mcp.json`. A project-scoped `.cursor/mcp.json` is different and belongs to that project. Keep the token in an environment variable and never put its literal value in either file:

```json
{
  "mcpServers": {
    "darwin": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Authorization": "Bearer ${env:DARWIN_MCP_BEARER_TOKEN}"
      }
    }
  }
}
```

### ChatGPT

ChatGPT custom MCP apps use Developer Mode and require a remote MCP endpoint; ChatGPT cannot connect directly to a server bound only to `127.0.0.1`. Use a supported Secure MCP Tunnel or another authenticated remote deployment, and do not expose the bearer token in a public repository. ChatGPT plan and workspace availability, custom-app permissions, and write support vary; this repository has verified the Codex Windows path, not a ChatGPT connection.

Official host references: [Binance MCP Server](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic), [Codex MCP](https://developers.openai.com/codex/mcp/), [Claude Code MCP](https://code.claude.com/docs/en/mcp), [Cursor MCP](https://cursor.com/docs/mcp), and [ChatGPT Developer Mode and MCP apps](https://help.openai.com/en/articles/12584461).

## Safe first live test

Keep `FINANCIAL_WRITES_ENABLED=false` for the first run. From the connected MCP host:

1. Call `darwin.get_status`, `darwin.get_mandate`, `darwin.get_budget`, `darwin.get_universe`, `darwin.get_portfolio`, and `darwin.list_pending_trades`.
2. Confirm the mode, bearer-authenticated tool catalog, and provider read state before proposing anything.
3. Optionally call `darwin.validate_proposal`; it is dry-run only and does not persist an intent.
4. Do not call `darwin.approve_trade` or any provider order tool during this smoke test. A zero-balance account may correctly return `insufficient available USDT balance`; that is a policy result, not proof of integration failure.

Before enabling any financial write, verify the mandate, allowed Spot/USDT universe, budget, account permissions, owner session, provider confirmation behavior, and recovery/reconciliation plan. A configured live profile is not evidence of a funded live order.

## Health

```bash
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
curl -i http://127.0.0.1:8000/docs
```

In PowerShell, use `curl.exe` if `curl` resolves to the PowerShell web-request alias.

`/health/ready` is mode-aware in live mode. It requires the owner hash in every non-demo profile. `AUTO_BOUNDED` additionally requires `OPENAI_API_KEY`, `OPENAI_MODEL`, and direct Binance Spot credentials. `HUMAN_APPROVAL` does not require DARWIN `OPENAI_API_KEY`, but it requires `TOKEN_ENCRYPTION_KEY` and `DARWIN_MCP_BEARER_TOKEN` for the MCP-native control plane and persisted provider authorization. Readiness is configuration readiness, not funded-order acceptance.

## Current evidence

| Claim | Status |
| --- | --- |
| Demo Docker runtime, all demo scenarios, and zero durable demo rows | **VERIFIED** in a fresh non-financial Compose run |
| Chromium `/demo` rendering and scenario selection | **VERIFIED** in the same fresh run |
| Public-enabled `/showcase` Chromium rendering | **VERIFIED** |
| MCP-native HUMAN_APPROVAL bearer/tools/list/readiness/proposal admission checks | **VERIFIED** in the PR #10 feature-branch checks |
| Authenticated Binance Agent OS/Codex read acceptance on Windows | **VERIFIED**: bearer auth, 17 DARWIN tools, deferred Spot discovery 0 → 48, `get_universe` `FRESH`, `get_portfolio` `CONNECTED`, and deterministic zero-USDT rejection |
| Funded HUMAN_APPROVAL proposal, provider write confirmation, or Binance order | **NOT VERIFIED**: the account was unfunded; no `WAITING_FOR_APPROVAL` attempt, approval, or order was made |
| AUTO_BOUNDED transport regression | **VERIFIED**: uses `BinanceSpotApiClient` |
| Live configuration, worker, mode transport, and safety implementation | **IMPLEMENTED** |
| Funded AUTO_BOUNDED execution | **NOT VERIFIED** |

Do not use documentation verification as a reason to submit a funded order, withdrawal, transfer, or live transport confirmation.
