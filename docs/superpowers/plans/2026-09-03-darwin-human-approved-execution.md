# DARWIN Human-Approved Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Re-architect DARWIN into a 24/7 autonomous monitoring and decision runtime that creates durable Telegram-approved trade intents while keeping every ordinary Binance write behind explicit operator approval and a fail-closed Codex transport.

**Architecture:** Preserve the existing evidence mappers, AgentRuntime, budget calculations, ToolCatalog, idempotency, exchange reconciliation, OAuth material storage, and emergency-stop concepts. Deepen the runtime into DecisionCycle, TradeIntentApproval, ApprovedExecution, and a purpose-specific PostgreSQL work outbox. Add a JSONL Codex App Server adapter using only the exact 0.153.0 schemas already inspected; it starts safely unauthenticated and never auto-answers elicitation.

**Tech Stack:** Python 3.14 project, FastAPI, SQLAlchemy/Alembic, PostgreSQL, existing `httpx2`/MCP stack, Next.js, React, Telegram Bot API over `httpx2`, Codex App Server 0.153.0 over stdio JSON-RPC, Chromium/Playwright for local E2E.

**Spec:** `docs/superpowers/specs/2026-09-03-darwin-autonomous-approval-design.md`

## Global Constraints

- Start from fresh `origin/main` and never modify the original dirty investigation tree.
- DARWIN owns scheduling, evidence, model decisions, mandate context, structured policy, budget, risk, intents, approvals, execution gates, reconciliation, emergency stop, and audit.
- Codex owns only supported Binance OAuth identity and authenticated MCP transport; no natural-language trading prompts.
- `AUTO_BOUNDED` means bounded autonomous Spot execution through the direct
  Binance API after the same deterministic policy and fresh revalidation; it
  never creates a human approval row.
- Telegram callback data is only `approve:<approval_id>` or `reject:<approval_id>`.
- Approval TTL defaults to 90 seconds and is backend-bounded to 30 through 180 seconds; the LLM cannot choose it.
- One PostgreSQL database is authoritative; do not add Redis, Kafka, workflow frameworks, or event sourcing.
- Ordinary financial writes are serialized per Binance account with PostgreSQL-only coordination.
- Revalidation uses fresh exchange/account state and the newest structured policy; stale approvals never submit stale payloads.
- Failed, rejected, expired, or revalidation-failed intents cannot reach a Binance write seam.
- `SUBMISSION_UNKNOWN` always reconciles before retry; the external-call marker is conservative.
- Telegram and web approval use one durable approval state machine.
- Emergency-stop cancellation is the only special operator-command write path; model cancellation and direct web cancellation are disabled.
- Codex/Binance authenticated bridge verification remains `PENDING`/`UNVERIFIED` until manual OAuth and live read/write-confirmation tests are performed.
- Test-only files remain under ignored `.local-tests/` and are never committed.

---

### Task 1: Establish implementation branch and local verification harness

**Files:**
- Create: `.local-tests/` files only; add `.local-tests/` and related artifacts to `.gitignore`.
- Modify: `.gitignore`

**Interfaces:**
- Produces a local `unittest` runner and a clean ignored area for temporary DB/browser/API harnesses.

- [ ] **Step 1: Write the local test runner first**

Create `.local-tests/run_backend_tests.py` to discover and run tests under `.local-tests/backend_tests/` with `unittest`, returning a non-zero code on failure.

- [ ] **Step 2: Run the empty runner**

Run: `python3 .local-tests/run_backend_tests.py`
Expected: PASS with zero discovered tests.

- [ ] **Step 3: Ignore verification artifacts**

Add `.local-tests/`, `.tmp/`, `playwright-report/`, `test-results/`, `*.har`, and `*.trace.zip` to `.gitignore` without changing existing ignore behavior.

- [ ] **Step 4: Verify the working tree scope**

Run: `git status --short --branch`
Expected: only the plan and `.gitignore` changes are present; the original `/root/DARWIN` checkout is untouched.

