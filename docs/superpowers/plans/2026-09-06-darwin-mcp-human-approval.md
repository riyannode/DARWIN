# DARWIN MCP-Native HUMAN_APPROVAL Implementation Plan

> **For agentic workers:** Implement this plan on `feat/mcp-human-approval` only. PR #9 is the authoritative architecture specification. Do not merge or deploy `main`.

**Goal:** Add the inbound DARWIN MCP control plane for PR #9 `HUMAN_APPROVAL` while preserving the current Web/Telegram HUMAN_APPROVAL compatibility path, AUTO_BOUNDED behavior, worker behavior, frontend, and judge demo.

**Architecture:** An external MCP host owns reasoning and submits an untrusted candidate through a thin official MCP SDK adapter. A shared DARWIN application seam fetches authoritative state, normalizes values, evaluates the existing deterministic policy, and admits exactly one durable `WAITING_FOR_APPROVAL` intent by explicit idempotency key. Approval/rejection and provider confirmation delegate to the existing durable state machine and outbox/ApprovedExecution path. The existing Codex App Server → Binance Agent OS MCP transport remains unchanged.

**Tech Stack:** Python 3.14, FastAPI, official MCP Python SDK `mcp==2.1.1` (`MCPServer` v2 API), SQLAlchemy, Pydantic, existing Codex App Server transport, SQLite/PostgreSQL-compatible repository.

**Spec:** `docs/superpowers/specs/2026-09-06-darwin-mcp-human-approval-design.md`, derived from PR #9 `docs/ARCHITECTURE.md` and `docs/PRD.md`.

## Global Constraints

- Base branch is latest `origin/main` at implementation start; never branch from PR #9.
- Only `HUMAN_APPROVAL` MCP-native reasoning/proposal/control is in scope.
- Do not call `AgentRuntime` or `DecisionCycle` from the new MCP proposal path.
- Do not change `AUTO_BOUNDED`, autonomous scheduling, direct Binance Spot execution, or worker semantics.
- Do not change frontend, `/demo`, showcase, Web approval, or Telegram approval behavior except minimal shared-service delegation if required.
- No raw buy/sell/place-order or arbitrary Binance passthrough MCP tool.
- `CODEX_WRITE_CONFIRMATION_VERIFIED=false` remains fail-closed and provider confirmation is never auto-answered.
- `DARWIN_MCP_BEARER_TOKEN` is private/VPS bearer auth only; do not claim OAuth/CIMD compliance.
- No migration unless a current durable invariant cannot be met with existing tables/constraints; stop and report before adding one.
- Temporary verification files stay under `.local-tests/` or `.tmp/` and remain untracked.

---

### Task 1: Lock the MCP/auth/runtime seam

**Files:**
- Create: `backend/src/darwinspot/mcp/__init__.py`
- Create: `backend/src/darwinspot/mcp/auth.py`
- Modify: `backend/src/darwinspot/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/src/darwinspot/main.py`

**Interfaces:**
- `McpPrincipal`: authenticated private owner/operator identity used by MCP adapters.
- `require_mcp_bearer(request) -> McpPrincipal`: constant-time bearer comparison against `Settings.darwin_mcp_bearer_token`; missing/invalid token returns 401/403 without invoking tools.
- `mount_mcp(app)`: builds `MCPServer` v2 Streamable HTTP app at `/mcp`, mounted under the auth wrapper.

- [ ] Add `darwin_mcp_bearer_token: str | None` to settings with non-empty validation when configured; never log its value.
- [ ] Add a secret-free `.env.example` entry and private/test-only documentation comment.
- [ ] Implement a small ASGI auth wrapper that validates `Authorization: Bearer <token>` with `hmac.compare_digest`, rejects missing/invalid credentials, and does not forward the bearer value to tool functions or Binance clients.
- [ ] Add bounded request-body/transport settings through the installed SDK app and a private per-token request limiter with deterministic 429 responses; keep the limiter implementation isolated so production distributed rate limiting remains a later remote-access concern.
- [ ] Mount the SDK app at `/mcp` using `MCPServer.streamable_http_app(streamable_http_path="/")`; do not add a second HTTP protocol implementation.
- [ ] Run the MCP SDK import/mount smoke check before adding business tools.

