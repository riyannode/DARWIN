# DARWIN Architecture

## Authority boundary

DARWIN is a custom decision runtime, not a policy-free model wrapper. Its `AgentRuntime` uses the OpenAI SDK and optionally `OPENAI_BASE_URL` for an OpenAI-compatible endpoint. It makes two typed model calls:

1. `choose_pair()` returns one strict Pydantic `PairSelection`.
2. `decide()` returns one strict Pydantic `AgentDecision`: `BUY`, `SELL`, or `HOLD`, with pair/order details, confidence, rationale, supporting factors, and risk factors.

Invalid JSON, extra fields, or invalid Pydantic output gets one schema-correction attempt; unresolved output fails closed. Pydantic validates model output—it is not an agent framework.

The model decides a proposed trade. The deterministic backend owns the Trading Mandate, Allowed Symbols, Max Per Trade, 24h Trading Budget, Max Concurrent Trades, Configured Universe, balances, filters, freshness, open-order conflict, emergency stop, financial-write gate, and durable execution state.

## Decision flow

```mermaid
flowchart TD
    C[Configured Universe] --> E[Effective Universe]
    A[Allowed Symbols] --> E
    B[Live Binance Spot/USDT metadata and filters] --> E
    E --> S[Candidate scan: closed 15m + 1h OHLCV]
    S --> P[AgentRuntime pair selection]
    P --> D[Selected-pair evidence]
    D --> M[AgentRuntime BUY / SELL / HOLD]
    M --> G[Decision-admission policy and budget]
    G --> W{Financial writes enabled?}
    W -->|No| N[FINANCIAL_WRITES_DISABLED]
    W -->|Yes| X{Mode-specific authorization claim}
    X -->|AUTO_BOUNDED| AA[AUTO_POLICY]
    X -->|HUMAN_APPROVAL| HA[Telegram or web approval]
    AA --> Q[Account lock + fresh evidence + current policy/budget revalidation]
    HA --> Q
    Q --> F{Final financial-write and applicable confirmation gates}
    F -->|Blocked| K[Durable no-write state]
    F -->|Allowed| T{External write transport}
    T -->|AUTO_BOUNDED| R[Binance Spot API order write]
    T -->|HUMAN_APPROVAL| H[Codex + Binance Agent OS MCP order write]
    R --> J[Reconciliation + durable audit state]
    H --> J
```

### Universe and evidence

A newly created Configured Universe defaults to `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`, and `XRPUSDT`. Owners may configure up to 100 valid uppercase Spot/USDT symbols. The five defaults are not a dynamic top-five strategy or a runtime limit. A database upgraded from before `0004_dual_execution_and_universe` can retain that migration's four-symbol compatibility value (`BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`) until its owner explicitly updates the stored universe.

```text
Effective Universe = Configured Universe ∩ Allowed Symbols ∩ live-valid Binance Spot/USDT symbols
```

A cycle uses live exchange metadata and required filters to derive that intersection. It fetches 10 closed candles for `15m` and `1h` for every effective candidate with bounded concurrency of eight. A failed candidate is excluded, recorded as a sanitized failure in that run's `pair_selection` evidence, and does not create a child run. If no candidate remains, the cycle completes as `NO_EFFECTIVE_SYMBOLS`.

Configured-universe validation accepts up to 100 symbols. Candidate scanning processes the entire Effective Universe and is never silently truncated. A sufficiently large Effective Universe can exceed the worker's current 60-second cycle timeout; that cycle fails closed rather than creating a partial decision or silently reducing the candidate set.

After pair selection, the final decision receives selected-pair-only current ticker, balances, open orders, recent activity, filters, Trading Mandate, policy/budget snapshots, and 48 closed candles each for `15m`, `1h`, and `4h`. Candidate history remains audit evidence and is not forwarded to the final model call.

### Deterministic policy

A `BUY` or `SELL` must pass all applicable checks before it can create an actionable intent:

