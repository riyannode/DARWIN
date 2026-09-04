# DARWIN Runbook

This runbook starts DARWIN safely before operator Binance/Codex OAuth. It never
asks the agent to handle Binance credentials, cookies, bearer tokens, or 2FA.

## Verification boundary

Current implementation status:

```text
Codex/Binance transport implementation: IMPLEMENTED
Authenticated live bridge verification: PENDING
Production readiness: PARTIALLY VERIFIED
```

Verified without Binance login: migrations, deterministic policy, approval and
outbox state, Codex App Server initialize/status handling, unauthenticated write
blocking, bounded public Binance `/api/v3/klines` mapping and decision evidence,
backend checks, frontend build, and local API/Chromium behavior where configured.

## 1. Install

Requirements are the versions locked by the repository: Python 3.14.x, uv,
Node.js, pnpm 11.25.0, and PostgreSQL for production-like state.

```bash
cd backend
uv sync --frozen
cd ../frontend
pnpm install --frozen-lockfile
cd ..
```

If pnpm reports an ignored build script, approve only the exact package it
reports, then rerun `pnpm install --frozen-lockfile`.

## 2. Configure backend

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env
```

Set `DATABASE_URL`, owner password hash, `OPENAI_API_KEY`,
`TOKEN_ENCRYPTION_KEY`, and exact `FRONTEND_ORIGIN`. DARWIN can start with
Codex/Binance auth pending.

Default transport configuration:

```dotenv
BINANCE_AGENT_OS_TRANSPORT=codex
CODEX_APP_SERVER_COMMAND=codex app-server --stdio
CODEX_APP_SERVER_VERSION=0.153.0
CODEX_WRITE_CONFIRMATION_VERIFIED=false
APPROVAL_TTL_SECONDS=90
SIGNAL_COOLDOWN_SECONDS=300
```

Do not set `CODEX_WRITE_CONFIRMATION_VERIFIED=true` until the manual operator
verification has observed the real Codex/Binance confirmation contract.

For Telegram, configure all four values together:

```dotenv
TELEGRAM_BOT_TOKEN=<backend-only bot token>
TELEGRAM_OPERATOR_CHAT_ID=<exact chat id>
TELEGRAM_OPERATOR_USER_ID=<exact user id>
TELEGRAM_WEBHOOK_SECRET=<Telegram secret token>
```

No Telegram secret belongs in frontend environment variables.

## 3. Migrate

```bash
cd backend
PYTHONPATH=src uv run alembic upgrade head
```

The current migration is `0003_approval_outbox`. It adds structured mandate
policy, bounded intent evidence, durable approvals, and the PostgreSQL work
outbox. Migration downgrade/upgrade is reversible for controlled maintenance.

## 4. Start API, worker, and frontend

API:

```bash
cd backend
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
BACKEND_URL=http://127.0.0.1:8000 pnpm build
HOSTNAME=127.0.0.1 PORT=3000 pnpm start
```

The worker remains alive when Codex reports `AUTH_REQUIRED`; it records the
failure/retry state and performs no fabricated Binance read or write.

## 5. Configure DARWIN

1. Sign in as the owner.
2. Set one required high-level Trading Mandate.
3. Set exact allowed symbols, Max Per Trade, and Max Concurrent Trades.
4. Set the rolling 24-hour BUY budget.
5. Configure the persisted Spot universe. It bootstraps to `BTCUSDT`, `ETHUSDT`,
   `BNBUSDT`, `SOLUSDT`, and `XRPUSDT`; this is not a runtime limit or top-five
   strategy. Add/remove valid Spot/USDT symbols as needed; adding a symbol here
   does not authorize it in the mandate.
6. Choose `AUTO_BOUNDED` for autonomous execution without per-order approval,
   or `HUMAN_APPROVAL` for supervised execution through Codex Agent OS.
7. Confirm the UI shows Codex `AUTH_REQUIRED`/`UNVERIFIED` until manual setup.

## 6. Telegram webhook

Telegram has no official sandbox. Use a dedicated test bot and private test
chat when performing real Bot API verification.

The deployed HTTPS webhook URL is:

```text
https://<frontend-origin>/api/integrations/telegram/webhook
```

Configure Telegram’s Bot API webhook with the exact `secret_token` matching
`TELEGRAM_WEBHOOK_SECRET`. The webhook accepts only callback queries from the
configured user ID and chat ID.

Callbacks contain only:

```text
approve:<approval_id>
reject:<approval_id>
```

The backend resolves the approval server-side, checks PENDING/unexpired state,
and atomically pairs the approval and intent transition. Duplicate callbacks
are idempotent; unauthorized callbacks fail closed.

## 7. Normal runtime

```text
DecisionCycle
  -> lightweight Spot/USDT market universe and effective intersection
  -> bounded 15m/1h candidate history for every effective symbol
  -> one selected pair
  -> selected-pair current ticker + 15m/1h/4h closed OHLCV + account evidence
  -> DARWIN BUY/SELL/HOLD
  -> deterministic policy gate
  -> HUMAN_APPROVAL: WAITING_FOR_APPROVAL + Telegram outbox
     AUTO_BOUNDED: AUTO_POLICY authorization + execution outbox
  -> account-scoped PostgreSQL lock
  -> fresh revalidation
  -> HUMAN_APPROVAL: operator authorization + Codex transport
     AUTO_BOUNDED: direct Binance Spot API
  -> optional observed confirmation for HUMAN_APPROVAL
  -> exact write only when the selected path allows it
  -> reconciliation + Telegram receipt
