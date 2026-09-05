# DARWIN Deployment

## Checked-in deployment state

The repository ships one `docker-compose.yml`. It is intentionally the **JUDGE DEMO** runtime, using local SQLite and `DEMO_MODE=true`; it is not a live-trading deployment manifest.

A live deployment needs managed processes for the API, the worker, the frontend, and PostgreSQL. The worker is required for scheduled decision cycles, approval expiry, execution/confirmation work, notification outbox work, and emergency-cancellation work. Starting FastAPI alone is not a complete live operation.

## Runtime profiles

| Profile | `DEMO_MODE` | `FINANCIAL_WRITES_ENABLED` | `PUBLIC_SHOWCASE_ENABLED` | Behavior |
| --- | --- | --- | --- | --- |
| **JUDGE DEMO** | `true` | `false` | `false` | Synthetic `/demo`, zero credentials, no external LLM, no Binance connection, no financial writes. |
| **PUBLIC LIVE SHOWCASE** | `false` | `false` | `true` | Real model and Binance evidence, scheduled worker, persisted read-only `/showcase`, no financial writes. |
| **REAL LIVE TRADING** | `false` | `true` | normally `false` | Operator-controlled Spot execution after the configured mode's authorization and all backend gates. |

The showcase endpoint returns 404 unless it is public-enabled, demo mode is off, and financial writes are off. It is public read-only; all operator APIs and mutations remain owner-authenticated.

The financial-write setting is enforced at safe-live decision admission and again directly before external submission; it is not an authorization bypass.

## Profile-specific transports

| Mode | Required transport | Financial credentials | Human authorization |
| --- | --- | --- | --- |
| `AUTO_BOUNDED` | direct Binance Spot API | `BINANCE_API_KEY` + `BINANCE_API_SECRET` | none per order |
| `HUMAN_APPROVAL` | Codex App Server + Binance Agent OS MCP | genuine Codex-managed Agent OS OAuth material, protected by `TOKEN_ENCRYPTION_KEY` | Telegram or web approval |

`AUTO_BOUNDED` does not use Codex OAuth or Telegram approval as its primary transport. `HUMAN_APPROVAL` does not use Binance API keys as its primary write transport. Both remain bounded by the same deterministic policy, fresh revalidation, idempotency, reconciliation, emergency stop, and financial-write gate.

## Service topology

```text
Browser
  -> Next.js frontend (server-side /api rewrite via BACKEND_URL)
  -> FastAPI API
  -> PostgreSQL
  -> worker
       -> OpenAI or compatible model endpoint
       -> AUTO_BOUNDED: Binance Spot API
       -> HUMAN_APPROVAL: Codex App Server -> Binance Agent OS MCP
       -> optional Telegram Bot API
```

Terminate TLS and enforce ingress policy outside the repository. Keep the backend database URL, model key, owner password hash, Binance credentials, OAuth material, and Telegram values outside frontend configuration. The code supports PostgreSQL advisory locks for ordinary financial serialization; SQLite is only the demo default.

## Commands

The authoritative command sequence is in [LIVE.md](LIVE.md). Its essential live steps are:

```bash
cd backend
uv sync --frozen
PYTHONPATH=src uv run alembic upgrade head
PYTHONPATH=src uv run uvicorn darwinspot.main:app --host 0.0.0.0 --port 8000
```

In a separate managed process:

```bash
cd backend
PYTHONPATH=src uv run python -m darwinspot.worker
```

Build and start the frontend with a server-side backend origin:

```bash
cd frontend
BACKEND_URL=http://127.0.0.1:8000 pnpm build
HOSTNAME=0.0.0.0 PORT=3000 pnpm start
```

## Health and acceptance boundary

```bash
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
```

`/health/ready` requires owner credentials and model configuration in live mode, plus mode-dependent direct Spot credentials for `AUTO_BOUNDED` or `TOKEN_ENCRYPTION_KEY` for `HUMAN_APPROVAL`.

| Claim | Status |
| --- | --- |
| Docker JUDGE DEMO, all demo scenarios, and zero durable demo rows | **VERIFIED** in a fresh non-financial Compose run |
| Chromium `/demo` rendering and scenario selection | **VERIFIED** in the same fresh run |
| Public-enabled `/showcase` Chromium rendering | **NOT VERIFIED** in this run |
| Live process/transport implementation | **IMPLEMENTED** |
| Funded direct Spot order | **NOT VERIFIED** |
| Authenticated Binance Agent OS/Codex acceptance | **PENDING / NOT VERIFIED** |

No deploy, restart, or service mutation is performed by these instructions.
