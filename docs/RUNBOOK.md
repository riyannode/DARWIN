# DarwinSpot Judge Replication Runbook

This runbook reproduces DarwinSpot locally from the repository. It uses only operator-owned credentials, the official Binance Agent OS MCP endpoint, PostgreSQL, and either direct OpenAI or an OpenAI-compatible gateway such as 9Router.

## Verification boundary

Verified in this workspace: dependency installation, production frontend build, PostgreSQL migration, backend `/health/live` and `/health/ready`, frontend route responses, owner login/session, and the local 9Router `/v1/models` catalog. A clean-fork replication, full public HTTPS Binance Agent OS OAuth flow, live LLM completion, and live order have not been verified here.

The commands below are intended for a Linux host. Run the backend API, worker, and frontend in separate terminals. The API and worker commands include `PYTHONPATH=src` because this repository keeps Python source under `backend/src/`.

## 1. Fork and clone

Fork `https://github.com/riyannode/DARWIN` in GitHub, then clone your fork after PR #2 is merged:

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/DARWIN.git
cd DARWIN
```

Confirm the clone is on the default `main` branch:

```bash
git status --short --branch
```

Expected result: the branch is `main` and the working tree is clean.

## 2. Prerequisites

DarwinSpot's locked project versions are:

- Python `3.14.x` (`backend/pyproject.toml` requires `>=3.14,<3.15`)
- uv `0.12.9`
- Node.js `24.20.0`
- pnpm `11.25.0`
- PostgreSQL with a local database and role you can use for DarwinSpot

Check the installed tools:

```bash
python3 --version
uv --version
node --version
pnpm --version
psql --version
```

Start PostgreSQL using the operating system's documented method if it is not already running. Confirm a local connection:

```bash
pg_isready
```

## 3. Create the backend environment file

Copy the committed example. Keep this file local and mode `0600`:

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env
```

Generate values for the two DarwinSpot secrets that are not supplied by an external provider:

```bash
cd backend
uv sync --frozen
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
uv run python -c 'from getpass import getpass; from argon2 import PasswordHasher; print(PasswordHasher().hash(getpass("Owner password: ")))'
cd ..
```

Put the Fernet output in `TOKEN_ENCRYPTION_KEY`. Put the Argon2id output in `OWNER_PASSWORD_HASH`. The password entered for the hash is the owner password used by the DarwinSpot sidebar login.

Create a local PostgreSQL role and database if they do not already exist. Choose a local password and keep it only in the environment file or your local secret store:

```bash
read -rsp "PostgreSQL password: " DB_PASSWORD; printf '\n'
sudo -u postgres psql -c "CREATE ROLE darwinspot LOGIN PASSWORD '${DB_PASSWORD}';"
unset DB_PASSWORD
sudo -u postgres createdb -O darwinspot darwinspot
```

If the role or database already exists, do not run the create command again; use the existing connection details instead.

Set `DATABASE_URL` in `backend/.env` using the role, password, host, port, and database you created:

```dotenv
DATABASE_URL=postgresql+psycopg://darwinspot:<local-database-password>@127.0.0.1:5432/darwinspot
```

For the local demo, set the frontend origin to loopback:

```dotenv
FRONTEND_ORIGIN=http://127.0.0.1:3000
```

## 4. Configure direct OpenAI or 9Router

Edit only the backend environment file:

```bash
${EDITOR:-vi} backend/.env
```

For direct OpenAI, leave `OPENAI_BASE_URL` unset and set your own key and model:

```dotenv
OPENAI_API_KEY=<your OpenAI API key>
OPENAI_MODEL=<a model available to your OpenAI account>
# OPENAI_BASE_URL is intentionally unset for direct OpenAI.
```

For a local 9Router gateway, use its OpenAI-compatible endpoint and a model returned by its dashboard/API:

```dotenv
OPENAI_BASE_URL=http://localhost:20128/v1
OPENAI_API_KEY=<your key from the 9Router dashboard>
OPENAI_MODEL=<a model available in the 9Router dashboard>
```

Check the 9Router model catalog without making a completion request:

