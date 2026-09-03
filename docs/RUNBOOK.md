# Runbook

## Setup

From `backend/`: `uv sync --frozen`, set secrets from `.env.example`, then run `uv run alembic upgrade head`. Start the API with `uv run uvicorn darwinspot.main:app --host 127.0.0.1 --port 8000`. Start the worker separately with `uv run python -m darwinspot.worker`. Both are persistent processes and must be stopped after local verification.

From `frontend/`: `pnpm install --frozen-lockfile`, then `BACKEND_URL=http://127.0.0.1:8000 pnpm build`. A temporary `pnpm dev` process is only for visual review and must be stopped afterward.

## Readiness sequence

1. Confirm `/health/live`.
2. Confirm `/health/ready` only after database and required backend secrets are present.
3. Sign in as owner; mutations require the CSRF cookie/header pair.
4. Confirm `/.well-known/darwinspot-oauth-client.json` is publicly reachable on the exact frontend origin.
5. Connect Agent OS through the official OAuth authorization flow and inspect returned tool descriptors.
6. Confirm real balance and market timestamps before any order.
7. Configure mandate and budget, then start `AUTO_BOUNDED` only with a deliberately small dedicated allocation.
8. Independently confirm any order in Binance, then exercise an over-budget rejection and emergency stop.

## Validation boundary

This source package intentionally contains no automated test suite. No test suite
or production build is executed as part of this source-preparation task. Static
review is limited to source inspection, AST parsing, dependency/lockfile review,
and order-flow reasoning.

The P0 UI includes live allocation valuation, live open orders, agent start/stop/
run-once controls, a global emergency-stop control, activity filters, expandable
exchange evidence, and owner approval for `PROPOSED` intents in
`APPROVAL_REQUIRED`. The budget meter derives its display from Available Budget
and Spent Amount; it does not use a fixed or seeded value.

## Live validation still required

- Install the locked backend and frontend dependencies in the target environment.
- Apply the Alembic migration to PostgreSQL.
- Inject owner-provided backend secrets through the deployment secret store.
- Complete the official Binance Agent OS OAuth flow and inspect returned tool descriptors.
- Confirm live market, balance, symbol-filter, order-status, and cancellation responses.
- Confirm any authorized order independently in Binance; an order submission is not settlement.

## Safety

Never put secrets in `frontend/.env`, never use withdrawals or transfers, never retry `SUBMISSION_UNKNOWN` blindly, never claim a fill from model/UI output, and never enable live trading without owner authorization.