- exact membership in Configured Universe and Allowed Symbols;
- current live Binance Spot/USDT metadata and required filters;
- Max Per Trade / computed notional;
- rolling 24h Trading Budget and atomic active-workflow limit;
- available Spot balances;
- current evidence freshness and pair consistency;
- no conflicting open order; and
- emergency stop off.

A `HOLD` is a model decision. `SKIPPED` is a system outcome. Policy rejection, stale evidence, an invalid selected pair, a suppressed repeat signal, no Effective Universe, or a closed financial-write gate never becomes an exchange order.

## Execution modes

| Mode | Authorization | Evidence and transport | Approval semantics |
| --- | --- | --- | --- |
| `AUTO_BOUNDED` | `AUTO_POLICY` after policy admission | The direct backend-only **Binance Spot API** supplies exchange metadata, ticker, account, open orders, recent trades, filters, order submit/query, and emergency cancel. | No per-order human approval, Codex OAuth, or Telegram approval. |
| `HUMAN_APPROVAL` | durable approved `TradeIntentApproval` | **Binance Agent OS** is reached through Codex App Server + MCP. Codex is a transport/authentication adapter, not a decision authority. | Telegram callbacks and owner web approval call the same durable state machine. Telegram notification is not an `AUTO_BOUNDED` authorization mechanism. |

Both modes use a fresh revalidation, account-scoped lock, current policy/budget, idempotency key, write request hash, external-call marker, durable outbox, and reconciliation. `HUMAN_APPROVAL` can stop at a further observed Codex/Binance confirmation; DARWIN never auto-answers it. `CODEX_WRITE_CONFIRMATION_VERIFIED=false` blocks HUMAN_APPROVAL financial submission pending manual provider-contract verification.

## Financial-write safety

`DEMO_MODE=true` always blocks writes. With `DEMO_MODE=false` and `FINANCIAL_WRITES_ENABLED=false`, a policy-passing BUY/SELL ends as `FINANCIAL_WRITES_DISABLED` before an intent, approval, or financial transport is invoked.

Immediately before an external order call, DARWIN stores the request hash and `external_call_started_at`. A missing marker identifies known pre-call recovery. A recorded marker means the boundary may have been crossed, not that an order succeeded. `SUBMISSION_UNKNOWN` and marked `SUBMITTING` work reconcile before retry.

The system is Spot-only: no futures, margin, leverage, options, transfers, or withdrawals. A SELL uses held Spot inventory and cannot open a short. Model cancellation, cancel/replace, and direct web cancellation are disabled. Emergency stop blocks ordinary new work and queues narrow cancellation/reconciliation work for known affected intents.

## Durable state and migration head

`mandate_versions` stores immutable mandate versions. The current canonical free-text `trading_mandate` coexists with structured `allowed_symbols`, `max_order_notional`, and `max_open_actionable_intents`; legacy structured text is read through a compatibility projection without rewriting history.

The repository Alembic graph has one head:

```text
0006_canonical_trading_mandate
```

Migration lineage:

```text
0001_initial
→ 0002_oauth_and_event_dedupe
→ 0003_approval_outbox
→ 0004_dual_execution_and_universe (adds configured-universe compatibility data)
→ 0005_confirmation_reference
→ 0006_canonical_trading_mandate
```

The current head adds `mandate_versions.trading_mandate`; `0005` added stored Codex confirmation request/expiry fields. `0003_approval_outbox` is historical, not the current head.

## Public safe-live showcase

`GET /api/showcase` and frontend `/showcase` exist only when all of the following are true:

```dotenv
DEMO_MODE=false
FINANCIAL_WRITES_ENABLED=false
PUBLIC_SHOWCASE_ENABLED=true
```

The route reads persisted completed `SCHEDULED`/`RUN_ONCE` evidence. It neither invokes the model nor Binance and has no mutation seam. Its projection exposes selected decision fields, policy outcome, candidate/selected-pair market evidence, configured/allowed/effective symbols, freshness, and safe system outcomes. It explicitly excludes credentials, OAuth/session material, provider headers, Telegram identifiers, private balances, and hidden reasoning.

