# DARWIN autonomous monitoring and human-approved execution

- **Status:** Approved architecture design
- **Baseline:** `origin/main` at `cdd2ef3ec73d52aaeb03ba3a8126b16e448debb6`
- **Scope:** `/root/DARWIN-rebuild` clean worktree only
- **Decision owner:** DARWIN, not Codex

## 1. Goal and non-goals

DARWIN becomes a continuously scheduled Binance market/account monitoring and
decision agent. It autonomously collects live evidence, selects BUY/SELL/HOLD,
checks deterministic policy, creates durable proposals, and signals the operator
through Telegram. DARWIN never autonomously submits an order, cancellation, or
transfer.

The ordinary path is:

```text
24/7 DecisionCycle
  -> fresh evidence
  -> DARWIN AgentRuntime typed decision + bounded rationale
  -> deterministic mandate/risk/budget/execution-policy gate
  -> TradeIntent WAITING_FOR_APPROVAL
  -> Telegram proposal
  -> operator APPROVE or REJECT
  -> durable approval transition
  -> ApprovedExecution claim
  -> account-scoped financial-write lease
  -> fresh revalidation
  -> exact transport confirmation, if required
  -> exact Binance MCP write
  -> idempotency/correlation/reconciliation
  -> Telegram receipt
```

Reject and timeout are terminal no-write paths. Codex is permitted only as an
authenticated Binance-supported identity/transport bridge. Codex must not make
market decisions, evaluate policy, choose parameters, or auto-answer a
Binance/Codex confirmation.

Out of scope: generic workflow engines, event sourcing, Redis, Kafka, a generic
policy DSL, transfers, withdrawals, futures, margin, leverage, options, social
feeds, arbitrary browsing, and automatic CANCEL/CANCEL_REPLACE decisions.

## 2. Baseline findings

Fresh `origin/main` already contains:

- a scheduled Python worker and durable `AgentRun` records;
- `AgentRuntime` with pair selection and typed decision calls;
- four free-text mandate sections;
- a rolling 24-hour buy budget and deterministic order checks;
- durable `TradeIntent` rows with UUIDv7 idempotency keys;
- uncertain-submission handling and exchange reconciliation;
- emergency stop and known-order cancellation;
- OAuth material encrypted in the database;
- discovered MCP `ToolCatalog` and Binance Agent OS Streamable HTTP client;
- a web approval endpoint for `PROPOSED` intents.

Fresh main does not contain Telegram integration, a durable approval table, an
outbox, an account-scoped financial-write lease, or a Codex App Server bridge.
`AUTO_BOUNDED` currently allows an automatic write and must be changed.

Current non-read paths are `submit_order` and `cancel_order`. No internal
transfer/withdrawal route exists; transfers and withdrawals are forbidden by
capability filtering and remain unsupported/fail-closed.

## 3. Deep modules and seams

### DecisionCycle

`DecisionCycle` owns evidence acquisition, DARWIN model invocation, typed
decision validation, and deterministic admission. Its interface accepts the
repository, read-only exchange adapter, and DARWIN runtime; it returns a durable
run outcome. It does not call a financial write capability.

The model receives both existing free-text mandate context and the structured
execution policy. The free text may influence strategy reasoning, but only the
backend gate is authoritative.

### TradeIntentApproval

`TradeIntentApproval` owns one durable approval state machine. Telegram and web
are adapters over this same interface. It validates operator identity, resolves
opaque approval references server-side, atomically pairs approval and intent
transitions, enforces expiry, and enqueues work. It never accepts trade
parameters from callback data and never directly calls Binance.

### ApprovedExecution

`ApprovedExecution` owns the only ordinary financial-write seam. It claims an
approved intent, acquires the account-scoped write lease, fetches fresh evidence,
reruns deterministic checks, handles an observed transport confirmation, marks
the external-call phase, invokes the exact discovered MCP write, and preserves
existing idempotency/correlation/reconciliation behavior.

### PostgreSQL durable work outbox

`outbox_messages` is a purpose-specific durable work outbox, not merely a
notification queue. It carries Telegram proposal/result delivery and bounded
approved-execution work. It uses unique dedupe keys, `FOR UPDATE SKIP LOCKED`,
leases, retry timestamps, and bounded errors. It is not a generic message bus.

## 4. Authoritative policy

Each immutable `MandateVersion` retains the four existing text fields and adds
only:

- `allowed_symbols`: exact uppercase symbols;
- `max_order_notional`: positive decimal in USDT quote units;
- `max_open_actionable_intents`: positive integer.

Before an actionable intent is created, the backend checks exact symbol
membership, computed notional, outstanding actionable intent count, rolling buy
budget, available balances, Binance symbol filters, freshness, pair consistency,
emergency stop, and spot-only execution policy. It never silently resizes or
mutates a model proposal.