### Task 2: Add shared authoritative HUMAN_APPROVAL proposal admission

**Files:**
- Create: `backend/src/darwinspot/application/__init__.py`
- Create: `backend/src/darwinspot/application/human_approval.py`
- Modify: `backend/src/darwinspot/storage/repository.py`
- Modify: `backend/src/darwinspot/execution/modes.py`
- Modify: `backend/src/darwinspot/approval/service.py`

**Interfaces:**
- `ProposalInput`: bounded untrusted host input: symbol, side, quantity/notional, optional price/order type, confidence, rationale, and optional supporting/risk text with strict sizes.
- `ProposalEvaluation`: pass/reject, deterministic reasons, safe normalized values, policy evidence, and no provider secrets.
- `HumanApprovalApplication.validate_proposal(proposal) -> ProposalEvaluation`: fresh dry-run; no durable intent/approval/outbox/execution write.
- `HumanApprovalApplication.submit_proposal(proposal, idempotency_key) -> DurableProposalResult`: repeats safely and returns an opaque existing intent/approval reference when the same proposal key is replayed.
- `HumanApprovalApplication.approve_trade(intent_id) -> ApprovalResult` and `reject_trade(intent_id) -> ApprovalResult`: look up the approval server-side and call `TradeIntentApprovalService.decide` with MCP source.

- [ ] Build fresh evidence through the existing HUMAN_APPROVAL client factory, `ToolCatalog`, typed mappers, effective universe, and current repository policy/budget.
- [ ] Normalize host values server-side: use fresh market price for market notional, validate limit price/quantity against current Binance filters, derive trusted committed notional, and reject ambiguous or non-finite values. Never copy host balances, filters, policy results, or final Binance arguments.
- [ ] Call the existing `evaluate_execution_policy` with current mandate, live universe, balances, filters, open orders, budget, freshness, and emergency-stop state.
- [ ] Apply `ensure_financial_write_allowed()` at admission where PR #9 requires write eligibility; dry-run must report the gate without creating work.
- [ ] For durable submission, create an external-proposal `AgentRun` audit record and use the existing repository waiting-intent/approval/outbox primitives. Preserve `WAITING_FOR_APPROVAL` and `PENDING` states.
- [ ] Extend repository admission only enough to accept an explicit idempotency key and safely recover unique-key races; conflicting reuse of a key must fail closed.
- [ ] Add MCP as an approval/authorization source without changing Telegram/Web behavior or allowing AUTO_POLICY to enter the HUMAN_APPROVAL path.
- [ ] Ensure duplicate approval/rejection returns the existing durable result or a safe conflict through `TradeIntentApprovalService`; never create another approval or execution work item.

### Task 3: Extract only shared owner-control helpers

**Files:**
- Create: `backend/src/darwinspot/application/owner_controls.py`
- Modify: `backend/src/darwinspot/api/agent.py` only where a helper extraction preserves its current route contract
- Modify: `backend/src/darwinspot/api/portfolio.py` only where a helper extraction preserves its current route contract

**Interfaces:**
- `update_mandate(db, input, actor) -> version projection`
- `update_budget(db, amount, actor) -> version projection`
- `update_universe(db, symbols, settings, actor, client_factory) -> universe projection`
- `emergency_stop(db, actor) -> existing cancellation/queue result`

- [ ] Move only duplicated route logic needed by MCP into helpers; keep existing REST response shapes and auth dependencies unchanged.
- [ ] Preserve live Spot/USDT validation for new universe symbols, immutable mandate/budget versions, audit events, recent reauthentication semantics for REST, account execution lock, deduplicated emergency-cancel outbox, and reconciliation.
- [ ] Do not add mode-changing or AUTONOMOUS control logic.
- [ ] Verify route behavior against the baseline after each extraction.

### Task 4: Add bounded redacted MCP projections

**Files:**
- Create: `backend/src/darwinspot/application/projections.py`
- Create: `backend/src/darwinspot/mcp/tools.py`
- Modify: existing API modules only if a projection extraction is required to preserve identical REST behavior