## Status

| Claim | Status |
| --- | --- |
| Runtime architecture, AgentRuntime, Pydantic validation, policy, transports, state machine, and public projection | **IMPLEMENTED** |
| Fresh non-financial Docker JUDGE DEMO: all three demo APIs and zero `agent_runs`/`trade_intents` rows | **VERIFIED** |
| Fresh Chromium `/demo` rendering and scenario selection | **VERIFIED** |
| Fresh unauthenticated Chromium shells for `/`, `/agent`, `/budget`, `/activity`, and `/settings` | **VERIFIED**; protected APIs returned expected `401` responses and no mutation was attempted |
| PUBLIC LIVE SHOWCASE Chromium rendering with its required live profile | **NOT VERIFIED** |
| Authenticated Binance Agent OS/Codex provider acceptance | **PENDING / NOT VERIFIED** |
| Funded direct Binance Spot order | **NOT VERIFIED** |

For runnable profiles and commands, see [LIVE.md](LIVE.md), [DEPLOYMENT.md](DEPLOYMENT.md), and [RUNBOOK.md](RUNBOOK.md).

## Post-Judging Architecture Roadmap [PLANNED / POST-JUDGING]

This section is a forward-looking architecture roadmap. It does not describe a
newly implemented runtime, does not change the status table above, and must not
be used to upgrade any current verification claim. All functionality described
below is **PLANNED / POST-JUDGING** until its own acceptance evidence exists.

### Core principle [PLANNED / POST-JUDGING]

**AI proposes. DARWIN authorizes. Binance executes.**

No model, host agent, or external interface is financial execution authority.
The deterministic backend remains the sole authorization layer for every
financial write, regardless of which operating mode or transport is active.

### Two operating modes [PLANNED / POST-JUDGING]

DARWIN supports two distinct operating modes. They share the same application
services, policy engine, durable state, and audit trail.

| Mode | Reasoning engine | LLM API key in DARWIN | Persistent autonomy after host closes | Primary use |
| --- | --- | --- | --- | --- |
| `MCP_NATIVE` | Host agent (Codex, Claude Code, Cursor, ChatGPT, or another MCP-compatible host) | not required | no | interactive, owner-supervised trading |
| `AUTONOMOUS` | DARWIN `AgentRuntime` (server-side) | required | yes | persistent unattended trading |

#### MCP_NATIVE [PLANNED / POST-JUDGING]

In `MCP_NATIVE` mode, an MCP-compatible host is the reasoning and planning
engine. The host may inspect market and account context and propose an action,
but the host and its model are never trusted as financial authorization.

DARWIN does **not** require its own LLM API key in this mode. DARWIN provides
the deterministic policy, risk, budget, mandate, state, audit, and
authorization layer. The host model proposes; DARWIN authorizes; Binance
executes.

```text
Codex / Claude Code / Cursor / ChatGPT
  |  reasoning + MCP tools
  v
DARWIN MCP Server
  |  deterministic policy
  |  mandate / budget / risk / validation
  |  durable audit
  v
authorized execution path
  +--> Binance Agent OS MCP (when workflow requires provider confirmation)
  +--> direct Binance Spot API (future optional AUTO_BOUNDED autonomous mode)
```

Closing or disconnecting the MCP host must not stop an already-running
`AUTONOMOUS` agent. Agent execution is owned by DARWIN's durable server-side
runtime and worker state, not by the lifetime of an MCP host session.

The web UI may remain optional, legacy, or operator-facing. `MCP_NATIVE` may
become the primary control surface post-judging. The docs must not imply the
frontend is required in the future.

#### AUTONOMOUS [PLANNED / POST-JUDGING]

In `AUTONOMOUS` mode, DARWIN's own `AgentRuntime` performs reasoning
server-side. This mode requires a configured LLM provider or API endpoint
because DARWIN itself generates the model calls.

`AUTO_BOUNDED` may continue using the direct Binance Spot API after
deterministic authorization and fresh revalidation. This mode is optional and
separate from `MCP_NATIVE`.

