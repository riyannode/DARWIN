# DARWIN Architecture

## Authority and transport

DARWIN is the decision authority. The model receives typed internal evidence,
mandate context, and structured policy and returns a typed BUY/SELL/HOLD
decision plus a bounded operator-facing summary. The model cannot authorize a
financial write.

Codex is an optional transport/authentication adapter only. The configured
HUMAN_APPROVAL uses Codex App Server 0.153.0 over stdio JSON-RPC. AUTO_BOUNDED
uses the narrow backend-only Binance Spot REST adapter. DARWIN sends exact
server/tool/arguments requests to Codex and never sends natural-language
trading prompts. Codex forwards the authenticated Binance Agent OS MCP session.

The transport supports only the exact inspected operations:

- `initialize`;
- `mcpServerStatus/list`;
- `mcpServer/oauth/login`;
- `mcpServer/tool/call`;
- `mcpServer/elicitation/request` handling;
- the exact `thread/start` bootstrap needed for `threadId`.

Elicitation actions are `accept`, `decline`, or `cancel`. DARWIN never
auto-answers them. `CODEX_WRITE_CONFIRMATION_VERIFIED=false` blocks every
financial write until the operator has manually observed and verified the real
confirmation contract.

When authentication is absent, transport state is `AUTH_REQUIRED` or
`NOT_AUTHENTICATED`; the API and worker remain startable, no Binance data is
fabricated, and no write is attempted.

The Spot REST adapter uses only exchange metadata, ticker, account, open orders,
trade history, order status, order submission, and order cancellation. Public
historical market evidence is a separate credential-free `GET /api/v3/klines`
adapter and is shared by both decision modes. The authenticated Spot REST
adapter's credentials are backend-only and must belong to a dedicated
Spot-trading-only key with withdrawals disabled and IP restrictions where
available. Both adapters use an approved Binance HTTPS API host.

## Runtime

```text
scheduler
  -> DecisionCycle
      -> read-only Binance/Codex evidence
      -> effective configured-universe/mandate/live-Spot intersection
      -> bounded 15m/1h candidate history for every effective symbol
      -> DARWIN AgentRuntime pair selection
      -> selected-pair 15m/1h/4h detailed history and account evidence
      -> DARWIN final BUY/SELL/HOLD decision
      -> deterministic execution policy
      -> TradeIntent
          HUMAN_APPROVAL -> TradeIntentApproval + Telegram proposal outbox
          AUTO_BOUNDED -> AUTO_POLICY + informational Telegram outbox
  -> TelegramApprovalAdapter / WebApprovalAdapter
      -> one shared approval state machine
  -> ApprovedExecution
      -> human approval claim OR AUTO_POLICY claim
      -> account-scoped PostgreSQL advisory lock
      -> fresh evidence and policy revalidation
      -> optional observed Codex/Binance elicitation
      -> exact write request
      -> existing mapper, idempotency, and reconciliation
      -> Telegram receipt outbox
```

### DecisionCycle

`DecisionCycle` acquires current Binance Spot metadata and computes the
intersection of persisted `AgentConfig.supported_symbols`, current mandate
`allowed_symbols`, and currently valid Spot/USDT symbols with required filters.
It computes that effective set, validates required Spot filters, and scans
all remaining symbols with typed candidate history: 10 closed candles for each
of `15m` and `1h`, using public `/api/v3/klines` requests with `limit=11` and
bounded concurrency. A candidate failure is audited and excludes only that
symbol. If no candidate history validates, the cycle returns
`NO_EFFECTIVE_SYMBOLS` without pair selection. Pair selection receives only the
remaining validated candidate set and candidate history. After exactly one
candidate is selected, the existing selected-pair path fetches exactly 48
closed candles for each of `15m`, `1h`, and `4h` with `limit=49`, plus current
account evidence. The public history adapter is mode-independent; AUTO_BOUNDED
and HUMAN_APPROVAL receive equivalent typed market evidence. The mapper filters
the currently forming candle, rejects malformed/non-monotonic OHLCV, and rejects
history whose newest closed candle is more than two interval periods old. It asks
the same DARWIN runtime for a typed BUY/SELL/HOLD. HOLD records a run only.
BUY/SELL passes through backend checks before it can create an actionable intent:

- exact symbol in the configured trading universe;
- exact symbol in `allowed_symbols`;
- currently valid Binance Spot/USDT metadata and required filters;
- computed notional at or below `max_order_notional`;
- atomic outstanding-intent limit;
- rolling 24-hour buy budget;
- available balances;
- Binance quantity/price/notional filters;
- current evidence freshness and pair consistency;
- no existing open order that would be implicitly replaced;
- emergency stop off;
- spot-only execution policy.

