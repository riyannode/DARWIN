# DARWIN

DARWIN is an autonomous Binance Spot market-monitoring and decision runtime with
two explicit execution modes. It continuously collects live evidence, asks the
DARWIN `AgentRuntime` for a typed BUY/SELL/HOLD decision, applies deterministic
policy and budget checks, creates durable `TradeIntent` records, and signals the
operator through Telegram.

DARWIN remains the only decision-making agent. HUMAN_APPROVAL requires operator
approval; AUTO_BOUNDED can execute through the narrow Binance Spot API only
after the same policy, lock, and fresh revalidation checks.

## Runtime flow

```text
24/7 scheduler
  -> market/account evidence
  -> DARWIN decision: BUY / SELL / HOLD
  -> mandate + risk + budget + execution-policy gate
  -> durable TradeIntent
  -> HUMAN_APPROVAL: Telegram proposal -> APPROVE / REJECT / timeout
     AUTO_BOUNDED: AUTO_POLICY authorization -> informational Telegram signal
  -> fresh revalidation
  -> HUMAN_APPROVAL: Codex Agent OS MCP
     AUTO_BOUNDED: Binance Spot API
  -> confirmation, if required
  -> order submission + reconciliation
  -> Telegram receipt
```

`APPROVE` authorizes fresh revalidation. It never authorizes submission of a
stale payload. `REJECT`, `APPROVAL_EXPIRED`, and failed revalidation are terminal
no-write paths.

## Ownership model

DARWIN owns:

- scheduling and worker leases;
- market/account evidence acquisition;
- LLM/model invocation and strategy context;
- BUY/SELL/HOLD decisions;
- structured execution policy, budget, risk, and sizing checks;
- durable TradeIntent and approval state;
- idempotency, write gating, and reconciliation;
- emergency stop and audit trail;
- Telegram proposal/receipt delivery state.

Codex owns only the supported Binance OAuth identity and authenticated MCP
transport. DARWIN never sends Codex natural-language trading prompts and Codex
never chooses trades or evaluates DARWIN policy.

## Safety properties

- `HUMAN_APPROVAL` ordinary BUY/SELL writes require one durable operator approval.
- `AUTO_BOUNDED` ordinary BUY/SELL writes require AUTO_POLICY authorization and
  never bypass deterministic policy, account locking, or fresh revalidation.
- Telegram callbacks contain only `approve:<approval_id>` or
  `reject:<approval_id>`; all intent data is resolved server-side.
- Telegram user ID, chat ID, webhook secret, and bot token are backend-only.
- Approval TTL defaults to 90 seconds and is bounded to 30..180 seconds.
- The persisted configured Spot universe defaults to exactly `BTCUSDT`,
  `ETHUSDT`, `BNBUSDT`, and `SOLUSDT`; an owner can add/remove valid Spot/USDT
  symbols without source changes. The current structured policy contains exact
  `allowed_symbols`,
  `max_order_notional`, and `max_open_actionable_intents`.
- Proposal admission is atomic under PostgreSQL coordination.
- One Binance account cannot execute concurrent ordinary financial writes.
- Fresh market/account/filter/policy checks run immediately before submission.
- The external-call marker is conservative; `SUBMISSION_UNKNOWN` reconciles
  before retry.
- The explicit authenticated emergency-stop command is the only special
  cancellation path. Model CANCEL/CANCEL_REPLACE and direct web cancellation are
  disabled.
- Transfers and withdrawals are unsupported and fail closed.

## Components

- `frontend/` — existing Next.js operator UI and secondary approval surface.
- `backend/` — FastAPI API, DARWIN worker, decision/runtime modules, approval,
  execution, Codex transport, Telegram adapter, database, and migrations.
- `docs/` — architecture, deployment, runbook, product, and submission notes.
- PostgreSQL — source of truth for sessions, mandates, budgets, runs, intents,
  approvals, order events, and durable work outbox rows.

The purpose-specific PostgreSQL `outbox_messages` table carries Telegram
proposal/receipt delivery and bounded approved-execution/emergency-cancel work.
It is not a generic message bus.

## Safe startup and configuration

Copy `backend/.env.example` to `backend/.env` and keep it backend-only. DARWIN
starts safely while Codex/Binance authentication is pending. In that state it
reports `AUTH_REQUIRED`/`NOT_AUTHENTICATED`, produces no fabricated Binance
results, and performs no financial write.

The default transport is:

```dotenv
BINANCE_AGENT_OS_TRANSPORT=codex
CODEX_APP_SERVER_COMMAND=codex app-server --stdio
CODEX_APP_SERVER_VERSION=0.153.0
CODEX_WRITE_CONFIRMATION_VERIFIED=false
APPROVAL_TTL_SECONDS=90
SIGNAL_COOLDOWN_SECONDS=300
```

Telegram requires all four backend-only values together:

```dotenv
TELEGRAM_BOT_TOKEN=<bot token>
TELEGRAM_OPERATOR_CHAT_ID=<chat id>
TELEGRAM_OPERATOR_USER_ID=<user id>
TELEGRAM_WEBHOOK_SECRET=<secret token>
```

Do not commit `backend/.env`, Telegram credentials, OAuth codes, cookies,
bearer tokens, or Codex credential material.

## Verification status

Verified in this implementation without operator Binance login:

- reversible Alembic migration;
- deterministic policy and lifecycle behavior;
- durable approval/outbox logic;
- unauthenticated Codex App Server initialization/status handling;
- Codex write blocking while confirmation verification is false;
- strict backend lint/type checks;
- frontend lint/typecheck/production build;
- local API and Chromium checks where configured.

Current status:

```text
Codex/Binance transport implementation: IMPLEMENTED
Authenticated live bridge verification: PENDING
Production readiness: PARTIALLY VERIFIED
```

## Deferred manual verification

The operator must later perform these steps with a genuine Codex-managed Binance
OAuth session:

1. Authenticate Binance through Codex App Server.
2. Confirm authenticated `mcpServerStatus/list`.
3. Confirm a populated Binance tool inventory.
4. Run an exact harmless read-only `mcpServer/tool/call` and inspect its
   structured result.
5. Observe the real write confirmation/elicitation contract.
6. Decline the first write-path confirmation.
7. Prove that zero Binance trade was created.
8. Only after that, deliberately verify any approved write in a controlled
   operator-owned account.

Telegram has no official sandbox. Use a dedicated test bot/private chat for real
Bot API verification; do not replace it with a mocked acceptance claim.

## Development

Backend:

```bash
cd backend
uv sync --frozen
PYTHONPATH=src uv run alembic upgrade head
PYTHONPATH=src uv run uvicorn darwinspot.main:app --host 127.0.0.1 --port 8000
```

Worker:

```bash
cd backend
PYTHONPATH=src uv run python -m darwinspot.worker
```

Frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
BACKEND_URL=http://127.0.0.1:8000 pnpm build
HOSTNAME=127.0.0.1 PORT=3000 pnpm start
```

The local verification harness is ignored under `.local-tests/` and is never
part of the production source or pull request.