Proposal admission is serialized for the relevant DARWIN account/mandate scope.
Resolving the current mandate, counting actionable intents, evaluating the
limit, creating the intent, creating its approval, and creating the Telegram
outbox row occur in one protected database operation. A rejected limit creates
no actionable approval.

The same checks run again after approval against the newest mandate, budget,
account, market, open-order, activity, and filter evidence. Existing open orders
and exposure are considered; a new BUY/SELL is never treated as an implicit
replacement. Model CANCEL and CANCEL_REPLACE are disabled. A replacement, if
supported later, must be a separate explicitly approved design.

## 5. Minimal persistence changes

### `mandate_versions`

Add `allowed_symbols` JSON text, `max_order_notional NUMERIC(30,12)`, and
`max_open_actionable_intents` integer. The version remains immutable and is
referenced by the agent run.

### `trade_intents`

Add bounded decision and policy evidence:

- `rationale` text;
- `supporting_factors` JSON text;
- `risk_factors` JSON text;
- `confidence` decimal in `[0,1]`;
- `policy_evidence` JSON text;
- `revalidation_evidence` JSON text, nullable;
- `revalidation_failed_reason` text, nullable;
- `write_request_hash` text, nullable;
- `external_call_started_at` timestamp, nullable.

`local_state` adds `WAITING_FOR_APPROVAL`, `APPROVED`, `REVALIDATING`,
`WAITING_FOR_EXECUTION_CONFIRMATION`, `REJECTED`, `APPROVAL_EXPIRED`, and
`REVALIDATION_FAILED`. Existing exchange `EXPIRED` remains reserved for an
exchange order reaching its expired terminal state. `APPROVAL_EXPIRED` means
only that the operator decision window elapsed before approval.

No duplicate expiry field is stored here. The approval row is the sole source of
`expires_at`.

### `trade_intent_approvals`

Add one row per actionable intent:

- opaque UUIDv7 `approval_id` primary key;
- unique `intent_id`;
- configured `operator_user_id` and `operator_chat_id` captured at creation;
- `created_at`, `expires_at`, `decided_at`;
- `status`: `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `EXECUTING`, `CONSUMED`;
- `decision_source`: `TELEGRAM` or `WEB`;
- optional Telegram message/chat identifiers for durable message updates.

No `decision_nonce` is added. The opaque reference, server lookup, configured
identity checks, unique intent link, conditional PENDING transition, and
idempotent duplicate handling are sufficient for the proven threat model.

### `outbox_messages`

Add one table with `id`, unique `dedupe_key`, `kind`, `aggregate_id`, JSON
`payload`, `status`, `attempts`, `available_at`, `lease_until`, `sent_at`, and
bounded `last_error`. Kinds are `TELEGRAM_PROPOSAL`, `TELEGRAM_RESULT`, and
`EXECUTE_APPROVED_INTENT`, plus the narrow emergency-stop cancellation work
needed by the existing product.

### Account-scoped financial-write serialization

Use PostgreSQL only. The preferred implementation is a PostgreSQL advisory lock
on the single DARWIN/Binance account, held by a dedicated database session
across fresh reads, optional transport confirmation, the external write, and
persistence of the definitive/uncertain result. Do not hold an ordinary
`SELECT ... FOR UPDATE` transaction open across network activity.

The lock is released on session/process failure by PostgreSQL. Reconciliation
work remains possible during emergency stop; the emergency stop prevents new
ordinary execution claims but does not prevent recovery of existing uncertain
orders.

## 6. State machines and atomicity

`trade_intents.local_state` is the overall execution lifecycle:

```text
WAITING_FOR_APPROVAL -> APPROVED -> REVALIDATING
WAITING_FOR_APPROVAL -> REJECTED
WAITING_FOR_APPROVAL -> APPROVAL_EXPIRED
REVALIDATING -> REVALIDATION_FAILED
REVALIDATING -> WAITING_FOR_EXECUTION_CONFIRMATION (if required)
REVALIDATING -> SUBMITTING (after confirmation is satisfied or not required)
SUBMITTING -> OPEN / PARTIALLY_FILLED / FILLED / SUBMISSION_UNKNOWN
SUBMISSION_UNKNOWN -> reconciliation states
```

`trade_intent_approvals.status` is only the operator authorization lifecycle:

```text
PENDING -> APPROVED -> EXECUTING -> CONSUMED
PENDING -> REJECTED
PENDING -> EXPIRED
```

Paired transitions are single transactions:

- `PENDING + WAITING_FOR_APPROVAL` to `APPROVED + APPROVED`;
- `PENDING + WAITING_FOR_APPROVAL` to `REJECTED + REJECTED`;
- `PENDING + WAITING_FOR_APPROVAL` to `EXPIRED + APPROVAL_EXPIRED`;
- `APPROVED + APPROVED` to `EXECUTING + REVALIDATING`.

Expiry may transition only `PENDING -> EXPIRED`. An approval successfully
approved before its expiry is never later expired merely because execution or
revalidation runs after the operator TTL. The TTL is the human decision window,
not an execution deadline.

After revalidation failure, `intent = REVALIDATION_FAILED` and `approval =
CONSUMED` commit together. `CONSUMED` means the one-time authorization was
terminally handled; it does not mean Binance executed.

## 7. Telegram approval flow

Server configuration contains bot token, exact operator Telegram user/chat IDs,
webhook secret, and approval TTL. TTL defaults to 90 seconds and is rejected or
clamped outside 30 to 180 seconds. The LLM cannot choose it.

The webhook requires the configured Telegram secret-token header and validates
both `from.id` and `message.chat.id`. Callback data contains only:

```text
approve:<approval_id>
reject:<approval_id>
```

No symbol, side, amount, price, JWT, bearer credential, or final Binance
argument is encoded. The server resolves the reference, checks the durable
state/expiry, and applies the one conditional update. Unauthorized, malformed,
late, and duplicate callbacks fail closed or return the already-recorded
idempotent outcome without side effects.

Proposal text is rendered from the persisted intent and the same bounded
`AgentRuntime` decision. It contains pair, side, order type, computed proposed
notional, reference price, confidence, concise rationale, supporting factors,
risk factors, mandate result, risk/budget result, TTL remaining, and intent ID.
It never contains hidden chain-of-thought, raw prompts, secrets, credentials, or
model internals.

Web approval remains a secondary/fallback adapter using the same approval row and
state transitions. Normal operation does not require opening the dashboard.

Telegram proposal delivery is visible separately from approval existence. A
failed or pending delivery leaves the approval durable and web-approvable but
never represents the operator as notified and never auto-executes.

## 8. Approved execution and confirmation boundary

The execution outbox worker first inspects durable intent/approval state. It does
not trust the outbox row as proof of financial state. It then claims an approved
intent and obtains the account-scoped financial-write lock before revalidation.
Only one ordinary money-moving Binance write for the account may be in flight.

The execution claim transaction changes approval `APPROVED -> EXECUTING` and
intent `APPROVED -> REVALIDATING`. It fetches the newest evidence and policy,
then records revalidation evidence. A failed check produces
`REVALIDATION_FAILED`/`CONSUMED` with no write.

Fresh `origin/main` has a direct MCP Streamable HTTP client but no Codex App
Server bridge. The implementation may define a narrow transport result seam,
but it must not invent the RPC or elicitation schema. It must never auto-answer
an additional Binance/Codex confirmation.

If the exact live transport requires confirmation:

```text
intent REVALIDATING -> WAITING_FOR_EXECUTION_CONFIRMATION
approval remains EXECUTING
```

Confirmation decline, expiry, or cancellation causes a terminal no-write state,
consumes the approval, and emits a Telegram result. Confirmation acceptance
continues to `SUBMITTING`. Only then may the final server-owned write request be
invoked.

Before invoking the external write, persist the final request hash and an
`external_call_started_at` marker. The marker is deliberately conservative:

- marker absent: known pre-call recovery path;
- marker present: the call may have crossed the external boundary; never blind
  retry and reconcile first.

The marker alone never proves successful submission. A crash immediately before
the actual network call may still produce conservative uncertainty, which is
acceptable for financial safety. A definitive correlated response applies the
existing order event/reconciliation logic. An uncertain response or post-marker
crash preserves `SUBMISSION_UNKNOWN` and reconciles by Binance order ID or the
same client idempotency key before retry.

## 9. Emergency stop and other writes

The authenticated operator emergency-stop command is the only special
operator-command cancellation path. It:

- requires authenticated owner mutation controls;
- durably records the exact targeted intents/order IDs in an audit run;
- blocks new proposals and ordinary execution claims;
- enqueues deduplicated cancellation work;
- routes cancellation through `ApprovedExecution`'s narrow emergency branch;
- preserves `CANCEL_PENDING` until terminal exchange reconciliation.

The model cannot trigger this branch. The direct unapproved web cancel endpoint
is disabled. Autonomous CANCEL and CANCEL_REPLACE are disabled. Transfers,
withdrawals, and any other non-spot capability remain unsupported and fail
closed. Every ordinary Binance write requires the durable approval state machine;
the emergency-stop operator command is the explicit approval for its special
cancellation work.

## 10. Worker and retry behavior

The scheduler claims a due run by locking the existing `AgentConfig` row and
advancing its existing `next_run_at` reservation in the same short transaction
before doing network work. This durable schedule reservation prevents two
replicas from claiming the same cycle without holding a database transaction
open across network activity; a worker crash allows the next scheduled cycle to
retry. No scheduler-lease columns are added. The outbox worker claims rows with
`SKIP LOCKED` and a bounded lease. Reclaim always inspects durable execution state:

- rejected, approval-expired, consumed, or terminal intent: mark work skipped;
- approved intent: claim/revalidate under the account lock;
- revalidating/waiting-confirmation: resume only through durable state;
- submitting/submission-unknown or external marker present: reconciliation wins;
- no external marker and known pre-call phase: recover only after state check.

No failed, expired, rejected, or revalidation-failed intent can reach the write
seam. One approval can cause at most one ordinary financial submission attempt.

## 11. Exact implementation scope

New files:

- `backend/src/darwinspot/approval/__init__.py`
- `backend/src/darwinspot/approval/service.py`
- `backend/src/darwinspot/notifications/__init__.py`
- `backend/src/darwinspot/notifications/outbox.py`
- `backend/src/darwinspot/notifications/telegram.py`
- `backend/migrations/versions/0003_approval_outbox.py`

Changed backend files:

- `backend/src/darwinspot/agent/cycle.py`
- `backend/src/darwinspot/agent/runtime.py`
- `backend/src/darwinspot/agent/schemas.py`
- `backend/src/darwinspot/agent/mandate.py`
- `backend/src/darwinspot/execution/gateway.py`
- `backend/src/darwinspot/execution/orders.py`
- `backend/src/darwinspot/execution/reconciliation.py`
- `backend/src/darwinspot/binance/client.py`
- `backend/src/darwinspot/storage/models.py`
- `backend/src/darwinspot/storage/repository.py`
- `backend/src/darwinspot/api/activity.py`
- `backend/src/darwinspot/api/agent.py`
- `backend/src/darwinspot/worker.py`
- `backend/src/darwinspot/config.py`
- `backend/src/darwinspot/main.py`
- `backend/.env.example`

Frontend files are limited to mandate policy inputs, activity/approval state,
and Telegram delivery visibility:

- `frontend/src/lib/api.ts`
- `frontend/src/lib/schemas.ts`
- `frontend/src/components/activity-timeline.tsx`
- `frontend/src/app/activity/page.tsx`
- `frontend/src/app/agent/page.tsx`
- `frontend/src/app/settings/page.tsx` only if delivery status needs display

Documentation files:

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/RUNBOOK.md`
- `docs/DEPLOYMENT.md`
- `docs/SUBMISSION.md`
- `docs/PRD.md`

