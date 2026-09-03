# DarwinSpot

DarwinSpot is a clean-room, owner-operated autonomous spot trading agent for Binance Agent OS. It uses one rolling 24-hour buy budget and exposes only **Available Budget** and **Spent Amount** as budget usage metrics. The model proposes a typed action; the backend owns durable intent, idempotency, exchange reconciliation, and the emergency stop.

This repository contains only `backend/`, `frontend/`, and `docs/` as source directories. It does not contain real credentials, Binance account data, fake orders, fabricated fills, or public deployment configuration.

## Local setup

1. Install Python 3.14.7, uv 0.12.9, Node.js 24.20.0, and pnpm 11.25.0.
2. Copy the two `.env.example` files to local `.env` files and provide real secrets outside git. `OWNER_PASSWORD_HASH` must be an Argon2id hash. Never place an API key in the frontend environment.
3. From `backend/`, run `uv sync --frozen` and `uv run alembic upgrade head` against PostgreSQL.
4. From `frontend/`, run `pnpm install --frozen-lockfile` and `pnpm build`.
5. Run the API and worker as separate processes using the commands in `docs/RUNBOOK.md`. Do not enable trading until the read-only Agent OS connection and emergency stop have been verified.

## Product boundary

Spot only. No futures, margin, leverage, options, withdrawals, transfers, bridging, liquidity pools, copy trading, public research loop, multi-agent council, or profitability promise. Binance Agent OS is reached through its official MCP endpoint; DarwinSpot does not invent an OAuth client-secret flow.

## Event-window change log

DarwinSpot was created as a new project for the Binance Agent OS Mini Hackathon Track A. It is not a patch or resubmission of DarwinLP. The separate prior work is disclosed in `docs/SUBMISSION.md`.

## Validation status

The source-level review boundary and live-validation prerequisites are recorded in
`docs/RUNBOOK.md`; the production topology and release gates are in
`docs/DEPLOYMENT.md`. Live Agent OS authentication, account data, and an order
require owner-provided credentials and explicit financial authorization. They are
not performed by this workspace task.
