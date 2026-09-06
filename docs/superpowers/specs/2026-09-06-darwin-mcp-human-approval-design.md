# DARWIN MCP-Native HUMAN_APPROVAL Design

> This implementation follows PR #9 (`docs/ARCHITECTURE.md` and `docs/PRD.md`) as the authoritative architecture specification. It does not redesign the approval model or implement the full post-judging roadmap.

## Goal

Add the inbound DARWIN MCP control plane for the post-judging `HUMAN_APPROVAL` mode so an external MCP host owns reasoning and proposal generation, DARWIN independently authorizes and persists the proposal, and the existing durable approval/execution path remains authoritative.

## Core invariant

**AI proposes. DARWIN authorizes. Binance executes.**

The external host may read authorized DARWIN projections, reason, and submit an untrusted candidate proposal. It may not provide trusted balances, prices, filters, policy results, final Binance arguments, or direct financial writes. `darwin.approve_trade` and `darwin.reject_trade` are explicit owner control-panel actions and delegate to the existing durable approval state machine; the server must not infer approval from proposal confidence or policy PASS.

## Scope

### Inbound MCP tools

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

- `darwin.validate_proposal` — dry-run only; no durable intent or execution work.
- `darwin.submit_proposal` — server-side admission into `WAITING_FOR_APPROVAL`; never executes.

Human approval:

- `darwin.approve_trade`
- `darwin.reject_trade`
- `darwin.resolve_execution_confirmation` where the existing confirmation state supports it.

Owner configuration / safety:

- `darwin.update_mandate`
- `darwin.update_budget`
- `darwin.update_universe`
- `darwin.emergency_stop`

No autonomous `run_once`, `start`, `stop`, or mode-renaming tools are included. No raw order or arbitrary Binance passthrough tool is included.

### Authentication

Use a dedicated `DARWIN_MCP_BEARER_TOKEN` server setting for this private/VPS implementation. It is supplied only in the HTTP `Authorization: Bearer` header, compared securely, never logged or returned, and never passed to Binance/Codex. Missing or invalid credentials fail before privileged tool handling. This implementation does not claim OAuth 2.1/CIMD compliance; production remote authorization remains a later PR #9 phase.

The configured MCP token represents the authenticated owner/operator for this private control plane. Existing REST owner-cookie/CSRF authentication remains unchanged.

### Transport

Use the already pinned official MCP Python SDK `mcp==2.1.1`, whose v2 API exposes `MCPServer`. Mount its stateless Streamable HTTP application at `/mcp` inside the existing FastAPI backend. Preserve the current outbound `CodexAppServerTransport` and `CodexBinanceClient` path.

## Shared application seams

MCP handlers remain thin adapters. The new application seam will:

1. validate bounded proposal input;
2. load fresh authoritative Binance evidence through the existing mode-selected client and `ToolCatalog`/mappers;
3. normalize trusted quantity/notional/order values server-side;
4. call the existing `evaluate_execution_policy` and effective-universe logic;
5. enforce freshness, budget, balance, filters, open-order, emergency-stop, and write-gate checks;
6. apply explicit idempotency before durable admission;
7. create the existing `TradeIntent` plus `TradeIntentApproval` in `WAITING_FOR_APPROVAL`; and
8. delegate approve/reject/confirmation transitions to `TradeIntentApprovalService` and execution to the existing outbox/`ApprovedExecution` path.

No MCP handler may write a financial order, call Binance order transport, or implement a second approval/state machine.

## Durable behavior

- `validate_proposal` creates zero `TradeIntent` rows and zero approval/execution outbox work.
- `submit_proposal` creates one durable `TradeIntent` and one durable `TradeIntentApproval` only after fresh deterministic admission.
- An explicit idempotency key is required for submission. Replays return the existing opaque intent/approval reference when the proposal matches; conflicting reuse fails closed.
- Initial intent state is `WAITING_FOR_APPROVAL`; approval state is `PENDING`.
- `approve_trade` and `reject_trade` resolve only an opaque intent/approval reference server-side. They do not accept client-trusted financial fields.
- Repeated approval/rejection/expiry calls are idempotent or fail closed according to the existing `TradeIntentApprovalService` semantics.
- Approved work enters the existing `EXECUTE_APPROVED_INTENT` outbox path. Provider confirmation, `CODEX_WRITE_CONFIRMATION_VERIFIED=false`, write markers, `SUBMISSION_UNKNOWN`, and reconciliation remain unchanged.
- Emergency stop delegates to the existing durable target selection, cancellation outbox, account lock, and reconciliation path.

## Explicit non-goals

- No AUTONOMOUS/AUTO_BOUNDED refactor, rename, scheduling change, or direct Spot API change.
- No DARWIN `AgentRuntime` call for the new MCP proposal path.
- No removal or weakening of current Web/Telegram approval.
- No direct Binance Agent OS SDK migration; the Codex bridge remains.
- No frontend, `/demo`, showcase, or judge-flow changes.
- No database migration unless inspection proves an existing invariant cannot be met with current tables and unique constraints.
- No OAuth/CIMD production authorization claim.
- No raw `buy`, `sell`, `place_order`, or arbitrary provider passthrough.

## Verification contract

Before opening a PR, verify with real execution:

- official MCP `tools/list` and bounded schemas;
- authentication denial for missing/invalid bearer token;
- authorized read projections with secret/redaction checks;
- invalid proposal rejection and zero durable intent;
- valid proposal PASS and zero durable intent for dry-run;
- valid durable submission with exactly one `WAITING_FOR_APPROVAL` intent;
- duplicate submission with no duplicate intent/work;
- explicit host/user approval through `darwin.approve_trade` using the existing service;
- rejection/no-write path;
- confirmation-state preservation;
- emergency-stop delegation;
- unchanged REST, `/demo`, and AUTO_BOUNDED behavior;
- real MCP-host discovery and control-panel sequence;
- feature-branch VPS read/proposal/approval/restart verification without main deployment.