```text
DARWIN AgentRuntime
  |  server-side reasoning + policy
  v
deterministic backend authorization
  |  fresh revalidation
  v
direct Binance Spot API
  |
  v
Binance
```

Host disconnect must not stop an already-running autonomous worker. The
execution transport remains separate from decision authority.

### Target architecture [PLANNED / POST-JUDGING]

The target is one shared application-service boundary for REST/web, future MCP
handlers, and the worker. All three call the same application/domain services.
No business logic or financial policy is duplicated across interfaces.

```text
Codex / Claude / Cursor / ChatGPT
  |  reasoning + MCP v
DARWIN MCP  |  deterministic policy | mandate | budget | risk | validation | durable audit
  |  authorized execution path
  +--> Binance Agent OS MCP (when selected workflow requires provider confirmation)
  +--> Direct Binance Spot API (future optional AUTO_BOUNDED autonomous mode)

REST / Web UI  ─────┐
                     │
Worker             ─┤  same shared application services
                     │
MCP Native handlers ┤
                     v
           shared application services
                     │
          policy / budget / approval
          execution / reconciliation
                     │
         AUTO_BOUNDED / HUMAN_APPROVAL
```

### Inbound MCP read-only surface [PLANNED / POST-JUDGING]

Claude, Codex, ChatGPT, and other compatible MCP hosts will connect to a
future **DARWIN MCP Server**. The server must expose a read-only surface first
before any mutation tools are enabled.

The server calls the same DARWIN application/domain services and durable state
machines used by the REST API and web UI. An MCP handler is an adapter at the
protocol seam, not a second policy engine, order writer, approval
implementation, or persistence model.

The server must not call Binance directly for a user-requested operation. It
must authenticate the host/operator, validate bounded tool input, authorize the
operation, and delegate to the existing authoritative module. This preserves
policy locality and gives REST, web, and MCP callers the same behavior, audit
trail, idempotency, reconciliation, and failure semantics.

Host-supplied pair, amount, price, confidence, or rationale are
**proposals/input only** and must be independently validated server-side. Do
NOT expose a raw unrestricted `place_order`, `buy`, or `sell` tool that
bypasses DARWIN policy.

### Outbound MCP for HUMAN_APPROVAL [PLANNED / POST-JUDGING]

Binance Agent OS MCP remains an outbound integration for applicable
MCP/human-confirmed workflows. For `HUMAN_APPROVAL`, DARWIN will connect
directly to the Binance Agent OS MCP endpoint as an MCP client using the
**official MCP Python SDK**. The outbound client owns transport, OAuth, tool
discovery, tool invocation, and protocol elicitation/confirmation handling.
DARWIN still owns the decision, mandate, deterministic policy, approval state
machine, financial-write gate, submission uncertainty, and reconciliation.

Do not incorrectly claim Binance Agent OS MCP currently provides unattended
autonomous financial writes if confirmation is required by its provider
contract.

The current Codex-specific App Server bridge remains the active implementation
seam documented above. It is planned for removal only after direct OAuth, tool
discovery, tool calling, elicitation/confirmation, submission-uncertainty, and
reconciliation parity have all been verified against the real Binance Agent OS
contract. Until then, the existing `CODEX_WRITE_CONFIRMATION_VERIFIED=false`
fail-closed behavior and **PENDING / NOT VERIFIED** status must remain unchanged.
No bridge removal is implied by this roadmap document.

### AUTO_BOUNDED execution path [PLANNED / POST-JUDGING]

The existing `AUTO_BOUNDED` direct Binance Spot API architecture may remain as
the autonomous execution path:

```text
DARWIN
  → deterministic backend authorization
  → fresh revalidation
  → direct Binance Spot API
  → Binance
```

It remains architecturally independent of MCP, Codex OAuth, and per-order human
approval. The roadmap must not route `AUTO_BOUNDED` through the future DARWIN
MCP Server or through Binance Agent OS MCP, and must not weaken its existing
policy, freshness, idempotency, write-marker, or reconciliation controls.

