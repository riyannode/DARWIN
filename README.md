# DarwinSpot

DarwinSpot is an owner-operated autonomous **Binance Spot trading agent** built on Binance Agent OS. It turns live market, symbol, account, and order evidence into typed decisions while keeping the final execution controls in the backend: durable intent, idempotency, reconciliation, a rolling budget, and an emergency stop.

## Why it fits Track A — Trading Workflows

DarwinSpot is built for the **Binance Agent OS Mini Hackathon, Track A — Build an AI agent with Agent OS**, with the theme **Trading Workflows**. The agent uses the official Binance Agent OS MCP endpoint for live exchange capabilities and demonstrates a bounded workflow from evidence collection to a typed Spot action:

```text
live Agent OS evidence
        ↓
LLM pair selection and decision
        ↓
backend validation + mandate + budget guard
        ↓
READ_ONLY / approval / bounded execution
        ↓
durable intent + Binance reconciliation + activity evidence
```

## Architecture

- **Frontend** — Next.js production UI for owner login, connection state, mandate, budget, agent mode, portfolio, emergency stop, and activity/evidence views.
- **Backend API** — FastAPI application that owns authentication, authorization, validation, budget enforcement, durable state, idempotency, reconciliation, and emergency-stop behavior.
- **Worker** — separate bounded Python process that claims scheduled runs, calls the agent cycle, retries only transient failures with backoff, and persists run state.
- **PostgreSQL** — durable database for owner sessions, Agent OS OAuth material, mandates, budgets, runs, trade intents, and order events.
- **Binance Agent OS** — official MCP integration for authorized market/account/trading capabilities. DarwinSpot does not ask for a Binance API key in the browser and does not handle withdrawals or transfers.
- **LLM** — existing OpenAI SDK with either direct OpenAI or an optional OpenAI-compatible gateway such as 9Router. The backend sends the API key; it is never a frontend setting.

## Guardrails and core features

- `READ_ONLY`, `APPROVAL_REQUIRED`, and `AUTO_BOUNDED` operating modes.
- A simple rolling 24-hour budget represented by **Available Budget** and **Spent Amount**.
- Backend-owned mandate and budget validation; client controls are not authorization.
- Durable submission intent, idempotency, exchange reconciliation, and explicit handling of uncertain submissions.
- Global emergency stop and a chronological activity/evidence trail.
- Explicit LLM configuration and response validation. Invalid configuration or malformed/schema-invalid model responses fail; DarwinSpot does not silently switch provider or model.
- Direct OpenAI by default, or 9Router through `OPENAI_BASE_URL` without adding a provider dependency.

## Quick Start

The full fork, configuration, migration, Agent OS, operating-mode, health-check, troubleshooting, and shutdown procedure is in the [Judge Replication Runbook](docs/RUNBOOK.md).

```bash
git clone https://github.com/YOUR_GITHUB_USERNAME/DARWIN.git
cd DARWIN

# The judge replication guide is on main after PR #2 is merged.
git status --short --branch

cp backend/.env.example backend/.env
chmod 600 backend/.env
```

Then follow `docs/RUNBOOK.md` to install the locked dependencies, create PostgreSQL state, set the owner password and your own LLM/Agent OS credentials, run the migration, and start the three application processes.

## LLM choices

Direct OpenAI is the default when `OPENAI_BASE_URL` is unset. For 9Router, use the model shown by that gateway's `/v1/models` endpoint:

```dotenv
OPENAI_BASE_URL=http://localhost:20128/v1
OPENAI_API_KEY=<your key from the 9Router dashboard>
OPENAI_MODEL=<a model available in the 9Router dashboard>
```

When DarwinSpot runs in a container, `localhost` points to that container. Use a 9Router hostname reachable from the backend container instead.

## Verification status

Verified in this workspace: locked backend/frontend dependency installation, production frontend build, PostgreSQL migration, backend `/health/live` and `/health/ready`, frontend route responses, owner login/session, and the local 9Router `/v1/models` catalog. A clean-fork replication, full public HTTPS Binance Agent OS OAuth flow, live LLM completion, and live order have not been verified here.

## Project sources

- [Binance Agent OS Mini Hackathon announcement](https://x.com/binance/status/2094810011557838988)
- [Binance submission survey](https://app.binance.com/uni-qr/user-survey/2913aa200aac462c89a737779393f3d4)
- [9Router source](https://github.com/decolua/9router)

## Demo

Video demo: pending before submission.

No hosted application URL is required by the hackathon submission. The repository, replication guide, and demo video are the primary Track A deliverables.

## Local demo and full Agent OS OAuth

The local replication path is a local build/health/UI demonstration. It binds the backend and frontend to loopback and does not claim that the official Binance Agent OS OAuth flow is complete.

The full Agent OS OAuth path is separate: it requires a public **HTTPS** `FRONTEND_ORIGIN`, with both `/.well-known/darwinspot-oauth-client.json` and the OAuth callback publicly reachable on that same origin. A `127.0.0.1` or plain HTTP origin is suitable for the local demo only, not for full public OAuth.

Use credentials belonging to the operator running the fork. Keep `backend/.env` outside git and never put backend secrets in `frontend/.env` or a client bundle. Start in `READ_ONLY`, inspect the real Agent OS capabilities and timestamps, and enable execution only after deliberately configuring the mandate, budget, permissions, and operating mode.