- [ ] **Step 5: Commit the plan/harness setup**

```bash
git add .gitignore docs/superpowers/plans/2026-09-03-darwin-human-approved-execution.md
git commit -m "docs: add DARWIN execution implementation plan"
```

### Task 2: Define deterministic policy and state behavior with failing tests

**Files:**
- Create: `.local-tests/backend_tests/test_policy_and_states.py`
- Modify later: `backend/src/darwinspot/agent/schemas.py`, `backend/src/darwinspot/agent/mandate.py`, `backend/src/darwinspot/execution/orders.py`, `backend/src/darwinspot/execution/gateway.py`

**Interfaces:**
- `evaluate_execution_policy(policy, decision, market, balances, filters, open_orders, budget, emergency_stop, actionable_intent_count) -> PolicyEvaluation`
- `next_state(current, event)` accepts `WAITING_FOR_APPROVAL`, `APPROVAL_EXPIRED`, `APPROVED`, `REVALIDATING`, `WAITING_FOR_EXECUTION_CONFIRMATION`, and `REVALIDATION_FAILED` transitions without conflating approval expiry with exchange `EXPIRED`.
- `AgentDecision` accepts only `HOLD`, `BUY`, and `SELL`; includes bounded `confidence`, `supporting_factors`, and `risk_factors`.

- [ ] **Step 1: Write failing policy/state tests**

Cover exact symbol membership, maximum notional, max-open limit, budget, balances, Binance filters, open-order exposure, emergency stop, approval-expired naming, disabled CANCEL/CANCEL_REPLACE, and invalid action fields.

- [ ] **Step 2: Run the focused tests**

Run: `python3 -m unittest discover -s .local-tests/backend_tests -p 'test_policy_and_states.py' -v`
Expected: FAIL because the new policy evaluator and state transitions are absent.

- [ ] **Step 3: Implement the smallest policy module**

Add a focused deterministic policy evaluator in `backend/src/darwinspot/execution/gateway.py` or a new `policy.py` only if the existing gateway cannot retain locality. It must return named reasons and never mutate a decision.

- [ ] **Step 4: Implement typed decision/state changes**

Update schemas/prompts so DARWIN returns BUY/SELL/HOLD with bounded explanation fields. Preserve existing model response validation and fail closed on malformed output.

- [ ] **Step 5: Run focused tests again**

Expected: PASS with all policy/state cases green.

### Task 3: Add the minimal migration and durable models

**Files:**
- Create: `backend/migrations/versions/0003_approval_outbox.py`
- Modify: `backend/src/darwinspot/storage/models.py`
- Modify: `backend/src/darwinspot/agent/mandate.py`
- Modify: `backend/src/darwinspot/config.py`

**Interfaces:**
- Immutable `MandateVersion` stores `allowed_symbols`, `max_order_notional`, `max_open_actionable_intents`.
- `TradeIntentApproval` stores one approval per intent, with `PENDING`, `APPROVED`, `REJECTED`, `EXPIRED`, `EXECUTING`, `CONSUMED`.
- `OutboxMessage` stores Telegram and approved-execution work with dedupe/lease state.
- `TradeIntent` stores bounded rationale/policy/revalidation/write-boundary evidence and distinct `APPROVAL_EXPIRED` from exchange `EXPIRED`.

- [ ] **Step 1: Write failing model/migration tests**

Test column presence, unique approval-to-intent link, unique outbox dedupe key, approval status values, bounded TTL configuration, and downgrade reversibility against a temporary database.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest discover -s .local-tests/backend_tests -p 'test_models_and_migration.py' -v`
Expected: FAIL because columns/tables are absent.

- [ ] **Step 3: Implement SQLAlchemy models and Alembic migration**

Use JSON text consistently with existing models, explicit nullable fields, indexes for approval status/expiry and outbox availability/lease, and no `decision_nonce`.

- [ ] **Step 4: Add config validation**

Add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_OPERATOR_CHAT_ID`, `TELEGRAM_OPERATOR_USER_ID`, `TELEGRAM_WEBHOOK_SECRET`, `APPROVAL_TTL_SECONDS`, `BINANCE_AGENT_OS_TRANSPORT=codex`, `CODEX_APP_SERVER_COMMAND`, and `CODEX_APP_SERVER_VERSION=0.153.0`. Enforce paired Telegram IDs and TTL 30..180 with default 90. Missing Binance auth must be a runtime state, not startup failure.

