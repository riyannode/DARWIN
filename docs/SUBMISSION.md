# DARWIN — Binance Agent OS Mini Hackathon, Track A

## Positioning

DARWIN is an autonomous Binance Spot trading agent with a visible, deterministic authority boundary. An owner configures a high-level **Trading Mandate**, **Allowed Symbols**, **Max Per Trade**, **24h Trading Budget**, **Max Concurrent Trades**, a **Configured Universe**, and an execution mode. DARWIN decides what, when, and how to trade only within those backend-enforced limits.

## What is implemented

- A custom DARWIN `AgentRuntime`, built on the OpenAI SDK, supports direct OpenAI or an OpenAI-compatible endpoint through `OPENAI_BASE_URL`.
- Pair selection and final `BUY`/`SELL`/`HOLD` decisions are validated as strict Pydantic models. The decision includes confidence, rationale, supporting factors, and risk factors.
- A newly created Configured Universe bootstraps to `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, and `XRPUSDT` and accepts up to 100 validated Spot/USDT symbols. A database upgraded from before `0004_dual_execution_and_universe` can retain the migration's four-symbol compatibility value (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`) until an owner updates it.
- The Effective Universe is `Configured Universe ∩ Allowed Symbols ∩ live-valid Binance Spot/USDT symbols`.
- The worker scans all effective candidates, selects one pair, records selected-pair evidence, and applies deterministic policy before any execution work.
- `AUTO_BOUNDED` uses the direct, backend-only **Binance Spot API**. `HUMAN_APPROVAL` uses explicit Telegram or web approval and **Binance Agent OS** through Codex App Server + MCP.
- The backend owns policy, budget, balances, filters, freshness, open-order conflict, emergency stop, idempotency, external-call uncertainty, reconciliation, and the financial-write gate. The model and Codex cannot override those controls.

## Safety boundary

DARWIN is Spot-only. It does not support futures, margin, leverage, options, transfers, or withdrawals. A `SELL` only sells a held Spot asset; it cannot open a short position.

A financial write requires the configured mode's authorization plus fresh revalidation. Durable intent state, an idempotency key, a pre-call marker, and reconciliation protect against duplicate or ambiguous submission. `SUBMISSION_UNKNOWN` is reconciled before retry. Emergency stop blocks ordinary new work and routes any necessary cancellation through durable reconciliation.

## Judge material

| Material | Location |
| --- | --- |
| Source | [github.com/riyannode/DARWIN](https://github.com/riyannode/DARWIN) |
| Stable demo video | [YouTube — DARWIN: Autonomous Binance Spot Agent](https://youtu.be/HrpbPH4EQ4w) |
| Canonical reproducible Judge Demo | `docker compose up --build` → [http://localhost:3000/demo](http://localhost:3000/demo) |
| Temporary public read-only showcase | [Cloudflare Tunnel `/showcase`](https://velvet-dow-milwaukee-commitment.trycloudflare.com/showcase) — temporary, not a permanent production deployment |
| Public showcase contract | deployment-relative `/showcase`, only with `DEMO_MODE=false`, `FINANCIAL_WRITES_ENABLED=false`, and `PUBLIC_SHOWCASE_ENABLED=true` |
| Architecture and review contract | [ARCHITECTURE.md](ARCHITECTURE.md) |
| Replication and operating commands | [LIVE.md](LIVE.md) and [RUNBOOK.md](RUNBOOK.md) |

The YouTube video is the stable demo reference. The Cloudflare Tunnel is a currently available public read-only showcase and may expire; it is not the canonical reproducible demo path or a permanent production endpoint. Judges can always reproduce the judge demo locally.

## Verification status

| Claim | Status |
| --- | --- |
| Zero-credential Docker judge demo and deterministic no-write behavior | **IMPLEMENTED BUT NOT VERIFIED** by a fresh runtime exercise in this documentation-only review |
| `/demo` and public-enabled `/showcase` Chromium rendering | **IMPLEMENTED BUT NOT VERIFIED** by a fresh Chromium exercise in this documentation-only review |
| AgentRuntime, Pydantic validation, direct Spot adapter, Binance Agent OS/Codex transport, policy, durable state, and reconciliation | **IMPLEMENTED** |
| Funded `AUTO_BOUNDED` order | **NOT VERIFIED** |
| Authenticated `HUMAN_APPROVAL` Binance Agent OS/Codex acceptance | **PENDING / NOT VERIFIED** |
| Full owner-control-panel browser acceptance | **NOT VERIFIED** |

The judge demo is synthetic: it has no external LLM, Binance connection, or financial write. The PUBLIC LIVE SHOWCASE is real-model/real-market/read-only evidence; it is not a claim of funded live trading.
