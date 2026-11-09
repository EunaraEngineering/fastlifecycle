<p align="center">
  <img
    src="docs/assets/fastlifecycle-logo-v1.png"
    alt="FastLifecycle logo: two snakes circle a versioned entity through lifecycle states"
    width="240"
  >
</p>

<h1 align="center">FastLifecycle</h1>

<p align="center"><strong>Entity-centric durable lifecycles for Python.</strong></p>

FastLifecycle is an open-source framework for building durable,
entity-centric business lifecycles in Python. It models business entities as
persistent state machines and connects their transitions to synchronous and
asynchronous jobs.

The project aims for a FastAPI-like developer experience: typed models,
declarative decorators, strong defaults, actionable errors, generated
documentation, and progressive adoption in existing Python applications.

## Project status

FastLifecycle 0.1.0 provides the SQLite/local MVP: typed entities,
public triggers with resolved outcomes, guards and invariants, explicit SQLite schema
migrations, optimistic versions, append-only transition history, and command
idempotency. PostgreSQL, background workers, jobs, retries, outbox delivery,
and recovery of external effects are not part of this release.

## Why FastLifecycle?

Many applications end up representing a business lifecycle through a mix of a
`status` field, application code, queues, workers, cron jobs, callbacks,
retries, locks, and dashboards. The actual state machine becomes implicit and
spread across the system.

FastLifecycle makes the business entity the primary abstraction. A workflow
run is an implementation detail attached to an entity transition, not the
center of the model.

```text
Order #123

pending ──confirm_payment──▶ paid ──begin_fulfillment──▶ fulfilling ──▶ shipped
   └──────────────────────────── cancel ───────────────────────────▶ cancelled
```

The entity lifecycle can contain cycles. Trigger-derived job DAGs are a
separate future concern; the MVP does not create or deliver jobs.

## Quickstart

The supported local path uses an explicitly configured SQLite adapter. Schema
migration is a deployment step: constructing a storage adapter or lifecycle
does not create tables.

```python
from enum import Enum

from fastlifecycle import (
    Entity,
    FastLifecycle,
    LocalExecution,
    SQLiteStorage,
    stay,
    transition_to,
    trigger,
)


class OrderState(str, Enum):
    PENDING = "pending"
    PAID = "paid"
    FULFILLING = "fulfilling"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class Order(Entity):
    state: OrderState = OrderState.PENDING
    payment_id: str | None = None

    @trigger(from_states=[OrderState.PENDING])
    async def receive_payment_message(self, approved: bool, payment_id: str):
        if approved:
            self.payment_id = payment_id
            return transition_to(
                OrderState.PAID,
                outcome="payment_approved",
                result={"payment_id": payment_id},
            )
        return stay(outcome="payment_pending")


# Apply framework-owned DDL before the application accepts lifecycle work.
storage = SQLiteStorage("fastlifecycle.db")
storage.migrate()
lifecycle = FastLifecycle(storage, LocalExecution())

result = await lifecycle.dispatch(
    Order.receive_payment_message,
    entity_id="order-123",
    idempotency_key="provider-message-456",
    approved=True,
    payment_id="pay-456",
)
```

`result` includes the committed entity version, trigger outcome, resolved state
change, and handler result.
`lifecycle.get(Order, "order-123")` returns the latest entity and its version;
`lifecycle.history(Order, "order-123")` returns append-only committed records.

The local executor awaits the trigger handler, then persists the successful
state change in a short SQLite transaction. External effects inside a
trigger are therefore not part of that transaction and must be designed for
retries by the application. The MVP provides no durable background execution.

### Triggers, decisions, guards, and invariants

Triggers are the public, registrable lifecycle contracts. A trigger may be
accepted from declared `from_states`, but its handler decides the outcome with
`transition_to(target, outcome=...)` or `stay(outcome=...)`. A `stay` decision
is persisted and versioned like any other accepted trigger. Directly assigning
to `state` inside a handler is rejected: the declared decision is the only way
to change state.

Pass guards by method name or callable. Mark a zero-argument instance method
with `@invariant`; every invariant runs after the resolved target state is
applied and before anything is committed. A failed input check, guard, or
invariant produces a descriptive exception and creates no successful entity,
history, or command record.

### SQLite migration and configuration

Run the same explicit migration outside application startup with:

```bash
fastlifecycle-migrate fastlifecycle.db
```

Alternatively, `lifecycle_from_environment()` is opt-in and reads:

```text
FASTLIFECYCLE_STORAGE=sqlite
FASTLIFECYCLE_SQLITE_PATH=fastlifecycle.db
FASTLIFECYCLE_EXECUTION=local
```

It validates the selected profile but does not migrate it. Errors redact URL
credentials if a connection-like setting must be reported.

### Persistence semantics and limits

For one successful command, FastLifecycle atomically records the entity
snapshot and version, the append-only history record, and—when supplied—the
idempotency command/result in one SQLite transaction. A key is scoped to an
entity type and entity ID. Repeating the same trigger with identical inputs
returns the original result with `duplicate=True`; reusing the key for another
trigger or inputs is rejected. A conflicting entity version raises
`ConcurrentTriggerError`.

All records are regular `fastlifecycle_*` SQLite tables, so they remain
queryable with ordinary SQL. SQLite is intended for a single local application
profile in this MVP; this release makes no production multi-process, delivery,
exactly-once, or durable external-effect claim.

## Design principles

- **Entity-first.** Business entities, their state, and their history are the
  primary model.
- **Database-native.** State remains visible and operable in ordinary SQLite
  tables in the current release.
- **Explicit boundaries.** Successful local state changes are atomic in
  SQLite; durable background delivery and external-effect recovery are not yet
  provided.
- **Transactional trigger acceptance.** A resolved state change, its audit
  record, and its command result are persisted atomically.
- **DX-first and typed.** Type hints, decorators, validation, documentation,
  and error messages should make the safe path the easy path.
- **Progressive disclosure.** The local path should require minimal
  configuration; workers, storage adapters, telemetry, and advanced controls
  should appear only when needed.
- **Observable by default.** A user can inspect an entity's state and its
  committed trigger history, outcomes, inputs, and outputs with SQL or the
  read API.
- **Explicit guarantees.** Terms such as exactly-once, at-least-once,
  idempotent, and transactional must always state their scope and limits.

## Scope

FastLifecycle is not a general-purpose replacement for Temporal, DBOS, Hatchet,
or a message broker. PostgreSQL and other storage backends remain future work;
the 0.1.0 interface deliberately contains no generic adapter or plugin system.

## Development

FastLifecycle uses a distributable `src/` layout and is managed with
[`uv`](https://docs.astral.sh/uv/). It requires Python 3.10 or newer.

Install the locked development environment and run the quality gates:

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv run mypy
```

Tests enforce at least 90% branch coverage. Static type checking runs in mypy
strict mode for both the framework and its tests.

## Distribution

Build source and wheel distributions locally with:

```bash
uv build
```

The package publishes its typing metadata through `py.typed`.

## Roadmap

1. Add PostgreSQL only after proving the same entity-centric transactional
   model against a real backend.
2. Prototype durable job delivery, retries, and recovery without making
   external-effect guarantees prematurely.
3. Add entity-centric inspection and telemetry.
4. Stabilize extension points only after repeated validated use cases.

## License

FastLifecycle is licensed under the [Apache License 2.0](LICENSE).
