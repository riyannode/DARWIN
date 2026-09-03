# DarwinSpot deployment guide

This guide describes the production shape required by the approved PRD. The build task does not deploy or enable trading.

## Production topology

- Deploy `backend/` and `frontend/` as separate services.
- Build the backend image once, then run it with two finite entry commands: the HTTP API and the worker.
- Use PostgreSQL as the only stateful service. Do not use the default SQLite URL in production.
- Serve all public traffic over HTTPS and set `FRONTEND_ORIGIN` to the exact deployed frontend origin.
- Keep `/.well-known/darwinspot-oauth-client.json` publicly reachable on that frontend origin; it is the URL-based OAuth client metadata document used by Binance Agent OS.
- Inject secrets through the hosting platform. Never place backend secrets in the frontend environment or client bundle.

## Release sequence

1. Build the backend image from `backend/` with the locked `pyproject.toml` and `uv.lock`.
2. Build the frontend from `frontend/` with `BACKEND_URL` set to the HTTPS backend origin.
3. Provision PostgreSQL and inject the backend variables from `backend/.env.example` through the host secret store.
4. Run the migration as a bounded release step, once per release:

   ```text
   uv run alembic upgrade head
   ```

5. Start the backend API with the command in `backend/Dockerfile` and start the worker from the same image with:

   ```text
   python -m darwinspot.worker
   ```

6. Start the frontend with the command in `frontend/Dockerfile`.
7. Confirm the readiness gates below before connecting Binance Agent OS or enabling autonomous operation.

## Readiness gates

Deployment is not ready until all of these are verified against the deployed services:

- `GET /health/live` returns `200`.
- `GET /health/ready` returns `200` after PostgreSQL, `OWNER_PASSWORD_HASH`, `OPENAI_API_KEY`, and `TOKEN_ENCRYPTION_KEY` are injected.
- The frontend loads the real backend connection and agent state; no seeded balances or orders appear.
- The official Binance Agent OS OAuth flow completes and returned capabilities are inspected.
- The OAuth metadata document and callback use the same deployed frontend origin, and Binance's `S256` PKCE flow completes.
- One read-only market and account fetch returns live timestamps.
- The emergency stop blocks new submissions and reports each cancellation outcome.
- No secret, token, account identifier, or authorization header appears in client bundles or logs.
- Trading remains disabled until the owner deliberately configures the mandate, budget, connection permissions, and operating mode.

## Rollback and operations

- Keep migration execution separate from API and worker startup. Roll back the application image only after confirming schema compatibility; the initial migration has a reversible downgrade for a controlled maintenance window.
- If Agent OS becomes unavailable, leave the connection unavailable and do not substitute cached or synthetic exchange data for a new buy.
- If a submission is uncertain, preserve `SUBMISSION_UNKNOWN` and reconcile by the stored Binance order identifier or client idempotency key before any retry.
- Stop task-started validation servers, workers, tunnels, and temporary containers after verification. This repository task did not deploy a public service.