```

Reject and expiry are no-write terminal states. Approval never mutates symbol,
side, quantity, price, or final Binance arguments.

Candidate scanning is count-independent and uses the complete effective set,
up to the existing configured-universe validation maximum of 100 symbols. Each
candidate receives 10 closed candles for `15m` and `1h`; no `4h` candidate scan
or 48-candle candidate fetch is performed. A failed candidate is excluded and
recorded in sanitized audit evidence. If all candidates fail, no pair selection
or financial work occurs. Final detail remains 48 closed candles for each
`15m`, `1h`, and `4h` interval for only the selected pair.

## 8. Emergency stop

The authenticated owner emergency-stop control:

- stops new proposals and ordinary execution claims;
- records exact targeted intent/order IDs;
- queues narrow emergency cancellation work;
- uses account serialization and reconciliation;
- leaves orders `CANCEL_PENDING` until a terminal exchange state is observed.

Model cancellation and direct web cancellation are disabled. Transfers and
withdrawals remain unsupported.

## 9. Health and status

```bash
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
curl -i http://127.0.0.1:8000/docs
```

After owner login, inspect:

```text
GET /api/integrations/codex/status
GET /api/integrations/telegram/status
GET /api/activity
GET /api/budget
```

Codex status must be shown as `UNVERIFIED` until the manual live bridge gate
passes, even if App Server initialization itself succeeds.

## 10. Deferred manual verification

Perform later with genuine operator interaction:

1. Run genuine Codex-managed Binance OAuth.
2. Confirm authenticated `mcpServerStatus/list`.
3. Confirm populated Binance tool inventory.
4. Run an exact harmless read-only `mcpServer/tool/call` and inspect the
   structured result.
5. Create a bounded DARWIN TradeIntent and approve it through Telegram.
6. Observe the exact Binance/Codex write confirmation/elicitation.
7. Do not auto-answer it. Decline it.
8. Verify zero Binance trade was created.
9. Only after that, deliberately verify any controlled approved write.

If any step cannot be performed, keep the status `PENDING` and do not claim
production readiness.

## 11. Troubleshooting

### Codex `AUTH_REQUIRED`

Expected before manual OAuth. Do not put credentials into DARWIN. Complete the
operator Codex login later, then recheck `mcpServerStatus/list` and tools.

### Telegram proposal not delivered

Inspect the activity notification state and outbox retry state. An approval
row may exist while delivery is pending/failed; that never means the operator
was notified and never enables execution automatically.

### `SUBMISSION_UNKNOWN`

Do not retry blindly. Reconciliation by stored Binance order ID or the same
client idempotency key must resolve the external state first.

### Frontend build dependency gate

Approve only the named pnpm package reported by the build-policy prompt. Do not
approve unrelated scripts.

## 12. Stop services

Stop only processes started for this run with `Ctrl+C` or their tracked process
IDs. Leave shared PostgreSQL running unless it was started exclusively for this
run.

Final check:

```bash
git status --short --branch
```

The worktree must be clean and `backend/.env` must remain untracked.
