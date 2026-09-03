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

# Use the latest PR #2 branch from the upstream repository.
git remote add upstream https://github.com/riyannode/DARWIN.git
git fetch upstream pull/2/head:darwinspot-pr-2
git switch darwinspot-pr-2

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

## Demo

[Video demo — link pending](VIDEO_DEMO_URL)

No hosted application URL is required by the hackathon submission. The repository, replication guide, and demo video are the primary Track A deliverables.

## Security and live-use boundary

Use credentials belonging to the operator running the fork. Keep `backend/.env` outside git and never put backend secrets in `frontend/.env` or a client bundle. Start in `READ_ONLY`, inspect the real Agent OS capabilities and timestamps, and enable execution only after deliberately configuring the mandate, budget, permissions, and operating mode.