- [ ] **Step 5: Run migration/model tests**

Expected: PASS; verify upgrade and downgrade both complete.

### Task 4: Deepen repository operations and atomic approval state transitions

**Files:**
- Create: `.local-tests/backend_tests/test_approval_repository.py`
- Create: `backend/src/darwinspot/approval/__init__.py`
- Create: `backend/src/darwinspot/approval/service.py`
- Modify: `backend/src/darwinspot/storage/repository.py`

**Interfaces:**
- `TradeIntentApprovalService.create_waiting_approval(...) -> ApprovalResult`
- `TradeIntentApprovalService.decide(approval_id, decision, operator_user_id, operator_chat_id, source) -> ApprovalResult`
- `TradeIntentApprovalService.expire_due(now) -> int`
- `TradeIntentApprovalService.claim_for_execution(approval_id) -> ClaimedApproval`
- `TradeIntentApprovalService.complete_terminal(approval_id, intent_state, result) -> None`

- [ ] **Step 1: Write failing repository/service tests**

Cover atomic paired transitions, late expiry, approval-before-expiry not later expiring, duplicate Telegram/web decisions, unauthorized identity, no approval on max-open rejection, and approval-to-intent uniqueness.

- [ ] **Step 2: Run tests to verify expected failures**

Run: `python3 -m unittest discover -s .local-tests/backend_tests -p 'test_approval_repository.py' -v`
Expected: FAIL on missing service/state operations.

- [ ] **Step 3: Implement atomic repository primitives**

Use PostgreSQL row locks/advisory locks for proposal admission. In one transaction resolve the newest policy, count actionable intents, evaluate the limit, create `TradeIntent`, create `TradeIntentApproval`, and enqueue the proposal outbox row. Pair all approval/intent transitions in one transaction.

- [ ] **Step 4: Implement expiry and duplicate semantics**

Expiry may only execute `PENDING -> EXPIRED` and `WAITING_FOR_APPROVAL -> APPROVAL_EXPIRED`. Duplicate decisions return durable existing state without new work.

- [ ] **Step 5: Run focused tests**

Expected: PASS, including concurrent admission tests where max-open=1 results in exactly one actionable intent.

### Task 5: Implement purpose-specific PostgreSQL outbox and claims

**Files:**
- Create: `.local-tests/backend_tests/test_outbox.py`
- Create: `backend/src/darwinspot/notifications/__init__.py`
- Create: `backend/src/darwinspot/notifications/outbox.py`
- Modify: `backend/src/darwinspot/storage/repository.py`

**Interfaces:**
- `enqueue_unique(kind, aggregate_id, payload, dedupe_key) -> OutboxMessage`
- `claim_due(limit, lease_seconds, worker_id) -> list[OutboxMessage]`
- `mark_sent(message_id, worker_id) -> None`
- `mark_retry(message_id, worker_id, error, next_time) -> None`
- `reclaim_expired(worker_id) -> int`

- [ ] **Step 1: Write failing dedupe/lease tests**

Cover unique proposal/result/execution dedupe, `SKIP LOCKED` claim behavior, lease expiry reclaim, worker ownership, retry backoff, bounded errors, and durable-state inspection before execution retry.

- [ ] **Step 2: Run tests to verify failure**

Expected: FAIL because outbox operations do not exist.

- [ ] **Step 3: Implement outbox operations**

Use parameterized SQLAlchemy statements and explicit status predicates. Do not make outbox state authoritative for financial execution; inspect `TradeIntent`/approval state before processing.

- [ ] **Step 4: Run focused tests**