Keep execution transport separate from decision authority.

### Operator interfaces and runtime authority [PLANNED / POST-JUDGING]

In `MCP_NATIVE` mode, the host agent is the reasoning engine. DARWIN is the
deterministic authorization/policy layer. The host model may propose a trade,
but the deterministic backend must remain the only financial authorization
authority.

In `AUTONOMOUS` mode, DARWIN's `AgentRuntime` is the reasoning engine and the
deterministic backend is the authorization authority.

Claude, Codex, ChatGPT, and other compatible MCP hosts are operator interfaces
in `MCP_NATIVE` mode. They may request observations or an explicitly authorized
operation, but they must not choose trades, interpret a mandate as execution
permission, calculate trusted financial values, or bypass backend policy.

DARWIN's `AgentRuntime` remains the trading decision runtime in `AUTONOMOUS`
mode. The deterministic backend remains the authorization authority for mandate,
budget, symbols, balances, filters, freshness, open-order conflict, execution
mode, financial writes, approval state, emergency stop, idempotency, and
reconciliation.

Closing or disconnecting an MCP host must not stop an already-running
`AUTONOMOUS` agent. Agent execution is owned by DARWIN's durable server-side
runtime and worker state, not by the lifetime of an MCP host session. A host
disconnect may end that host's request/session, but it must not cancel a running
cycle or disable the backend's authorization and recovery controls.

### Shared architecture and non-duplication rule [PLANNED / POST-JUDGING]

The future inbound MCP server, REST/web, and worker must reuse the existing
deep application seams rather than implement policy in protocol handlers:

| Shared authoritative module/seam | MCP handler responsibility |
| --- | --- |
| `AgentRuntime` and `DecisionCycle` | Request a run through the existing decision flow; never add a second model decision path. |
| `Repository` and versioned mandate/budget state | Read current durable state and persist mutations through the same transaction rules. |
| deterministic execution policy and `ExecutionGateway` | Reuse symbol, notional, budget, balance, filter, freshness, open-order, and emergency-stop checks. |
| `TradeIntentApprovalService` | Own approve/reject/expiry/claim/consume transitions for every approval channel. |
| `ApprovedExecution` and reconciliation | Own revalidation, write-boundary markers, confirmation uncertainty, external submission, and recovery. |
| existing emergency-stop branch and audit event path | Keep emergency stop authoritative, deduplicated, and reconciliation-safe. |

If a caller-facing operation lacks a suitable shared module, the maintenance
work should first deepen that module at its existing seam. MCP handlers must
remain thin adapters with no duplicate business logic, policy predicates,
financial calculations, or state transitions. The interface is the test
surface: REST, web, and MCP acceptance should exercise the same authoritative
implementation and produce equivalent durable outcomes.

Do not design separate policy engines for different interfaces.

### Planned MCP tool surface [PLANNED / POST-JUDGING]

Tool names are the proposed stable namespace. Each tool must expose bounded
input/output schemas, actionable errors, explicit read/write annotations, and
structured results suitable for MCP hosts. Activity and list-like results must
be bounded and paginated rather than returning unbounded database contents.

MCP handlers must remain thin adapters over shared DARWIN application/domain
services. No business logic or financial policy should be duplicated inside MCP
handlers.

#### Read / observability [PLANNED / POST-JUDGING]

- `darwin.get_status`
- `darwin.get_mandate`
- `darwin.get_budget`
- `darwin.get_universe`
- `darwin.get_portfolio`
- `darwin.get_latest_decision`
- `darwin.get_activity`
- `darwin.list_pending_trades`
- `darwin.get_recent_decisions`

These tools are read-only projections. They must apply the same redaction rules
as the authenticated web/API projections and must not expose credentials, OAuth
or session material, provider headers, Telegram identifiers, private data beyond
the authorized operator view, or hidden reasoning.

#### Proposal validation / policy evaluation [PLANNED / POST-JUDGING]

- `darwin.validate_proposal`