The final decision evidence persists the selected pair, candidate history for
validated candidates, current snapshots, typed `market_history` for the three
intervals, mandate, structured execution policy, and budget. Existing evidence
serialization and hashing cover the historical bars as part of the same decision
evidence; the bars inform reasoning but do not authorize or override deterministic
policy.

The scan uses bounded concurrency of eight public requests. The existing
configured-universe validation permits up to 100 symbols; a very large universe
may exceed the current 60-second worker cycle timeout and fail closed, but is
never silently truncated.

A rejected model proposal creates no executable authorization and does not
resize or mutate the proposal. An out-of-effective-universe model result is
rejected deterministically and audited.

### TradeIntentApproval

One `TradeIntentApproval` row belongs to one actionable `TradeIntent`. Telegram
and web call the same service. Callback data is only an opaque approval UUID:

```text
approve:<approval_id>
reject:<approval_id>
```

The service validates Telegram secret token, configured user/chat IDs, current
PENDING state, and expiry, then pairs approval and intent transitions in one
transaction. Duplicate decisions return the durable result without new work.

Approval TTL is backend-configured, defaults to 90 seconds, and is bounded to
30..180 seconds. Expiry only changes `PENDING -> EXPIRED`; an approval already
accepted before expiry is never later expired because execution takes longer.

### ApprovedExecution

Human-approved execution first claims:

```text
approval APPROVED -> EXECUTING
intent   APPROVED  -> REVALIDATING
```

in one transaction. It then acquires the account-scoped PostgreSQL advisory
lock, fetches fresh account/market/open-order/activity/filter evidence, resolves
the newest policy and budget, and reruns deterministic checks. A failure pairs
`intent = REVALIDATION_FAILED` and `approval = CONSUMED` with zero Binance write.

If the exact Codex/Binance transport requests additional confirmation, the
intent becomes `WAITING_FOR_EXECUTION_CONFIRMATION` while approval remains
`EXECUTING`. Decline/expiry/cancel and acceptance all preserve the possible-write marker and
transition to `SUBMISSION_UNKNOWN`; the approval is consumed and reconciliation
must run before any possible retry. No confirmation is auto-answered.

AUTO_BOUNDED claims `AUTO_AUTHORIZED -> REVALIDATING` without creating a
`TradeIntentApproval` row. It uses the same account lock, fresh evidence,
newest policy, write marker, submission, reconciliation, and result outbox.
The only difference is `AUTO_POLICY` authorization and the Binance Spot API
transport; it never bypasses deterministic policy.

If Codex requests an additional transport confirmation, DARWIN stores the
opaque request reference and expiry, keeps the execution work pending, and
requires an explicit owner ACCEPT/DECLINE/CANCEL command through the durable
confirmation outbox. Expired confirmation becomes terminal no-write work;
transport loss never triggers a retrying financial submission.

Immediately before calling the external write seam, DARWIN persists a final
request hash and `external_call_started_at`. If the marker is absent, recovery
is a known pre-call path. If present, the call may have crossed the external
boundary; reconciliation wins over retry. The marker never proves success.

## Durable state

`mandate_versions` remains immutable. New rows store the canonical free-text
`trading_mandate` plus the structured policy fields. Historical rows preserve
`assets`, `entry_rules`, `sizing_rules`, and `exit_rules`; when a legacy row has
no `trading_mandate`, the repository derives a read-only compatibility text
without rewriting the row.

The structured policy fields remain:

- `allowed_symbols` JSON text;
- `max_order_notional` numeric;
- `max_open_actionable_intents` integer.

`BudgetSnapshot` counts BUY fills observed in the prior 24 hours plus the
remaining notional of every active BUY workflow in
`WAITING_FOR_APPROVAL`, `APPROVED`, `AUTO_AUTHORIZED`, `REVALIDATING`,
`WAITING_FOR_EXECUTION_CONFIRMATION`, `SUBMITTING`, `SUBMISSION_UNKNOWN`,
`OPEN`, `PARTIALLY_FILLED`, or `CANCEL_PENDING`. For a partially filled intent,
recorded fills are subtracted from its commitment before the remaining amount
is reserved, preventing double counting. During execution revalidation, only
that current intent's active commitment is excluded from the working budget
snapshot; its realized BUY fills and every other active commitment remain
counted. This prevents self-competition without weakening global reservation
accounting.

