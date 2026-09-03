# DarwinSpot submission copy

## One-line description

DarwinSpot is an owner-operated Binance Agent OS spot-trading agent whose model proposes typed actions while the backend enforces one visible rolling 24-hour buy budget, durable order intent, idempotency, reconciliation, and an emergency stop.

## Short description

DarwinSpot connects one owner to one dedicated Binance Agent OS Agentic sub-account for spot trading. The agent reads live market and account evidence, selects one spot pair explicitly listed in the owner mandate, and returns one typed `HOLD`, `BUY`, `SELL`, `CANCEL`, or `CANCEL_REPLACE` decision. The backend—not the model—calculates buy notional, reserves the rolling 24-hour budget, builds the Binance Spot order payload, records durable intent, reconciles uncertain submissions, and keeps every decision linked to evidence and exchange state.

The UI exposes only `Available Budget` and `Spent Amount` as budget usage values. The owner can use `READ_ONLY`, `APPROVAL_REQUIRED`, or `AUTO_BOUNDED`, and can activate an emergency stop that blocks new submissions and requests cancellation of known DarwinSpot orders.

## Full description

Unbounded AI trading prompts are not execution boundaries. DarwinSpot separates the model decision from the trusted execution boundary:

- Binance Agent OS is connected through its official MCP Streamable HTTP endpoint and OAuth authorization-code flow with PKCE.
- Tool names and input schemas are discovered from the connected MCP server; unsupported or ambiguous capabilities fail closed.
- The model chooses one exact uppercase spot pair from the pairs written in the mandate. The backend rejects a pair not explicitly present in the mandate and fetches market data and symbol filters for that selected pair.
- Buy spending is governed by one rolling 24-hour budget. `Spent Amount` is verified buy fills from the previous 24 hours plus quote value committed to open buy orders. Sells and cancellations do not consume the budget.
- Limit buys use backend-computed `quantity × price`. Market buys use backend-computed `quoteOrderQty` as the spending ceiling and never send `quantity` together with it. Market sells send `quantity` only.
- Decimal values are serialized safely, `None`/`null` fields are omitted, and Binance Spot identifiers use `newClientOrderId`, `orderId`, and `origClientOrderId` according to the discovered tool schema.
- Durable trade intents are created before submission. Submission ambiguity becomes `SUBMISSION_UNKNOWN` and is reconciled by the stored Binance order identifier or idempotency key before another action is allowed.
- The owner emergency stop blocks new submissions and requests cancellation of known open DarwinSpot orders.
- No withdrawals, external transfers, futures, margin, leverage, options, bridging, liquidity pools, social feeds, arbitrary browsing, paper orders, fabricated fills, or profitability promise is included.

## Replication guide

### Prerequisites

- Python 3.14.7
- uv 0.12.9
- Node.js 24.20.0
- pnpm 11.25.0
- PostgreSQL
- One Binance account with a dedicated Agentic sub-account
- Binance Agent OS access with the least required scopes: Account, Market data, and Spot Trade only when live execution is intentionally enabled

### 1. Configure the backend

From `backend/`:

```bash
cp .env.example .env
uv sync --frozen
```

Set these values in the server-side environment only:

- `DATABASE_URL` — PostgreSQL connection string
- `OPENAI_API_KEY` — backend-only model key
- `OPENAI_MODEL` — selected OpenAI model
- `BINANCE_AGENT_OS_MCP_URL` — `https://agent.binance.com/mcp/agentic`
- `TOKEN_ENCRYPTION_KEY` — Fernet key generated outside the repository
- `OWNER_PASSWORD_HASH` — Argon2id hash generated outside the repository
- `FRONTEND_ORIGIN` — exact HTTPS frontend origin
- `AGENT_CYCLE_SECONDS` — scheduled cycle interval
- `LOG_LEVEL` — logging level

Apply the schema as a bounded release step:

```bash
uv run alembic upgrade head
```

### 2. Configure the frontend

From `frontend/`:

```bash
cp .env.example .env.local
pnpm install --frozen-lockfile
```

Set `BACKEND_URL` to the HTTPS backend origin. Keep all backend secrets out of the frontend environment. `NEXT_PUBLIC_APP_NAME` may remain `DarwinSpot`.

### 3. Start the services

Run the API and worker as separate processes from the backend image:

```bash
uv run uvicorn darwinspot.main:app --host 0.0.0.0 --port 8000
uv run python -m darwinspot.worker
```

Run the frontend through the deployment platform using the production `start` entrypoint after its deployment build has been performed by the release operator.

### 4. Verify the connection before enabling execution

1. Confirm `GET /health/live` returns `200`.
2. Confirm `GET /health/ready` returns `200` only after PostgreSQL and required backend secrets are available.
3. Sign in as the owner and confirm CSRF-protected mutations work.
4. Choose **Connect Binance Agent OS** and complete the official Binance authorization page.
5. Inspect the discovered MCP capabilities. Keep only Account, Market data, and Spot Trade scopes needed by the mandate.
6. Confirm a live market read, live account balance read, live open-order read, live trade-history read, and live exchange-info/symbol-filter read.
7. Configure all four mandate sections: assets, entry rules, sizing rules, and exit rules.
8. Configure the rolling 24-hour budget and begin in `READ_ONLY`.
9. Review the selected pair and live evidence. Use `APPROVAL_REQUIRED` before any first live order.
10. If live execution is intentionally authorized, use a dedicated, deliberately small allocation and independently verify the resulting Binance order and fills.
11. Exercise over-budget rejection and emergency stop only with owner authorization and a controlled live account state.

### 5. Operational recovery

- If Agent OS becomes unavailable, the connection is marked unavailable and new execution is blocked.
- If an order submission outcome is uncertain, do not blindly retry. Reconciliation must first resolve the stored Binance order ID or client idempotency key.
- If cancellation is uncertain, keep the intent in `CANCEL_PENDING` until a terminal exchange state is observed.
- Keep PostgreSQL shared across API and worker replicas; do not rely on process-local trading state.
- Keep all logs free of credentials, access tokens, authorization headers, and account secrets.

## Demo flow

1. Explain why an unbounded prompt is not an execution boundary.
2. Connect the dedicated Binance Agent OS account and show discovered capability state.
3. Show the four-part mandate, operating mode, `Available Budget`, and `Spent Amount`.
4. Run one authorized cycle with live timestamps and show the typed decision, evidence, budget result, durable intent, and independently verified Binance order state.
5. Show a deterministic over-budget rejection.
6. Activate emergency stop and show cancellation/reconciliation outcomes.
7. Close with: “The agent can act. The model does not control its own budget. Every action is provable and revocable.”

## Evidence boundary

This source package does not contain credentials, account data, synthetic orders, fabricated fills, or a public deployment. Official Binance Agent OS authentication, live capability discovery, account reads, and any live order remain owner-operated validation steps.

## Submission links

- GitHub: `GITHUB_URL_HERE`
- Video: `VIDEO_URL_HERE`

## X reply draft

DarwinSpot gives one Binance Agent OS-connected spot agent room to act inside a visible rolling buy budget. The model proposes; deterministic backend code enforces backend-computed notional, idempotency, and reconciliation. Every decision has live evidence, and the owner can stop new execution. `GITHUB_URL_HERE` `VIDEO_URL_HERE`