This tool accepts a host-supplied trade proposal (pair, amount, price,
confidence, rationale) and returns the deterministic policy evaluation without
executing. Host-supplied values are proposals only; the result reflects
server-side validation against the current mandate, budget, universe, filters,
and freshness. This tool must not create durable intent or trigger financial
transport.

#### Agent control [PLANNED / POST-JUDGING]

- `darwin.run_once`
- `darwin.start`
- `darwin.stop`

Each control tool must delegate to the same run/control module and durable agent
state used by the REST and web paths. `run_once` must not bypass the normal
DecisionCycle, policy admission, write gate, or selected execution mode.

#### Human approval [PLANNED / POST-JUDGING]

- `darwin.approve_trade`
- `darwin.reject_trade`
- `darwin.resolve_execution_confirmation`

Each tool must resolve an opaque durable reference server-side and delegate to
`TradeIntentApprovalService` or the existing execution-confirmation state
machine. Tool arguments must not carry client-trusted pair, amount, price,
recipient, policy result, or final Binance arguments. A confirmation response
must preserve the conservative submission marker and reconciliation-first
behavior; accepting a confirmation must never blindly emit a new financial
request.

#### Owner configuration [PLANNED / POST-JUDGING]

- `darwin.update_mandate`
- `darwin.update_budget`
- `darwin.change_mode`
- `darwin.update_universe`

These tools must delegate to the same versioned mandate, budget, mode, and
universe validation paths as REST/web. They must preserve immutable mandate
history, live Spot/USDT symbol validation, bounded values, and current mode
preconditions. Each mutation must record auditable before/after state without
recording secrets.

#### Emergency stop [PLANNED / POST-JUDGING]

- `darwin.emergency_stop`

`darwin.emergency_stop` must call the existing authenticated emergency-stop
branch, including durable target selection, deduplicated cancellation work, and
reconciliation. It must not create an MCP-only cancellation path.

#### Safety and guardrails [PLANNED / POST-JUDGING]

Guardrails and immutable execution-safety invariants remain backend-enforced.
They are not exposed as mutable MCP tools. No MCP tool may weaken, disable, or
bypass the safety architecture described below.

### Mutation authorization and audit contract [PLANNED / POST-JUDGING]

The following rules apply to every future mutation tool. The MCP server must
perform protocol-level authentication and authorization, then call the same
backend application service/state machine used by REST and the web UI. It must
never reimplement policy, compute trusted financial values from client input, or
write durable state directly from a handler.

| Tool class | Required authorization | Required backend behavior and audit |
| --- | --- | --- |
| Read-only tools | Normal authenticated operator access | Return an authorized, redacted projection only; no mutation or financial transport. |
| `darwin.validate_proposal` | Normal authenticated operator access | Evaluate host-supplied proposal against current policy; return pass/reject with reasons; no durable intent created. |
| `darwin.run_once`, `darwin.start`, `darwin.stop` | Authenticated owner authorization | Use the existing agent control/decision flow and record the operator action and resulting state. |
| `darwin.approve_trade`, `darwin.reject_trade`, `darwin.resolve_execution_confirmation` | Authenticated owner authorization | Use the durable approval/confirmation state machine, opaque server-side references, conditional transitions, idempotency, and audit events. |
| `darwin.update_mandate`, `darwin.update_budget`, `darwin.change_mode`, `darwin.update_universe` | Stronger mutation authorization | Require authenticated owner mutation access; validate server-side; persist auditable before/after state and version/hash metadata. |
| `darwin.emergency_stop` | Authenticated owner authorization with the existing recent-reauthentication requirement | Use the existing emergency-stop state and cancellation/reconciliation path; audit operator identity, targets, and outcomes. |

The server must also apply bounded request sizes, rate limits, timeouts,
replay/idempotency controls, request correlation IDs, and safe structured error
responses. OAuth access tokens presented to the inbound MCP server must be
validated for the DARWIN resource/audience and must never be passed through as
Binance credentials. A host identity is not itself owner authorization.

### Immutable execution-safety invariants [PLANNED / POST-JUDGING]

