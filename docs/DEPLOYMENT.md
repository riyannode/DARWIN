# DARWIN Deployment

## Production status

The Codex App Server transport implementation is present and pinned to the
inspected 0.153.0 protocol shapes. Authenticated Binance bridge verification is
still `PENDING` until the operator completes genuine OAuth and live read-only /
confirmation checks. Production readiness is therefore `PARTIALLY VERIFIED`.

## Topology

- Frontend and backend deploy as separate services behind HTTPS ingress.
- PostgreSQL is the source of truth and the only coordination dependency.
- API and worker may run as multiple replicas.
- Worker scheduling uses the durable `AgentConfig.next_run_at` reservation.
- Outbox claims use PostgreSQL row locks, `SKIP LOCKED`, and bounded leases.
- Ordinary account financial writes use one PostgreSQL advisory lock per Binance
  account.
- No Redis, Kafka, or workflow framework is required.

## Configuration

Inject backend secrets through the host secret store only:

```text
DATABASE_URL
OPENAI_API_KEY
OPENAI_MODEL
TOKEN_ENCRYPTION_KEY
OWNER_PASSWORD_HASH
FRONTEND_ORIGIN
BINANCE_AGENT_OS_MCP_URL
BINANCE_AGENT_OS_TRANSPORT=codex
CODEX_APP_SERVER_COMMAND=codex app-server --stdio
CODEX_APP_SERVER_VERSION=0.153.0
CODEX_WRITE_CONFIRMATION_VERIFIED=false
APPROVAL_TTL_SECONDS=90
TELEGRAM_BOT_TOKEN
TELEGRAM_OPERATOR_CHAT_ID
TELEGRAM_OPERATOR_USER_ID
TELEGRAM_WEBHOOK_SECRET
```

Keep `CODEX_WRITE_CONFIRMATION_VERIFIED=false` until the operator has observed
the exact live Binance/Codex confirmation behavior and intentionally enabled the
verified path. Missing Binance OAuth must not prevent API/worker startup; it
must produce `AUTH_REQUIRED`/`NOT_AUTHENTICATED` and no write.

## Release sequence

1. Build the locked backend image.
2. Build the frontend with the exact backend origin.
3. Provision PostgreSQL.
4. Run `PYTHONPATH=src uv run alembic upgrade head` once as a release step.
5. Start API replicas.
6. Start worker replicas.
7. Verify `/health/live` and `/health/ready`.
8. Verify owner login, Codex status, Telegram configuration state, and durable
   activity state.
9. Keep DARWIN in `READ_ONLY` until mandate, structured policy, budget, Telegram,
   and manual transport verification are deliberately complete.

## Runtime guarantees

- DARWIN performs autonomous monitoring, analysis, and BUY/SELL/HOLD decisions.
- Every ordinary BUY/SELL write requires a durable explicit operator approval.
- Telegram approval triggers fresh revalidation, not stale submission.
- Policy admission is atomic and respects max-open intent limits.
- One Binance account cannot perform concurrent ordinary financial writes.
- `SUBMISSION_UNKNOWN` reconciles before retry.
- Emergency stop remains available and queues explicit operator-command
  cancellation work; reconciliation continues while stop is active.
- Notification delivery state is distinct from approval existence.
- Failed Telegram delivery never auto-executes.

## Deferred manual acceptance

Use a dedicated test bot/private chat and a controlled operator-owned account:

1. Complete genuine Binance OAuth through Codex App Server.
2. Verify authenticated `mcpServerStatus/list`.
3. Verify populated Binance tools.
4. Perform an exact harmless read-only MCP call and inspect its structured
   result.
5. Observe the real write confirmation/elicitation contract.
6. Decline the first write confirmation.
7. Verify zero trade creation.
8. Keep the status `PENDING` if any step is unavailable.

Telegram has no official sandbox; do not substitute mocked acceptance.

## Failure and rollback

If Codex exits or authentication expires, keep the worker alive, mark transport
unavailable, retry bounded work, and block writes. Do not fabricate exchange
state. If a request may have crossed the external write marker, reconcile before
retry. Roll back application images only after checking migration compatibility;
never roll back durable financial state by deleting intents or order events.

Never log bot tokens, OAuth codes, bearer credentials, cookies, or Codex
credential material.
