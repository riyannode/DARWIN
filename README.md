# DARWIN

DARWIN is an owner-operated Binance Spot trading agent. The owner supplies a **Trading Mandate** and deterministic risk limits; DARWIN's custom `AgentRuntime` selects a pair and returns a typed `BUY`, `SELL`, or `HOLD` decision. The backend—not the model or frontend—authorizes every possible financial write.

## Judge Quickstart — zero credentials

Requirements: Git, Docker Engine, and Docker Compose v2.

```bash
git clone https://github.com/riyannode/DARWIN.git
cd DARWIN
docker compose up --build
```

Open [http://localhost:3000/demo](http://localhost:3000/demo). This local Docker route remains the canonical reproducible judge path.

A stable walkthrough is available on [YouTube](https://youtu.be/HrpbPH4EQ4w). It is a demonstration reference, not a replacement for the local reproducible path.

The checked-in root `docker-compose.yml` is deliberately the **JUDGE DEMO** profile:

- no `.env`, model-provider credential, Binance credential, Codex authentication, Telegram configuration, or funded account is required;
- Alembic runs against local SQLite, then the backend and frontend start;
- deterministic synthetic Binance-format fixtures replace external market/account/model providers;
- no external LLM call or Binance connection occurs; and
- `DEMO_MODE=true` blocks financial writes before an order, cancellation, transfer, or withdrawal transport can be reached.

The demo exposes three backend-computed scenarios:

| Scenario | Model decision | Deterministic result | System outcome |
| --- | --- | --- | --- |
| `valid-buy` | `BUY BTCUSDT` | `PASS` | `SKIPPED / DEMO_EXECUTION_BLOCKED` |
| `max-notional` | `BUY SOLUSDT` | `REJECTED / MAX_ORDER_NOTIONAL` | `SKIPPED` |
| `hold` | `HOLD ETHUSDT` | `NOT_APPLICABLE` | `SKIPPED / NO_TRADE` |

Stop and reset only this demo runtime:

```bash
docker compose down -v --remove-orphans
```

## Runtime profiles

| Profile | Required flags | Evidence and write behavior |
| --- | --- | --- |
| **JUDGE DEMO** | `DEMO_MODE=true`, `FINANCIAL_WRITES_ENABLED=false`, `PUBLIC_SHOWCASE_ENABLED=false` | Synthetic, zero credentials, no external LLM, no Binance connection, no financial writes. The judge route is `/demo`. |
| **PUBLIC LIVE SHOWCASE** | `DEMO_MODE=false`, `FINANCIAL_WRITES_ENABLED=false`, `PUBLIC_SHOWCASE_ENABLED=true` | Real model inference and real Binance evidence are persisted by the scheduled worker and projected read-only at `/showcase`. Financial writes stop before an intent or proposal is created. |
| **REAL LIVE TRADING** | `DEMO_MODE=false`, `FINANCIAL_WRITES_ENABLED=true`, normally `PUBLIC_SHOWCASE_ENABLED=false` | Operator-controlled execution remains subject to deterministic authorization, fresh revalidation, reconciliation, and the configured execution mode. |

`FINANCIAL_WRITES_ENABLED` is enforced twice: as safe-live admission closure after evidence/model/policy evaluation (before intent creation) and again immediately before an external financial write. It never bypasses the Trading Mandate, policy, budget, emergency stop, freshness, idempotency, or applicable mode-specific authorization and transport checks. `DEMO_MODE=true` always wins.

The repository contains no production deployment manifest or permanent hosted-runtime URL. `/showcase` is a deployment-relative public route, available only when the PUBLIC LIVE SHOWCASE profile is intentionally enabled. A currently available [temporary public read-only showcase](https://velvet-dow-milwaukee-commitment.trycloudflare.com/showcase) is provided through Cloudflare Tunnel; it is not a permanent production deployment and may expire.

## Interfaces and routes

The Next.js application has one shell with these routes:

| Route | Surface | Access |
| --- | --- | --- |
| `/demo` | deterministic judge walkthrough | public only in JUDGE DEMO |
| `/showcase` | stored safe-live evidence and recent decisions | public only in PUBLIC LIVE SHOWCASE |
| `/` | account overview, allocation, live balances, and latest decision | owner control panel |
| `/agent` | Trading Mandate, mode, start/stop, and run-once controls | owner control panel |
| `/budget` | rolling 24-hour BUY budget | owner control panel |
| `/activity` | decision, intent, order-event, and audit timeline | owner control panel |
| `/settings` | Binance Agent OS/Codex status, direct Spot status, and Configured Universe | owner control panel |

Owner mutations require an owner session and CSRF validation. The public showcase is a separate read-only projection; it excludes sessions, credentials, OAuth material, Telegram identifiers, provider headers, private balances, and hidden reasoning.

## Current architecture

DARWIN uses a custom `AgentRuntime`; Pydantic is used for typed model-output validation, not as an agent framework.

1. The worker computes the **Effective Universe** from the **Configured Universe** ∩ **Allowed Symbols** ∩ currently valid Binance Spot/USDT symbols with required filters.
2. It scans every effective candidate with bounded closed `15m` and `1h` OHLCV evidence, then `AgentRuntime.choose_pair()` selects one pair.
3. The final model call receives only selected-pair evidence: current ticker, closed `15m`/`1h`/`4h` history, balances, open orders, recent activity, filters, Trading Mandate, policy, and budget.
4. `AgentRuntime.decide()` validates a typed `BUY`, `SELL`, or `HOLD` object with confidence, rationale, supporting factors, and risk factors.
5. Deterministic backend policy evaluates symbols, per-trade notional, 24-hour BUY budget, active workflows, balances, Binance filters, evidence freshness, open-order conflict, and emergency stop.
6. A permitted actionable decision either creates durable work for the selected mode or completes as a safe no-write outcome when the global write gate is closed.

The OpenAI SDK supports direct OpenAI or an OpenAI-compatible endpoint through `OPENAI_BASE_URL`. A malformed or schema-invalid model response fails closed after one correction attempt.

For the full contract, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Trading universe

A newly created **Configured Universe** bootstraps to:

```text
BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT
```

A database upgraded from before migration `0004_dual_execution_and_universe` can retain that migration's four-symbol compatibility value (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`) until its owner updates the persisted universe. Review it explicitly after upgrade.

The universe is configurable by an owner to up to 100 uppercase Spot/USDT symbols. New symbols are checked against current Binance Spot metadata and required filters before being saved. A configured symbol is not automatically authorized by a Trading Mandate.

```text
Effective Universe = Configured Universe ∩ Allowed Symbols ∩ live-valid Binance Spot/USDT symbols
```

The bootstrap five are neither a dynamic ranking nor a five-pair runtime limit.

## Execution modes

| Mode | Authorization | Transport | Per-order human approval |
| --- | --- | --- | --- |
| `AUTO_BOUNDED` | `AUTO_POLICY` after deterministic policy and fresh revalidation | direct, backend-only **Binance Spot API** | no |
| `HUMAN_APPROVAL` | durable Telegram or web approval, then fresh revalidation | Codex App Server + **Binance Agent OS** MCP | yes |

Both paths use the same policy, account-scoped execution lock, idempotency key, final write marker, reconciliation, and audit trail. Codex does not decide trades and does not override backend policy. `AUTO_BOUNDED` does not require Codex OAuth or Telegram approval.

## Safety model

- Spot only: no futures, margin, leverage, options, transfers, or withdrawals.
- A `SELL` can sell only a held Spot asset; it cannot open a short position.
- The backend evaluates budget, balances, filters, freshness, open-order conflict, and emergency stop before a write can be considered.
- New ordinary work is blocked by emergency stop. Model cancellation and direct web cancellation are disabled; emergency-stop cancellation is reconciled through the worker.
- Financial writes use durable intent state, idempotency, an external-call marker, and reconciliation. `SUBMISSION_UNKNOWN` is reconciled before any retry; a marker never proves success.
- Telegram is notification and an optional HUMAN_APPROVAL delivery channel, not authorization for `AUTO_BOUNDED`.

## Verification status

| Claim | Status |
| --- | --- |
| Docker JUDGE DEMO, all three demo scenarios, and zero durable `agent_runs`/`trade_intents` rows | **VERIFIED** in a fresh non-financial Compose run |
| Chromium `/demo` rendering and scenario selection | **VERIFIED** in the same fresh run |
| Unauthenticated Chromium shell routes `/`, `/agent`, `/budget`, `/activity`, and `/settings` | **VERIFIED**; protected APIs correctly returned `401` and no mutation was attempted |
| Public-enabled `/showcase` Chromium rendering | **VERIFIED** |
| Custom AgentRuntime, typed validation, dual transports, policy, persistence, reconciliation, and public projection | **IMPLEMENTED** |
| Funded `AUTO_BOUNDED` live order | **NOT VERIFIED** |
| Authenticated `HUMAN_APPROVAL` Codex/Binance Agent OS acceptance | **PENDING / NOT VERIFIED** |

See [docs/DEMO.md](docs/DEMO.md), [docs/LIVE.md](docs/LIVE.md), [docs/RUNBOOK.md](docs/RUNBOOK.md), and [docs/SUBMISSION.md](docs/SUBMISSION.md) for reproduction and reviewer detail.
