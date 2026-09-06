# DARWIN Runbook

This runbook describes the current operational contract. It does not authorize deployment, restart, credential creation, a funded order, or a live provider confirmation.

## 1. Choose the profile

| Goal | Profile | Result |
| --- | --- | --- |
| Judge walkthrough | JUDGE DEMO | Synthetic data, no external LLM, no Binance connection, no financial writes. Run `docker compose up --build`, then open `/demo`. |
| Public evidence | PUBLIC LIVE SHOWCASE | Real model and Binance evidence, scheduled worker, read-only `/showcase`, financial writes closed. |
| Operator-controlled trade execution | REAL LIVE TRADING | Financial writes deliberately enabled, subject to all policy and mode gates. |

See [LIVE.md](LIVE.md) for exact flags and configuration.

## 2. Install and configure live prerequisites

```bash
cd backend
uv sync --frozen
cp .env.example .env

cd ../frontend
pnpm install --frozen-lockfile
```

For live state, set a PostgreSQL `DATABASE_URL`, an Argon2id `OWNER_PASSWORD_HASH`, and exact `FRONTEND_ORIGIN` in `backend/.env`. Then select the mode-specific configuration:

- `AUTO_BOUNDED`: `OPENAI_API_KEY`, `OPENAI_MODEL`, `BINANCE_API_KEY`, and `BINANCE_API_SECRET` for DARWIN's AgentRuntime and direct Binance Spot API.
- `HUMAN_APPROVAL`: `DARWIN_MCP_BEARER_TOKEN`, `TOKEN_ENCRYPTION_KEY`, Codex App Server transport configuration, and genuine Binance Agent OS OAuth. The external MCP host supplies reasoning; DARWIN does not require `OPENAI_API_KEY` for this mode's readiness.

Optional Telegram must be a complete group of `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OPERATOR_CHAT_ID`, `TELEGRAM_OPERATOR_USER_ID`, and `TELEGRAM_WEBHOOK_SECRET`.

## 3. Migrate

The checked-in Alembic head is `0006_canonical_trading_mandate`, not `0003_approval_outbox`.

```bash
cd backend
PYTHONPATH=src uv run alembic upgrade head
```

## 4. Run the three live processes

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

The worker is required for scheduled cycles and durable outbox work. It validates model configuration and records provider/auth failures without fabricating Binance state. FastAPI without the worker is not a complete live operation.

## 5. Configure DARWIN as owner

1. Sign in at an owner control-panel route.
2. Set one Trading Mandate, Allowed Symbols, Max Per Trade, and Max Concurrent Trades.
3. Set the rolling 24h Trading Budget.
4. Review the Configured Universe. A newly created configuration bootstraps to `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, and `XRPUSDT`; it can hold up to 100 valid Spot/USDT symbols. A database upgraded from before `0004_dual_execution_and_universe` can retain that migration's four-symbol compatibility value (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`) until an owner updates it.
5. Remember that configuration is not authorization:

   ```text
   Effective Universe = Configured Universe ∩ Allowed Symbols ∩ live-valid Binance Spot/USDT symbols
   ```

6. Select `AUTO_BOUNDED` for direct bounded Spot API execution without per-order approval, or `HUMAN_APPROVAL` for the MCP-native external-host proposal and explicit owner approval flow.
7. Start scheduled operation only after the displayed transport state and profile flags match the intended mode.

## 6.1 MCP-native HUMAN_APPROVAL operation

**AI proposes. DARWIN authorizes. Binance executes.** Configure a compatible external MCP host—such as Codex, Claude Code, Cursor, or ChatGPT—with the private `DARWIN_MCP_BEARER_TOKEN` for `/mcp`.

The host may discover the implemented DARWIN tools, read `darwin.get_status`, `darwin.get_mandate`, `darwin.get_budget`, `darwin.get_universe`, and `darwin.get_portfolio`, reason externally, validate a proposal, submit an untrusted proposal, and present owner controls. The authoritative sequence is:

```text
read state
  -> darwin.validate_proposal
  -> darwin.submit_proposal
  -> WAITING_FOR_APPROVAL
  -> explicit owner darwin.approve_trade or darwin.reject_trade
  -> existing TradeIntentApprovalService
  -> durable execution outbox / ApprovedExecution
  -> Codex App Server -> Binance Agent OS MCP
```