Expected: PASS for dedupe, claims, retries, and reclaim.

### Task 6: Implement DecisionCycle and remove autonomous write paths

**Files:**
- Create: `.local-tests/backend_tests/test_decision_cycle.py`
- Modify: `backend/src/darwinspot/agent/cycle.py`
- Modify: `backend/src/darwinspot/agent/runtime.py`
- Modify: `backend/src/darwinspot/agent/prompts.py`
- Modify: `backend/src/darwinspot/agent/schemas.py`
- Modify: `backend/src/darwinspot/execution/gateway.py`
- Modify: `backend/src/darwinspot/execution/orders.py`

**Interfaces:**
- `DecisionCycle.run(repo, read_client, runtime, run_id) -> CycleResult`
- DecisionCycle creates WAITING_FOR_APPROVAL intents for valid BUY/SELL and records HOLD without an approval.
- `submit_intent` is no longer callable from scheduler/model paths; only ApprovedExecution may call the ordinary write adapter.

- [ ] **Step 1: Write failing cycle tests**

Cover model BUY/SELL/HOLD, bounded rationale persistence, policy rejection with no approval, signal dedupe/cooldown, no CANCEL/CANCEL_REPLACE, and AUTO_BOUNDED producing proposals rather than writes.

- [ ] **Step 2: Run focused tests**

Expected: FAIL on new DecisionCycle/policy/approval behavior.

- [ ] **Step 3: Refactor current cycle surgically**

Keep existing read evidence acquisition and mappers. Move only admission/proposal responsibilities behind DecisionCycle and pass structured policy in model context. Do not add a second model explanation call.

- [ ] **Step 4: Run focused tests**

Expected: PASS and no Binance write adapter invocation from DecisionCycle.

### Task 7: Implement Codex 0.153.0 App Server transport/bootstrap fail-closed

**Files:**
- Create: `.local-tests/backend_tests/test_codex_transport.py`
- Create: `backend/src/darwinspot/binance/codex_transport.py`
- Modify: `backend/src/darwinspot/binance/client.py`
- Modify: `backend/src/darwinspot/config.py`
- Modify: `backend/src/darwinspot/main.py`

**Interfaces:**
- `CodexAppServerTransport.start() -> None`
- `CodexAppServerTransport.initialize() -> InitializeResult`
- `CodexAppServerTransport.status(detail="full") -> CodexMcpStatus`
- `CodexAppServerTransport.oauth_login(server, scopes=None) -> str`
- `CodexAppServerTransport.call_tool(server, thread_id, tool, arguments) -> ToolResult`
- `CodexAppServerTransport.resolve_elicitation(request_id, action, content=None) -> None`
- `CodexAppServerTransport.auth_state -> AUTH_REQUIRED | NOT_AUTHENTICATED | CONNECTED | UNAVAILABLE`

- [ ] **Step 1: Write failing JSON-RPC contract tests**

Use a local stdio fixture that emits exact 0.153.0-shaped initialize/status/tool/elicitation messages. Assert no natural-language prompt is sent, request/response IDs correlate, status `notLoggedIn` maps to `AUTH_REQUIRED`, structured tool results are preserved, and elicitation is surfaced without an automatic response.

- [ ] **Step 2: Run focused tests**

Expected: FAIL because the adapter is absent.

- [ ] **Step 3: Implement exact JSONL transport**

Start the configured `codex app-server --stdio` command. Implement only the inspected RPC shapes: `initialize`, `mcpServerStatus/list`, `mcpServer/oauth/login`, `mcpServer/tool/call`, and `mcpServer/elicitation/request`, plus only the exact thread bootstrap RPC required to obtain a valid `threadId`. Handle OAuth completion/status notifications. Never auto-answer elicitation.

- [ ] **Step 4: Implement safe unauthenticated startup**

If Codex is missing, exits, or reports `notLoggedIn`, expose `AUTH_REQUIRED`/`NOT_AUTHENTICATED`, keep DARWIN API/worker startup alive, disable all Binance writes, and permit only genuinely available operations. Do not fabricate tools or Binance results.

