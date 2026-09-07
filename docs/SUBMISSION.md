# DARWIN — Binance Agent OS Mini Hackathon, Track A

## Positioning

DARWIN is an owner-operated Binance Spot decision and execution runtime with two execution paths and a visible, deterministic authority boundary. `AUTO_BOUNDED` uses DARWIN's AgentRuntime for proposal generation; MCP-native `HUMAN_APPROVAL` uses an external MCP-compatible host for reasoning and proposal generation. The owner supplies a high-level **Trading Mandate**, deterministic limits, and an execution mode. DARWIN's backend authorizes every possible financial write.

## What is implemented

- The `AUTO_BOUNDED` path uses a custom DARWIN `AgentRuntime`, built on the OpenAI SDK, with direct OpenAI or an OpenAI-compatible endpoint through `OPENAI_BASE_URL`.
- Pair selection and final `BUY`/`SELL`/`HOLD` decisions are validated as strict Pydantic models. The decision includes confidence, rationale, supporting factors, and risk factors.
- A newly created Configured Universe bootstraps to `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, and `XRPUSDT` and accepts up to 100 validated Spot/USDT symbols. A database upgraded from before `0004_dual_execution_and_universe` can retain the migration's four-symbol compatibility value (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`) until an owner updates it.
- The Effective Universe is `Configured Universe ∩ Allowed Symbols ∩ live-valid Binance Spot/USDT symbols`.
- The `AUTO_BOUNDED` worker scans all effective candidates, selects one pair, records selected-pair evidence, and applies deterministic policy before any execution work; the `HUMAN_APPROVAL` worker processes durable external proposals and execution work without internal model reasoning.
- `AUTO_BOUNDED` uses the direct, backend-only **Binance Spot API**. `HUMAN_APPROVAL` is MCP-native: an external MCP-compatible host reasons and proposes through DARWIN's private MCP control plane, while DARWIN validates, authorizes, and persists the durable approval state.
- The backend owns policy, budget, balances, filters, freshness, open-order conflict, emergency stop, idempotency, external-call uncertainty, reconciliation, and the financial-write gate. The external host/model and Codex cannot override those controls.

## Safety boundary

DARWIN is Spot-only. It does not support futures, margin, leverage, options, transfers, or withdrawals. A `SELL` only sells a held Spot asset; it cannot open a short position.

A financial write requires the configured mode's authorization plus fresh revalidation. Durable intent state, an idempotency key, a pre-call marker, and reconciliation protect against duplicate or ambiguous submission. `SUBMISSION_UNKNOWN` is reconciled before retry. Emergency stop blocks ordinary new work and routes any necessary cancellation through durable reconciliation.

DARWIN independently enforces the Trading Mandate, Allowed Symbols, Configured Universe, Effective Universe, Max Per Trade, rolling 24-hour budget, Max Concurrent Trades, balances, Binance filters, evidence freshness, open-order conflicts, emergency stop, execution mode, financial-write enablement, durable intent, idempotency/replay protection, submission uncertainty, and reconciliation. Mode is rechecked at the locked durable admission boundary; stale mandate/policy, budget, emergency-stop, and invalid-mode admissions fail closed.

## MCP-native HUMAN_APPROVAL

**AI proposes. DARWIN authorizes. Binance executes.** The external MCP host may read authorized DARWIN projections, reason, validate an untrusted proposal, submit it with an idempotency key, and present owner controls. The implemented control sequence is:

```text
DARWIN MCP read tools
  -> darwin.validate_proposal (dry-run; no intent or approval)
  -> darwin.submit_proposal
  -> durable WAITING_FOR_APPROVAL
  -> explicit owner darwin.approve_trade / darwin.reject_trade
  -> TradeIntentApprovalService
  -> durable execution outbox
  -> ApprovedExecution
  -> Codex App Server -> Binance Agent OS MCP
  -> provider confirmation where applicable -> Binance
```

The external host/model must not self-approve a proposal. `darwin.approve_trade` is intended only for explicit owner-directed approval. Proposal confidence and deterministic policy `PASS` never constitute approval. The host cannot provide trusted balances, filters, policy results, final Binance arguments, or unrestricted raw order tools. Open the private `/mcp` endpoint with `DARWIN_MCP_BEARER_TOKEN`; no external provider authentication is required to inspect or reproduce the repository's judge demo.

### Implemented MCP control surface

Read / observability:

- `darwin.get_status`
- `darwin.get_mandate`
- `darwin.get_budget`
- `darwin.get_universe`
- `darwin.get_portfolio`
- `darwin.get_latest_decision`
- `darwin.get_activity`
- `darwin.list_pending_trades`

Proposal:

- `darwin.validate_proposal`
- `darwin.submit_proposal`

Human control:

- `darwin.approve_trade`
- `darwin.reject_trade`
- `darwin.resolve_execution_confirmation`

Owner configuration / safety:

- `darwin.update_mandate`
- `darwin.update_budget`
- `darwin.update_universe`
- `darwin.emergency_stop`

No `darwin.change_mode`, AUTONOMOUS start/stop/run_once controls, raw Binance trading tools, or direct financial-write tool is implemented in PR #10.

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

## Judge evaluation

The canonical evaluation path is:

```bash
git clone https://github.com/riyannode/DARWIN.git
cd DARWIN
docker compose up --build
```

Then open `http://localhost:3000/demo`. The root Compose Judge Demo is synthetic, deterministic, credential-free, uses no external LLM or Binance authentication, and performs no financial writes. It is the easiest zero-credential evaluation path and is not a live HUMAN_APPROVAL deployment manifest.

The implemented MCP-native control plane is available for technical inspection/testing through the private `/mcp` endpoint, but external provider authentication is not required to evaluate the submission's canonical Judge Demo.

Positive current evidence:

- zero-credential Docker Judge Demo and backend/frontend regression;
- MCP server registration, `initialize`, and `tools/list` with 17 tools discovered;
- missing and invalid bearer requests rejected with HTTP 401;
- authenticated read projections and secret-redaction checks;
- deterministic invalid proposal rejection with zero durable intent;
- valid proposal admission into `WAITING_FOR_APPROVAL`;
- explicit approve/reject durable transitions through the existing state machine;
- repeated approval idempotency and duplicate proposal idempotency;
- conflicting idempotency fingerprint, stale mandate/policy, emergency-stop, and execution-mode admission rejection;
- execution-mode recheck at the locked durable admission boundary;
- restart/readback persistence;
- unchanged AUTO_BOUNDED regression; and
- frontend production build.