No dependency is added unless the existing `httpx2` stack cannot support the
Telegram Bot API. No test-only files are committed; local verification files
belong under an ignored `.local-tests/` directory.

## 12. Safety invariants

1. The LLM never authorizes financial execution.
2. Telegram APPROVE authorizes revalidation, not stale submission.
3. Every ordinary Binance write requires durable operator approval.
4. Emergency cancellation is the only special operator-command write path.
5. One approval can cause at most one financial submission attempt.
6. One Binance account cannot perform concurrent ordinary financial writes.
7. Budget/exposure checks use fresh state immediately before submission.
8. Proposal admission enforces `max_open_actionable_intents` atomically.
9. No failed/expired/rejected/revalidation-failed intent reaches the write seam.
10. `SUBMISSION_UNKNOWN` always reconciles before any retry.
11. Transfer/withdrawal remains unsupported and fail-closed.
12. Codex owns transport/auth only; DARWIN owns decisions and policy.

## 13. Verification gates

Required implementation verification:

- migration upgrade/downgrade and database constraints;
- deterministic policy and atomic concurrent proposal admission;
- every paired state transition, duplicate callback, unauthorized callback, and
  expiry race;
- account-scoped write serialization across concurrent approved workers;
- outbox dedupe, retry, lease reclaim, and durable-state inspection;
- pre-call versus possible-call marker recovery;
- stale/fresh revalidation and proof of no write on failure;
- exact Telegram callback data and real Bot API delivery/callback using a
  dedicated test bot/private chat when available;
- real backend/API/database readback;
- real Chromium fallback approval and activity state;
- existing idempotency, correlation, emergency-stop, and reconciliation paths;
- exact Codex App Server to authenticated Binance MCP read-only and confirmation
  behavior, if credentials and the version-matched bridge are available.

Telegram has no official sandbox. If bot credentials or public callback
reachability are unavailable, Telegram verification is `INCOMPLETE`, not a
mocked pass. If the Codex bridge contract cannot be observed, the bridge/write
verification status is `PARTIALLY VERIFIED`; the interface alone is not proof of
production readiness.