`darwin.validate_proposal` is dry-run only. `darwin.submit_proposal` requires an idempotency key and stops at durable `WAITING_FOR_APPROVAL`; it never places an order. The host/model cannot self-approve, provide trusted balances or filters, inject policy results, or call raw Binance order tools. Provider confirmation remains separate and is never auto-answered by DARWIN.

## 6. Normal decision and execution path

```text
Effective Universe
  -> candidate scan: closed 15m + 1h evidence for every candidate
  -> AgentRuntime selects one pair
  -> selected-pair ticker, balances, orders, activity, filters, closed 15m/1h/4h evidence
  -> typed BUY / SELL / HOLD
  -> deterministic policy, budget, freshness, and emergency-stop checks
  -> financial-write gate
  -> HUMAN_APPROVAL: external MCP host -> DARWIN validate/submit -> WAITING_FOR_APPROVAL
     -> explicit owner approve/reject through DARWIN MCP -> Codex / Binance Agent OS MCP
     AUTO_BOUNDED: AUTO_POLICY -> direct Binance Spot API
  -> fresh revalidation, account lock, write marker, submission, reconciliation
```

Candidate scans use 10 closed `15m` and `1h` candles per effective symbol. Final selected-pair evidence uses 48 closed candles for `15m`, `1h`, and `4h`. Candidate failures exclude only the failed symbol and are persisted in original-cycle evidence. No candidate set produces `NO_EFFECTIVE_SYMBOLS` with no financial work.

Approval cannot change the symbol, side, quantity, price, or final Binance arguments. The approval TTL defaults to 90 seconds and is bounded to 30–180 seconds. Duplicate MCP submissions and approval decisions are idempotent; existing Telegram/web approval compatibility remains separate from the MCP-native proposal path.

## 7. Emergency stop and uncertain submission

Emergency stop blocks new ordinary proposals and claims, records affected work, and queues reconciled cancellation for applicable known orders. Direct web cancellation and model cancellation are disabled.

For `SUBMISSION_UNKNOWN`, or `SUBMITTING` with an external-call marker:

1. do not retry the financial call;
2. reconcile by stored Binance order identifier or the same client idempotency key;
3. persist the authoritative result; and
4. only then consider later recovery.

An external-call marker indicates possible boundary crossing, not a successful order.

## 8. Health and status

```bash
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
curl -i http://127.0.0.1:8000/docs
```

`/health/ready` is mode-aware: non-demo HUMAN_APPROVAL requires the owner hash, `TOKEN_ENCRYPTION_KEY`, and `DARWIN_MCP_BEARER_TOKEN`, but not DARWIN `OPENAI_API_KEY`; AUTO_BOUNDED continues to require the LLM and direct Binance Spot credentials. Readiness is configuration readiness, not funded-order acceptance.

Owner inspection routes include:
```text
GET /api/agent
GET /api/budget
GET /api/portfolio
GET /api/activity
GET /api/integrations/binance/status
GET /api/integrations/binance-api/status
GET /api/integrations/codex/status
GET /api/integrations/telegram/status
```

Public `GET /api/showcase` is available only in the PUBLIC LIVE SHOWCASE profile. Demo API routes are available only in JUDGE DEMO.

## 9. Verification boundary

- **VERIFIED:** fresh non-financial Docker JUDGE DEMO, all demo scenario APIs, zero durable demo rows, and Chromium `/demo` rendering plus scenario selection.
- **VERIFIED:** MCP-native bearer denial, tools/list, HUMAN_APPROVAL readiness without DARWIN OpenAI key, proposal mode guards, zero durable AUTO_BOUNDED admission work, and normal HUMAN_APPROVAL durable admission checks on the PR #10 feature branch.
- **IMPLEMENTED:** AgentRuntime, policy, mode transports, durable approval/outbox, write markers, reconciliation, emergency stop, and safe-live closure.
- **PENDING / NOT VERIFIED:** genuine authenticated Binance Agent OS/Codex provider acceptance.
- **NOT VERIFIED:** PUBLIC LIVE SHOWCASE Chromium under its required live profile; funded AUTO_BOUNDED live order; full authenticated owner-control-panel acceptance.

Stop only processes started for a run. Keep `backend/.env` untracked and never place credentials, cookies, OAuth codes, account values, or private URLs in the repository.