```bash
read -rsp "9Router API key: " ROUTER_API_KEY; printf '\n'
curl -sS -H "Authorization: Bearer ${ROUTER_API_KEY}" http://localhost:20128/v1/models
unset ROUTER_API_KEY
```

If DarwinSpot runs in Docker or another container, `localhost` means the DarwinSpot container itself. Set `OPENAI_BASE_URL` to the 9Router hostname and port reachable from that container. Do not copy 9Router source into DarwinSpot.

The backend validates the base URL, rejects empty key/model values, and fails explicitly on malformed or schema-invalid model responses. It does not silently fall back to another provider or model.

The local replication path is a local build/health/UI demonstration. It binds the backend and frontend to loopback and uses `FRONTEND_ORIGIN=http://127.0.0.1:3000`. It does not claim that the official Binance Agent OS OAuth flow is complete.

The full Agent OS OAuth path is separate: it requires a public **HTTPS** `FRONTEND_ORIGIN`, with both `/.well-known/darwinspot-oauth-client.json` and the OAuth callback publicly reachable on that same origin. A `127.0.0.1` or plain HTTP origin is suitable for the local demo only, not for full public OAuth.

## 5. Install dependencies

Backend, from the repository root:

```bash
cd backend
uv sync --frozen
cd ..
```

Frontend:

```bash
cd frontend
pnpm install --frozen-lockfile
cd ..
```

If pnpm 11 reports a blocked `unrs-resolver` postinstall build, approve only that named package and repeat the install:

```bash
cd frontend
pnpm approve-builds unrs-resolver
pnpm install --frozen-lockfile
cd ..
```

## 6. PostgreSQL and migration

Run the Alembic migration against the `DATABASE_URL` in `backend/.env`:

```bash
cd backend
PYTHONPATH=src uv run alembic upgrade head
cd ..
```

Expected final migration: `0002_oauth_and_event_dedupe`.

## 7. Build and run the application

Build the frontend with the backend rewrite target. This is a finite command and should finish before starting the production server:

```bash
cd frontend
BACKEND_URL=http://127.0.0.1:8000 pnpm build
cd ..
```

Open three terminals in the repository root.

**Terminal A — backend API:**

```bash
cd backend
PYTHONPATH=src uv run uvicorn darwinspot.main:app --host 127.0.0.1 --port 8000
```

**Terminal B — worker/agent:**

```bash
cd backend
PYTHONPATH=src uv run python -m darwinspot.worker
```

**Terminal C — frontend production:**

```bash
cd frontend
HOSTNAME=127.0.0.1 PORT=3000 pnpm start
```

The worker is a separate long-running process. It remains idle until the persisted agent configuration makes a scheduled run due; starting it does not submit an order.

## 8. Owner login

Open the frontend URL and use the **Owner session** form in the sidebar with the password used to create `OWNER_PASSWORD_HASH`:

```text
http://127.0.0.1:3000/
```

The login is sent to the backend at `/api/auth/login`. After signing in, reload the page and confirm that the overview and navigation data load.

Verify the authenticated backend session from the same machine if needed:

```bash
curl -i http://127.0.0.1:8000/api/auth/me
```

The curl request needs the session cookie from the browser; a `401` without that cookie is expected.

## 9. Connect Binance Agent OS

1. Sign in as the owner.
2. Open **Settings**.
3. Select **Connect Binance Agent OS**.
4. Open the official authorization URL shown by DarwinSpot.
5. Complete the Binance authorization and consent flow.
6. Return to the Settings page and confirm `CONNECTED` plus the discovered capabilities.

DarwinSpot uses the official MCP endpoint configured as `BINANCE_AGENT_OS_MCP_URL`. It stores encrypted session material and redacted capability metadata. It does not ask for a Binance API key in the frontend.

Confirm the public frontend metadata route before starting the authorization flow:

```bash
curl -i http://127.0.0.1:3000/.well-known/darwinspot-oauth-client.json
```

## 10. Configure mandate and rolling 24-hour budget

In the signed-in UI:

1. Open **Agent** and fill all four mandate sections: assets/universe, entry rules, sizing rules, and exit rules. Save the mandate.
2. Open **Budget** and set a positive rolling 24-hour budget.
3. Confirm the dashboard shows **Available Budget** and **Spent Amount**.
4. Keep the initial budget deliberately small for a live validation.

