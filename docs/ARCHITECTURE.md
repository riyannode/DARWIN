# Architecture

DarwinSpot has three source areas only: a FastAPI backend, a Next.js frontend, and documentation. PostgreSQL is the deployed stateful service. The local SQLite URL is for isolated development only; production configuration must use PostgreSQL.

## Boundary

The agent runtime receives typed internal evidence and must return `AgentDecision`. It cannot receive secrets or call arbitrary URLs. `BinanceAgentOSClient` uses the official MCP client transport and the official Agent OS endpoint configured by `BINANCE_AGENT_OS_MCP_URL`; upstream tool descriptors and input schemas are discovered, not invented. OAuth uses the official authorization-code PKCE flow with Binance-compatible URL-based client metadata; the short-lived authorization code is encrypted at rest.

The execution layer creates durable intent before external submission, locks the current budget version while reserving a buy, checks decimal-safe budget state, reuses mandatory UUIDv7 idempotency keys, and places uncertain submissions into reconciliation. `APPROVAL_REQUIRED` persists an allowed decision as `PROPOSED`; the owner approval endpoint locks the intent and reserves the budget immediately before submission. Cancellation remains pending until an exchange terminal state is observed. Models, connection material, session tokens, OAuth flow state, and owner password verification stay server-side.

The portfolio endpoint values live balances only from returned USDT ticker snapshots and returns live open orders; if a required snapshot is unavailable or stale, it returns an unavailable response instead of estimating. Activity is one timeline with server-backed detail expansion, and budget increases plus emergency-stop reactivation are recorded as audit runs.

The API logger emits timestamped structured audit lines with the DarwinSpot component, event code, severity, and sanitized metadata. Reconciliation failures are recorded before the error is returned to the worker or owner API.

## Persistence

`owner_sessions`, `binance_connections`, `agent_configs`, `mandate_versions`, `budget_versions`, `agent_runs`, `trade_intents`, and `order_events` are created by reversible Alembic migrations. OAuth state columns and the unique order-event dedupe index are added by the second migration. Previous mandate and budget versions are append-only records; edits do not rewrite past decisions.

## Failure semantics

Unavailable Agent OS, database failure, stale evidence, malformed model output, unknown exchange responses, and uncertain submission outcomes block new execution. An upstream Agent OS failure also marks the affected durable connection disconnected, so the UI cannot continue to present a stale `CONNECTED` state. The UI displays disconnected, unavailable, empty, and partial states explicitly; it never seeds balances or orders.