- [ ] **Step 5: Run focused tests**

Expected: PASS against the stdio fixture. Live Binance status remains `PENDING` until manual OAuth.

### Task 8: Implement ApprovedExecution, write-boundary marker, and account serialization

**Files:**
- Create: `.local-tests/backend_tests/test_approved_execution.py`
- Create: `backend/src/darwinspot/execution/approved.py`
- Modify: `backend/src/darwinspot/execution/reconciliation.py`
- Modify: `backend/src/darwinspot/execution/orders.py`
- Modify: `backend/src/darwinspot/storage/repository.py`
- Modify: `backend/src/darwinspot/binance/client.py`

**Interfaces:**
- `ApprovedExecution.execute_claimed(approval_id) -> ExecutionResult`
- `ApprovedExecution.cancel_for_emergency_stop(intent_id, operator_action_id) -> CancellationResult`
- `ExternalConfirmationRequired` carries only an opaque transport request reference and expiry.

- [ ] **Step 1: Write failing execution tests**

Cover account lock serialization, fresh revalidation pass/fail, newest policy use, open-order exposure, stale approval rejection, confirmation-required state, explicit confirmation decline, pre-call crash recovery, post-marker `SUBMISSION_UNKNOWN`, no blind retry, and emergency cancellation routing.

- [ ] **Step 2: Run focused tests**

Expected: FAIL because ApprovedExecution and account lock do not exist.

- [ ] **Step 3: Implement PostgreSQL account-scoped lock**

Acquire a PostgreSQL advisory lock using a stable account key on a dedicated DB connection. Hold it across fresh reads, revalidation, optional explicit confirmation handling, the write-boundary marker, external MCP write, and definitive/uncertain persistence. Do not hold a normal transaction open over network I/O.

- [ ] **Step 4: Implement durable execution phases**

Claim approval `APPROVED -> EXECUTING` and intent `APPROVED -> REVALIDATING` atomically. On revalidation failure, write `REVALIDATION_FAILED` + approval `CONSUMED` atomically. If confirmation is required, persist `WAITING_FOR_EXECUTION_CONFIRMATION` while approval remains `EXECUTING`; only an explicit confirmation response proceeds.

- [ ] **Step 5: Implement conservative external-call marker**

Persist final request hash and `external_call_started_at` immediately before crossing the write seam. Marker absent is a known pre-call recovery path; marker present means the call may have crossed and reconciliation wins. Never infer successful submission from the marker.

- [ ] **Step 6: Close write paths**

Route ordinary submit only here. Disable model CANCEL/CANCEL_REPLACE and direct web cancel. Keep emergency-stop cancellation as the explicit operator-command branch, durable/audited and reconciliation-safe. Transfers/withdrawals remain unsupported.

- [ ] **Step 7: Run focused tests**

Expected: PASS with zero write calls on all rejection/expiry/revalidation-failure/confirmation-decline paths and exactly one account-serialized ordinary attempt per approval.

### Task 9: Implement Telegram adapter/webhook and shared web fallback

**Files:**
- Create: `.local-tests/backend_tests/test_telegram.py`
- Create: `backend/src/darwinspot/notifications/telegram.py`
- Modify: `backend/src/darwinspot/api/activity.py`
- Modify: `backend/src/darwinspot/api/agent.py`
- Modify: `backend/src/darwinspot/api/auth.py`
- Modify: `backend/src/darwinspot/main.py`

**Interfaces:**
- `TelegramNotifier.send_proposal(approval_id) -> DeliveryResult`
- `TelegramNotifier.send_result(intent_id, result) -> DeliveryResult`
- `POST /api/integrations/telegram/webhook`
- Existing web approval endpoint delegates to `TradeIntentApprovalService` with source `WEB`.

- [ ] **Step 1: Write failing Telegram tests**

