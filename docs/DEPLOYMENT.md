# DARWIN Deployment

## Runtime profiles

The deployment has three explicit profiles:

| Profile | DEMO_MODE | FINANCIAL_WRITES_ENABLED | PUBLIC_SHOWCASE_ENABLED | Evidence |
| --- | --- | --- | --- | --- |
| JUDGE DEMO | `true` | `false` | `false` | Synthetic `/demo`, zero credentials |
| PUBLIC LIVE SHOWCASE | `false` | `false` | `true` | Real model/market reads, persisted `/showcase`, no writes |
| REAL LIVE TRADING | `false` | `true` | `false` recommended | Operator-authenticated live execution after normal gates |

`FINANCIAL_WRITES_ENABLED` is only an additional final authorization boundary.
It never bypasses deterministic policy, budget, emergency stop, approval,
revalidation, idempotency, or transport checks. `DEMO_MODE=true` always wins.

The public showcase is read-only and fail-closed: when
`PUBLIC_SHOWCASE_ENABLED=false`, `GET /api/showcase` returns 404. Existing
operator APIs and every mutation remain owner-authenticated.

## Current status

| Area | Status |
| --- | --- |
| Demo/Judge Docker runtime | VERIFIED |
| Exact localhost:3000 judge path | VERIFIED on a clean port-3000 re-test |
| AUTO_BOUNDED implementation | Present; funded live-order acceptance NOT VERIFIED |
| HUMAN_APPROVAL implementation | Present; genuine authenticated Codex/Binance acceptance PENDING / NOT VERIFIED |
| Chromium/browser pixel verification | DEFERRED / UNVERIFIED |
| Fully production-verified live trading | Not claimed |

No funded Binance order, withdrawal, transfer, or live Codex financial
confirmation was performed for this verification.

## Judge runtime

The root `docker-compose.yml` is a safe Demo Mode runtime:

```bash
docker compose up --build
```

It starts the backend/frontend pair with local SQLite, runs Alembic, waits for
backend live health, and serves the judge page at:

```text
http://localhost:3000/demo
```

The backend receives `DEMO_MODE=true`. No `.env`, model-provider key, Binance
credential, Codex auth, Telegram setting, or funded account is required. Fixed
synthetic fixtures are used, and the backend financial-write guard blocks
financial writes.

Reset the runtime with:

```bash
docker compose down -v --remove-orphans
```

This Compose file is not the production live-trading deployment.

## Live topology

- Frontend and backend run as separate processes behind HTTPS ingress or a
  reverse proxy.
- PostgreSQL is the durable source of truth and coordination dependency.
- API and worker can run as multiple replicas.
- The worker is required for scheduled autonomous cycles and durable outbox
  work; FastAPI alone is not a complete live deployment.
- Live installation and the mode-specific credential matrix are maintained in
  [LIVE.md](LIVE.md).

## Live configuration boundary

LIVE requires `DEMO_MODE=false` and the common settings in `LIVE.md`.

- `AUTO_BOUNDED` uses the backend Binance Spot API with a dedicated
  `BINANCE_API_KEY` and `BINANCE_API_SECRET`. It does not require per-order
  human approval, Codex OAuth, or `TOKEN_ENCRYPTION_KEY` for its readiness path.
- `HUMAN_APPROVAL` uses Codex App Server and Binance Agent OS MCP. It requires
  `TOKEN_ENCRYPTION_KEY` for persisted connection/OAuth material and genuine
  Codex-managed Binance Agent OS OAuth. It does not use
  `BINANCE_API_KEY`/`BINANCE_API_SECRET` as its primary write transport.
- `CODEX_WRITE_CONFIRMATION_VERIFIED=false` remains required until a real
  operator manually verifies the live write elicitation contract.
- Telegram is optional and must be configured as one complete four-value
  group. Notification delivery is not financial authorization.

## Release checks

Before a live deployment, provision PostgreSQL, run the migrations once, start
both API and worker processes, and verify health, owner authentication, mode
configuration, and durable activity state. Keep live acceptance status honest:
implementation is not evidence of authenticated provider or funded execution.

```bash
cd backend
uv sync --frozen
cp .env.example .env
PYTHONPATH=src uv run alembic upgrade head
PYTHONPATH=src uv run uvicorn darwinspot.main:app --host 0.0.0.0 --port 8000
```

In a separate process:

```bash
cd backend
PYTHONPATH=src uv run python -m darwinspot.worker
```

Frontend build/start is documented in [LIVE.md](LIVE.md).

## Failure and rollback

If Codex exits or authentication expires, keep the worker alive, mark the
transport unavailable, retry bounded work, and block writes. If a request may
have crossed an external write marker, reconcile before retry. Never roll back
durable financial state by deleting intents or order events.

Never log bot tokens, OAuth codes, bearer credentials, cookies, owner passwords,
or Codex credential material.