The backend must continue enforcing these immutable invariants regardless of
operating mode or any future configuration surface:

- Spot-only execution;
- no futures, margin, leverage, or options;
- no withdrawals or transfers;
- authentication and authorization;
- the financial-write enablement boundary;
- durable intent and idempotency guarantees;
- submission-uncertainty handling and reconciliation; and
- emergency-stop capability.

No MCP tool, host agent, or external interface may turn an untrusted host or
client payload into execution authority, remove fresh revalidation, disable the
financial-write gate, permit a blind retry after `SUBMISSION_UNKNOWN`, remove
account serialization, or make emergency stop unavailable. Every financial write
remains backend-authorized and attributable.

### Phased implementation roadmap [PLANNED / POST-JUDGING]

The following phases describe future implementation work only. They do not
change the current implementation or verification status above. Each phase
must pass its exit gate before the next mutation surface is enabled.

1. **Phase 1 — Shared application-service boundary [PLANNED / POST-JUDGING].**
   Extract reusable application-service functions from FastAPI routes where
   necessary. Preserve the existing route contracts and REST behavior exactly.
   The Next.js/web REST path, future inbound MCP handlers, and worker must call
   the same application/domain services; REST and MCP must never grow separate
   business logic, policy calculations, persistence rules, or state machines.

   **Exit gate:** real REST behavior remains unchanged; shared service calls
   produce the same durable readback; no MCP handler directly writes Binance or
   manipulates durable execution state.

2. **Phase 2 — Inbound MCP read-only surface [PLANNED / POST-JUDGING].** Add
   the future inbound DARWIN MCP Server as a thin adapter over the shared
   application services. Expose read-only tools first:
   `darwin.get_status`, `darwin.get_mandate`, `darwin.get_budget`,
   `darwin.get_universe`, `darwin.get_portfolio`, `darwin.get_latest_decision`,
   `darwin.get_activity`, `darwin.list_pending_trades`,
   `darwin.get_recent_decisions`. Read tools must use the same authorized and
   redacted projections as REST/web.

   **Exit gate:** compatible-host discovery and real read-only calls work with
   correct schemas, redaction, authentication, pagination, rate limiting, and
   audit correlation; mutation tools remain disabled until their authorization
   and state-machine tests pass.

3. **Phase 3 — MCP_NATIVE proposal/policy workflow [PLANNED / POST-JUDGING].**
   Add the `darwin.validate_proposal` tool so MCP hosts can submit trade
   proposals for deterministic policy evaluation. Add run controls
   (`darwin.run_once`, `darwin.start`, `darwin.stop`) and emergency stop
   (`darwin.emergency_stop`). The host model proposes; DARWIN authorizes.
   Control and approval tools must delegate to the existing durable run,
   approval, confirmation, emergency-stop, and reconciliation paths.

   **Exit gate:** proposal validation returns correct pass/reject with policy
   reasons; run controls delegate to the same DecisionCycle as REST; emergency
   stop uses the same durable cancellation path; no MCP handler creates
   duplicate policy or execution logic.

4. **Phase 4 — Owner configuration and control via MCP [PLANNED / POST-JUDGING].**
   Add the owner configuration tools:

   - `darwin.update_mandate`
   - `darwin.update_budget`
   - `darwin.change_mode`
   - `darwin.update_universe`

   Every mutation must be audited and must reuse the existing server-side
   validation, versioning, mode-precondition, symbol/filter, budget, and
   authorization logic. Before/after state must be attributable without
   recording secrets, and caller-supplied values must not override backend
   invariants.

   **Exit gate:** stronger owner mutation authorization, validation failures,
   concurrent updates, idempotent retries, before/after audit readback, and
   unchanged REST/web behavior are verified.