The frontend fields are presentation only. The backend validates the mandate, budget, ownership, and current persisted state.

## 11. Choose an operating mode

Start with the safest mode and move deliberately:

- **READ_ONLY** — collect and display live evidence without allowing order execution.
- **APPROVAL_REQUIRED** — create a proposed action that requires owner approval before execution.
- **AUTO_BOUNDED** — permit bounded execution only after the mandate, budget, connection, and Agent OS spot capability are all present.

Use the Agent page to select the mode. Confirm the displayed mode and connection state before running the agent. The global emergency stop remains available from the application shell.

## 12. Health checks and expected URLs

Backend:

```bash
curl -i http://127.0.0.1:8000/health/live
curl -i http://127.0.0.1:8000/health/ready
curl -i http://127.0.0.1:8000/docs
```

Expected: `/health/live` and `/health/ready` return HTTP `200` with a JSON status; `/docs` returns HTTP `200`.

Frontend routes:

```text
http://127.0.0.1:3000/
http://127.0.0.1:3000/agent
http://127.0.0.1:3000/budget
http://127.0.0.1:3000/activity
http://127.0.0.1:3000/settings
http://127.0.0.1:3000/demo
```

The frontend build also serves:

```text
http://127.0.0.1:3000/.well-known/darwinspot-oauth-client.json
```

Optional 9Router local gateway:

```text
http://localhost:20128/dashboard
http://localhost:20128/v1/models
```

## 13. Troubleshooting

### `ModuleNotFoundError: No module named 'darwinspot'`

Run backend commands with the source path from the backend directory:

```bash
cd backend
PYTHONPATH=src uv run uvicorn darwinspot.main:app --host 127.0.0.1 --port 8000
PYTHONPATH=src uv run python -m darwinspot.worker
```

### `address already in use`

Inspect the listener before changing ports:

```bash
ss -ltnp '( sport = :3000 or sport = :8000 )'
```

Stop only the process started for this replication, then rerun the relevant command.

### `/health/ready` returns `503`

Check that PostgreSQL is reachable and these backend values are populated: `DATABASE_URL`, `OWNER_PASSWORD_HASH`, `OPENAI_API_KEY`, and `TOKEN_ENCRYPTION_KEY`. Keep `OPENAI_BASE_URL` unset for direct OpenAI or set it to a valid reachable HTTP(S) gateway URL.

### Login returns `401`

Regenerate `OWNER_PASSWORD_HASH` from the exact password being entered. Confirm the backend process was restarted after changing `backend/.env`.

### Agent OS connection remains pending

Confirm the frontend metadata URL, `FRONTEND_ORIGIN`, `BINANCE_AGENT_OS_MCP_URL`, and `TOKEN_ENCRYPTION_KEY`. Complete the official authorization URL opened from Settings and wait for capability discovery.

### 9Router returns an unknown model or connection error

Query the gateway catalog and choose an exact returned model ID:

```bash
read -rsp "9Router API key: " ROUTER_API_KEY; printf '\n'
curl -sS -H "Authorization: Bearer ${ROUTER_API_KEY}" http://localhost:20128/v1/models
unset ROUTER_API_KEY
```

From a container, replace `localhost` with the reachable 9Router hostname. Do not use a provider/model fallback; fix the URL or model configuration explicitly.

### pnpm blocks a dependency build

Approve only the reported package, then reinstall:

```bash
cd frontend
pnpm approve-builds unrs-resolver
pnpm install --frozen-lockfile
```

## 14. Stop all services

When the demonstration is complete, stop each foreground process with `Ctrl+C` in its own terminal:

- frontend production server
- backend API
- DarwinSpot worker

If you intentionally launched a process in the background and recorded its PID, stop that exact PID:

```bash
kill <frontend-pid> <backend-pid> <worker-pid>
```

Leave a shared PostgreSQL service running if other local projects use it. Stop it only when it was started exclusively for this replication and your operating system's service policy permits it.

Final repository check:

```bash
git status --short --branch
```

The local `backend/.env` must remain untracked and must never be committed.