Cover exact proposal text fields, callback data format, secret header, configured user/chat identity, malformed/unauthorized callbacks, duplicate callbacks, real HTTP error retry classification, delivery state persistence, and no token/credential leakage.

- [ ] **Step 2: Run focused tests**

Expected: FAIL because the Telegram adapter/webhook is absent.

- [ ] **Step 3: Implement Telegram Bot API calls**

Use existing `httpx2`. Keep the bot token backend-only. Send bounded HTML/plain text with inline buttons whose callback data is exactly `approve:<approval_id>` and `reject:<approval_id>`. Persist outbox delivery status and Telegram message identifiers; do not claim notification until the Bot API succeeds.

- [ ] **Step 4: Implement webhook security and shared approval**

Validate the Telegram secret-token header, exact configured chat ID and user ID, opaque approval reference, current PENDING state, and expiry. Delegate both decisions to the same approval service; record source `TELEGRAM` and audit events. Never accept parameters from Telegram.

- [ ] **Step 5: Run focused tests**

Expected: PASS; duplicate/unauthorized/expired callbacks produce no write work.

### Task 10: Integrate worker scheduling, outbox processing, and safe startup

**Files:**
- Create: `.local-tests/backend_tests/test_worker.py`
- Modify: `backend/src/darwinspot/worker.py`
- Modify: `backend/src/darwinspot/api/agent.py`
- Modify: `backend/src/darwinspot/api/activity.py`
- Modify: `backend/src/darwinspot/config.py`

**Interfaces:**
- Worker executes scheduled DecisionCycle, expiry work, outbox Telegram work, execution work, and reconciliation work as separate bounded handlers.
- `start_agent` permits safe startup with Codex auth pending; mode/start state cannot enable writes.

- [ ] **Step 1: Write failing worker tests**

Cover multiple worker claims, due-run reservation, Codex unavailable startup, expiry processing, outbox retries, execution-state inspection on reclaim, emergency-stop reconciliation, and bounded exponential backoff.

- [ ] **Step 2: Run focused tests**

Expected: FAIL on new handlers and startup semantics.

- [ ] **Step 3: Implement worker loop**

Keep existing `next_run_at` schedule reservation and add outbox claim processing. Reconciliation can run while emergency stop is active; ordinary execution claims cannot. Codex auth failures become visible transport state, not process-fatal configuration errors.

- [ ] **Step 4: Run focused tests**

Expected: PASS with no automatic write when transport is unauthenticated.

### Task 11: Update frontend with minimal signal/approval/transport states

**Files:**
- Create: `.local-tests/frontend_playwright.py` only, ignored
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/schemas.ts`
- Modify: `frontend/src/components/activity-timeline.tsx`
- Modify: `frontend/src/app/activity/page.tsx`
- Modify: `frontend/src/app/agent/page.tsx`
- Modify: `frontend/src/app/settings/page.tsx`

**Interfaces:**
- Activity payload exposes intent/approval/delivery/revalidation/transport state.
- Web approval buttons call the shared backend approval endpoint and never construct trade arguments.

- [ ] **Step 1: Build the minimal UI state contract**

Update Zod schemas for pending approvals, `APPROVAL_EXPIRED`, `REVALIDATION_FAILED`, notification delivery status, `AUTH_REQUIRED`, and `UNVERIFIED` transport status.

- [ ] **Step 2: Implement minimal UI changes**

Show latest signal, approval expiry, rationale/factors, delivery state, Codex auth pending/unverified, last execution/reconciliation, and emergency stop. Remove direct cancel action and automatic-mode copy.

- [ ] **Step 3: Run frontend typecheck/build**

Run: `cd frontend && pnpm exec tsc --noEmit && pnpm build`
Expected: PASS with no frontend compile errors.

- [ ] **Step 4: Run real Chromium fallback E2E**

Start the actual backend/frontend using the repository’s production-oriented commands and use Chromium to sign in, inspect an unauthenticated Codex state, view an approval, reject it, reload, and confirm the durable state remains terminal. Do not fake Binance data.

### Task 12: Update configuration, documentation, and deferred verification status

**Files:**
- Modify: `backend/.env.example`
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/RUNBOOK.md`
- Modify: `docs/DEPLOYMENT.md`
- Modify: `docs/SUBMISSION.md`
- Modify: `docs/PRD.md`

