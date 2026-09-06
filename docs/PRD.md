# DARWIN product contract

DARWIN is an owner-operated Binance Spot decision and execution runtime with two execution paths. `AUTO_BOUNDED` uses DARWIN's AgentRuntime for proposal generation; MCP-native `HUMAN_APPROVAL` uses an external MCP-compatible host for reasoning and proposal generation. In both paths, DARWIN's backend owns authorization and safety.

## Authority model

The owner configures one free-text Trading Mandate plus deterministic controls:

- **Allowed Symbols** — exact allowlist for the current mandate;
- **Max Per Trade** — maximum USDT notional for one order;
- **Max Concurrent Trades** — maximum active actionable workflows, not positions;
- **24h Trading Budget** — a rolling BUY budget stored separately from the mandate;
- **Configured Universe** — persisted Spot/USDT monitoring capability; and
- **Emergency Stop** — backend-owned control that blocks ordinary new work.

The mandate is strategy context, never execution authority. The model may propose a pair, action, quantity, order type, limit price, confidence, rationale, supporting factors, and risk factors. Backend policy decides whether a proposed financial write is permitted.

## Universe

A newly created Configured Universe defaults to:

```text
BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT
```

A database upgraded from before `0004_dual_execution_and_universe` can retain the migration's four-symbol compatibility value (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`) until the owner updates it. The universe can contain up to 100 distinct uppercase Spot/USDT symbols. The owner must pass live Spot metadata/filter validation to add a new symbol. The five bootstrap symbols are not a runtime ceiling or a ranking strategy.

```text
Effective Universe = Configured Universe ∩ Allowed Symbols ∩ live-valid Binance Spot/USDT symbols
```

## Decision contract

DARWIN's custom `AgentRuntime` uses the OpenAI SDK and optional OpenAI-compatible `OPENAI_BASE_URL`. Pydantic validates strict pair-selection and decision output; Pydantic is not the agent framework.

Each cycle:

1. derives the Effective Universe;
2. scans every effective candidate using 10 closed `15m` and `1h` candles;
3. selects one pair;
4. fetches selected-pair current ticker, balances, open orders, recent activity, filters, and 48 closed candles each for `15m`, `1h`, and `4h`;
5. produces a typed `BUY`, `SELL`, or `HOLD`; and
6. applies deterministic policy and either creates durable mode-specific work or completes with a safe no-write result.

Candidate evidence supports selection and is retained for audit. Only selected-pair evidence reaches final decision generation. Historical bars inform a decision; they never authorize a trade.

## Modes

- **AUTO_BOUNDED:** DARWIN's `AgentRuntime` proposes a policy-passing intent; `AUTO_POLICY` authorizes it after fresh revalidation and the direct backend-only **Binance Spot API** executes it. It does not need per-order Telegram/web approval or Codex OAuth.
- **HUMAN_APPROVAL:** an external MCP-compatible host is the reasoning engine and proposal generator. It reads authorized DARWIN state and submits an untrusted proposal through DARWIN's private MCP control plane. DARWIN independently evaluates mandate, universe, policy, budget, risk, freshness, and write-gate state; a passing proposal becomes durable `WAITING_FOR_APPROVAL` work only after server-side validation. An explicit owner `darwin.approve_trade` or `darwin.reject_trade` call then uses the existing approval service and outbox path before Codex App Server + **Binance Agent OS** MCP transport.

**AI proposes. DARWIN authorizes. Binance executes.** The external host may reason, inspect authorized state, propose, and present controls to the owner. It may not self-approve, supply trusted balances or filters, inject policy results, supply final Binance arguments, or access unrestricted raw order tools. Proposal confidence and policy `PASS` are not authorization. Both modes use the same policy, account-scoped execution lock, idempotency, external-call marker, reconciliation, and audit trail.

The remaining roadmap is explicit: direct official MCP SDK Binance Agent OS transport, production OAuth/CIMD authorization, multi-host/multi-replica remote MCP hardening, `AUTO_BOUNDED` to `AUTONOMOUS` enum migration, and AUTONOMOUS MCP start/stop/run_once controls are not implemented in PR #10.

## Safety and failure contract

- Spot only: no futures, margin, leverage, options, transfers, or withdrawals.
- A `SELL` may sell a held Spot asset only; it cannot open a short position.
- Policy checks symbols, notional, active intents, 24-hour BUY budget, balances, Binance filters, freshness, open-order conflict, and emergency stop.
- The financial-write setting is enforced at safe-live decision admission and again directly before external submission; `DEMO_MODE=true` always blocks financial writes.
- A `SUBMISSION_UNKNOWN` or `SUBMITTING` state with a recorded external-call marker must reconcile before retry. The marker indicates ambiguity, not success.
- Direct web cancellation and model cancellation are disabled. Emergency stop is the only operator cancellation path and is reconciled by durable work.

## Status boundary

| Claim | Status |
| --- | --- |
| Runtime architecture and safety controls | **IMPLEMENTED** |
| Docker judge demo, all scenarios, and zero durable demo rows | **VERIFIED** in a fresh non-financial Compose run |
| Authenticated Binance Agent OS/Codex acceptance | **PENDING / NOT VERIFIED** |
| Funded live execution | **NOT VERIFIED** |

See [ARCHITECTURE.md](ARCHITECTURE.md) for implementation detail and [RUNBOOK.md](RUNBOOK.md) for operator procedures.