`agent_configs.supported_symbols` is the authoritative persisted configured Spot
universe. Its bootstrap default is exactly `BTCUSDT`, `ETHUSDT`, `BNBUSDT`,
`SOLUSDT`, and `XRPUSDT`; this is not a runtime limit or dynamic top-five
strategy. Owner-only settings can add or remove valid Spot/USDT symbols up to
the existing 100-symbol validation bound; this does not mutate historical
mandates.

Migration `0005_confirmation_reference` adds the opaque confirmation reference
and expiry fields to `trade_intents`.

Every new `trade_intents` row stores `execution_mode`, `execution_transport`,
`authorization_source`, and `authorized_at`. Human intents use
`CODEX_AGENT_OS_MCP` and receive `TELEGRAM`/`WEB` authorization only after
approval. Autonomous intents use `BINANCE_SPOT_API` and `AUTO_POLICY`.

`trade_intents.local_state` distinguishes approval expiry from exchange expiry:

```text
WAITING_FOR_APPROVAL -> APPROVED -> REVALIDATING
AUTO_AUTHORIZED -> REVALIDATING
WAITING_FOR_APPROVAL -> REJECTED
WAITING_FOR_APPROVAL -> APPROVAL_EXPIRED
REVALIDATING -> REVALIDATION_FAILED
REVALIDATING -> WAITING_FOR_EXECUTION_CONFIRMATION
WAITING_FOR_EXECUTION_CONFIRMATION -> SUBMISSION_UNKNOWN
REVALIDATING -> SUBMITTING
SUBMITTING -> OPEN / PARTIALLY_FILLED / FILLED / SUBMISSION_UNKNOWN
SUBMISSION_UNKNOWN -> existing reconciliation states
```

`trade_intent_approvals.status` is:

```text
PENDING -> APPROVED -> EXECUTING -> CONSUMED
PENDING -> REJECTED
PENDING -> EXPIRED
```

`outbox_messages` is a purpose-specific PostgreSQL durable work outbox for
Telegram proposals/receipts, approved execution, and emergency-stop
cancellation. It uses unique dedupe keys, `FOR UPDATE SKIP LOCKED`, leases,
retry timestamps, and bounded errors. Financial execution state is always read
from the intent/approval tables, not inferred from outbox status.

Proposal admission locks the agent/account scope while resolving the current
policy, reloading the rolling budget, counting actionable intents, and creating
intent plus the mode-specific authorization and outbox rows. The current
BUY reservation is checked under that lock before commit, so
`max_open_actionable_intents` and the rolling BUY budget cannot be bypassed by
concurrent admissions.

The same protected admission operation enforces `SIGNAL_COOLDOWN_SECONDS` for
the exact pair/direction, preventing repeated materially-identical Telegram
signals while the actionable condition remains unchanged.

All ordinary account money-moving writes use one PostgreSQL advisory lock held
by a dedicated database session across fresh revalidation, optional explicit
confirmation, the external call, and definitive/uncertain persistence. Ordinary
transactions are never held open across network I/O. PostgreSQL releases the
lock when the process/session dies.

## Emergency stop and write closure

The authenticated operator emergency-stop command blocks new proposals and
ordinary execution claims in both modes, records targeted intent/order IDs in an audit run,
and queues cancellation work. `ApprovedExecution` handles that narrow
operator-command branch and keeps cancellation in `CANCEL_PENDING` until
exchange reconciliation reaches a terminal state.

Autonomous/model CANCEL and CANCEL_REPLACE are disabled. Direct web cancellation
is disabled. Transfers and withdrawals are unsupported and fail closed.

## Observability and failure behavior

The audit trail records decision, policy result, intent creation, Telegram
attempt/delivery, approval/rejection/expiry, revalidation, transport state,
confirmation, submission, and reconciliation. Logs redact tokens, credentials,
OAuth codes, cookies, and authorization headers.

Codex process death, OAuth loss, Spot API credential/configuration loss, stale evidence, malformed model output,
ambiguous tool discovery, notification failure, and uncertain exchange results
all fail closed. Telegram failures preserve human authorization or autonomous
execution state and expose notification delivery state; they never change
financial authorization semantics.

## Verification status

```text
Codex/Binance transport implementation: IMPLEMENTED
Authenticated live bridge verification: PENDING
Production readiness: PARTIALLY VERIFIED
```

Manual verification remains required for genuine Codex OAuth, populated
Binance tools, an exact harmless read-only call, and the real write confirmation
contract. The first write-path confirmation must be declined and verified to
produce zero trade.