**Interfaces:**
- Documentation describes Codex transport implementation as `IMPLEMENTED`, authenticated live bridge verification as `PENDING`, and production readiness as `PARTIALLY VERIFIED` until manual operator verification.

- [ ] **Step 1: Document exact setup**

Document safe startup without Binance OAuth, Codex 0.153.0 stdio bootstrap, Telegram webhook configuration, approval TTL, callback security, state transitions, outbox retry, account locking, emergency stop, and no-write behavior while auth/confirmation is unverified.

- [ ] **Step 2: Document deferred manual verification**

List operator-only steps: genuine Codex/Binance OAuth, authenticated `mcpServerStatus/list`, populated tools, harmless read-only tool call, observed write confirmation/elicitation, decline first confirmation, and proof of zero trade. Do not include credential requests or bearer-token handling.

- [ ] **Step 3: Search documentation for stale claims**

Run: `python3 -c 'from pathlib import Path; import re; files=[Path("README.md"), *Path("docs").glob("*.md")]; [print(p) for p in files if re.search(r"AUTO_BOUNDED.*execution|fully autonomous 24/7 trading|directly authenticates", p.read_text(), re.I)]'`
Expected: no stale claims remain.

### Task 13: Full non-authenticated verification and review

**Files:**
- No committed test artifacts.
- Review all changed source/docs files.

- [ ] **Step 1: Run backend static checks**

Run from `backend/`: `uv run ruff check src` and `uv run pyright`.
Expected: zero new errors; if Python 3.14 is unavailable, record the exact environment blocker rather than fabricating results.

- [ ] **Step 2: Run migrations and local backend tests**

Run the available migration upgrade/downgrade checks and `python3 .local-tests/run_backend_tests.py`.
Expected: all non-authenticated tests pass.

- [ ] **Step 3: Run frontend checks**

Run frontend lint/typecheck/build and the actual Chromium flow from Task 11.
Expected: all available checks pass.

- [ ] **Step 4: Run Codex unauthenticated initialization/status check**

Use a temporary `CODEX_HOME` and Codex 0.153.0. Verify App Server initialization and Binance status handling returns `AUTH_REQUIRED`/`NOT_AUTHENTICATED`, with no fabricated inventory/result. Clean up the process and temporary files.

- [ ] **Step 5: Self-review security and concurrency invariants**

Inspect the full diff for token leakage, SQL interpolation, callback-data overloading, direct write bypasses, missing state predicates, account-lock release, outbox reclaim errors, and stale policy use.

- [ ] **Step 6: Run a fresh git/status/diff review**

Run: `git status --short --branch`, `git diff --check`, `git diff --stat`, and inspect staged diff. Confirm only production source/docs/config plus the intended plan/spec commits exist; `.local-tests/` remains untracked/ignored.

### Task 14: Commit, push, and open a PR without merging

**Files:**
- All approved implementation files.

- [ ] **Step 1: Commit the verified implementation**

```bash
git add -A
git commit -m "feat: add human-approved autonomous execution"
```

- [ ] **Step 2: Verify the commit**

Run: `git show --stat --oneline HEAD` and `git status --short --branch`.
Expected: commit contains the implementation and worktree is clean.

- [ ] **Step 3: Push the feature branch**

```bash
git push -u origin feat/darwin-human-approved-execution
```

- [ ] **Step 4: Open a PR only**

Create a PR against `main` with title `feat: add human-approved autonomous execution`. State that Codex/Binance authenticated live verification is pending manual operator OAuth, no funded trade is required, and the PR must not be merged automatically.

- [ ] **Step 5: Verify the PR readback**

Read back the PR URL/number and confirm its state is `OPEN`, not merged. Report the final implementation commit SHA and PR URL.
