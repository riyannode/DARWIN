# DARWIN product contract

DARWIN is an autonomous Binance Spot decision and execution runtime. Give it a **Trading Mandate** and hard backend limits; it decides what, when, and how to trade only within those limits.

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

- **AUTO_BOUNDED:** `AUTO_POLICY` authorizes a policy-passing intent. It uses the direct backend-only **Binance Spot API** after fresh revalidation and does not need per-order Telegram/web approval or Codex OAuth.
- **HUMAN_APPROVAL:** a policy-passing intent waits for a durable Telegram or web approval. After fresh revalidation, it uses Codex App Server and **Binance Agent OS** MCP. Codex does not choose a trade or override policy.

Both modes use the same policy, account-scoped execution lock, idempotency, external-call marker, reconciliation, and audit trail.

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
| Docker judge demo | **IMPLEMENTED BUT NOT VERIFIED** by a fresh runtime exercise in this documentation-only review |
| Authenticated Binance Agent OS/Codex acceptance | **PENDING / NOT VERIFIED** |
| Funded live execution | **NOT VERIFIED** |

See [ARCHITECTURE.md](ARCHITECTURE.md) for implementation detail and [RUNBOOK.md](RUNBOOK.md) for operator procedures.