**Interfaces:**
- `get_status(db) -> safe status projection`
- `get_mandate(db) -> safe mandate projection`
- `get_budget(db) -> safe budget projection`
- `get_universe(db, client) -> bounded configured/allowed/effective projection`
- `get_portfolio(db, client) -> existing safe portfolio projection`
- `get_latest_decision(db) -> safe latest completed decision projection`
- `get_activity(db, limit, cursor) -> bounded redacted activity page`
- `list_pending_trades(db, limit, cursor) -> bounded opaque intent/approval projections`

- [ ] Reuse `Repository`, existing typed mappers, and existing safe route projection semantics where possible.
- [ ] Never return credentials, OAuth/session material, provider headers, Telegram identifiers, hidden reasoning, raw evidence blobs, or unbounded database contents.
- [ ] Bound every list result and use an opaque cursor or deterministic bounded newest-first page.
- [ ] Return actionable unavailable/stale states without exposing provider internals.

### Task 5: Register the official MCP tool surface

**Files:**
- Create or modify: `backend/src/darwinspot/mcp/server.py`
- Modify: `backend/src/darwinspot/main.py` if mounting is not completed in Task 1

**Interfaces:**
- Tool names exactly as specified by PR #9 and this plan.
- Each tool has a strict Pydantic/SDK-generated input schema, concise description, title annotation, and correct `readOnlyHint`, `destructiveHint`, `idempotentHint`, and `openWorldHint` values.

- [ ] Register all read/proposal/approval/configuration/emergency-stop tools listed in the spec.
- [ ] Keep handlers thin: acquire a fresh DB session, call an application helper, return text plus structured JSON-safe content.
- [ ] `validate_proposal` must never call `submit_proposal` internally and must not create durable rows.
- [ ] `submit_proposal` must stop after `WAITING_FOR_APPROVAL`.
- [ ] `approve_trade` and `reject_trade` accept only opaque intent/approval references and explicit action context; they do not accept financial fields.
- [ ] `resolve_execution_confirmation` only queues the existing confirmation-resolution outbox path and never answers provider elicitation automatically.
- [ ] `emergency_stop` delegates the extracted existing helper.
- [ ] Do not expose any raw Binance or order-placement tool.

### Task 6: Local red-green and runtime verification

**Files:**
- Create only local: `.local-tests/mcp_human_approval_smoke.py` and/or `.local-tests/*.jsonl`
- No test-only files committed unless existing repository convention requires it.

- [ ] Run backend dependency/build checks, `ruff`, and `pyright`.
- [ ] Start the actual backend with an isolated database/config and the MCP endpoint; stop all processes afterward.
- [ ] Use the official MCP client/Inspector or a real JSON-RPC client to run `initialize`, `tools/list`, and tool calls.
- [ ] Verify missing/invalid bearer denial and authorized reads.
- [ ] Verify invalid proposal REJECT, valid dry-run PASS, and zero intent readback after both.
- [ ] Verify invalid submission creates zero intent; valid submission creates exactly one `WAITING_FOR_APPROVAL` intent and one PENDING approval; replay creates no duplicate intent/outbox work.
- [ ] Verify approve/reject through the existing durable service, including repeated calls and no-write rejection.
- [ ] Verify confirmation state remains provider-driven and `CODEX_WRITE_CONFIRMATION_VERIFIED=false` remains fail-closed.
- [ ] Verify emergency-stop delegation, REST endpoints, `/demo`, and AUTO_BOUNDED behavior remain unchanged.
- [ ] Inspect database readback and logs for secrets.

### Task 7: Real MCP host, VPS, and PR gate

- [ ] Configure the available real Codex client against the feature-branch MCP endpoint with the private bearer header; do not use Claude because it is unavailable unless it becomes available later.
- [ ] Verify the control-panel conversation: discover → read state → external reasoning → invalid proposal reject → valid validate → explicit user-directed submit → WAITING_FOR_APPROVAL → explicit user-directed approve/reject → existing durable state transition.
- [ ] Prove the host/model did not self-approve by capturing the explicit approval step and MCP call sequence.
- [ ] Deploy only the feature branch to the test VPS, record exact branch/SHA, run read/proposal/approval/restart/idempotency checks, and keep funded writes disabled unless explicitly authorized.
- [ ] Run scoped diff review, `git status`, secret scan, and acceptance checklist. Open a PR against `main` only if every critical gate passes; never merge or deploy `main`.