5. **Phase 5 — Binance Agent OS MCP integration/parity [PLANNED / POST-JUDGING].**
   Make the official MCP Python SDK the primary Binance Agent OS transport for
   `HUMAN_APPROVAL`, reusing the existing `BinanceAgentOSClient` foundations,
   typed mappers, `ToolCatalog`, and durable execution modules. Verify the full
   OAuth lifecycle, tool discovery and schema validation, read calls, write
   elicitation/confirmation, and transport error handling against the real
   provider. Preserve durable HUMAN_APPROVAL approval semantics, fresh
   revalidation, write-boundary markers, submission uncertainty, and
   reconciliation. Remove the Codex-specific App Server bridge only after
   direct behavior has parity evidence, including in-flight recovery.

   **Exit gate:** authenticated direct OAuth, discovered tools, harmless read
   calls, exact write schemas, explicit confirmation decline/cancel/expiry,
   conservative `SUBMISSION_UNKNOWN`, correlated order lookup, and
   reconciliation are all verified. Until then, the current bridge and
   `PENDING / NOT VERIFIED` status remain authoritative.

6. **Phase 6 — Optional autonomous runtime cleanup [PLANNED / POST-JUDGING].**
   Clean up the `AUTONOMOUS` mode runtime and make worker configuration
   validation mode-aware so that Codex/App Server dependencies are not required
   for modes that do not use them. Ensure `MCP_NATIVE` mode does not pull in
   autonomous-only dependencies. Do not change code now; document the known
   cleanup item for later implementation.

   **Exit gate:** `MCP_NATIVE` mode starts without LLM provider configuration;
   `AUTONOMOUS` mode requires LLM provider configuration; worker config
   validation is mode-aware; no dead dependency paths in either mode.

7. **Phase 7 — Remote multi-host access [PLANNED / POST-JUDGING].** Support
   compatible remote MCP hosts through authenticated remote MCP access. Define
   caller identity and audit attribution, rate limiting, request and session
   isolation, and session/token lifecycle behavior. Remote access must remain
   stateless or durably coordinated across replicas; disconnecting a host must
   not stop an already-running `AUTONOMOUS` agent. Implement only after local
   MCP behavior is verified.

   **Exit gate:** remote authentication/audience checks, identity attribution,
   token rotation/revocation, rate-limit enforcement, timeout behavior,
   multi-replica/load-balancer tests, and host-disconnect independence are
   verified with real protocol traffic.

### Verification gates before any future rollout [PLANNED / POST-JUDGING]

No future phase is complete from source inspection alone. Evidence must include
as applicable:

- real MCP `tools/list` and tool-call interoperability with supported hosts;
- schema, redaction, pagination, timeout, rate-limit, and structured-error
  checks;
- authenticated read access and denial of unauthenticated access;
- owner authorization for control, approval, rejection, and configuration
  mutations;
- stronger mutation authorization plus before/after audit readback for mandate,
  budget, mode, and universe changes;
- parity readback showing REST, web, and MCP use the same durable state and
  state-machine outcomes, with no duplicate policy in handlers;
- concurrent duplicate/replay requests proving idempotency and no duplicate
  approval or financial work;
- unchanged `AUTO_BOUNDED` behavior through direct Binance Spot API, including
  deterministic authorization, fresh revalidation, write gating, and
  reconciliation;
- real Binance Agent OS direct-SDK OAuth, discovery, read-only calls, tool
  calls, elicitation/confirmation, decline/cancel/expiry, submission-unknown,
  and reconciliation evidence;
- mode-aware worker configuration validation proving `MCP_NATIVE` does not
  require LLM provider or App Server dependencies;
- multi-replica/load-balancer behavior with no critical MCP session, lock,
  approval, or confirmation state held only in process memory; and
- rollback/recovery evidence showing the Codex bridge remains available until
  direct parity and in-flight recovery are proven.

Until these gates produce fresh evidence, the implementation and verification
status tables above remain authoritative and unchanged. The canonical sources
for protocol behavior are the [MCP tools specification](https://modelcontextprotocol.io/specification/2025-06-18/server/tools.md),
[MCP authorization specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization.md),
[MCP elicitation specification](https://modelcontextprotocol.io/specification/2025-06-18/client/elicitation.md),
and the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
