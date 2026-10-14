# FastLifecycle

> **Entity-centric durable lifecycles for Python.**

FastLifecycle is an open-source framework for building durable,
entity-centric business lifecycles in Python. It models business entities as
persistent state machines and connects their transitions to synchronous and
asynchronous jobs.

The project aims for a FastAPI-like developer experience: typed models,
declarative decorators, strong defaults, actionable errors, generated
documentation, and progressive adoption in existing Python applications.

## Project status

FastLifecycle is in the initial design stage. The repository currently
contains packaging and quality tooling only; the lifecycle runtime and the API
shown below are not implemented yet. Examples in this document describe the
intended direction, not a stable public contract.

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

Transitions may create jobs with dependencies, retries, timeouts, and durable
results. The entity lifecycle can contain cycles; the jobs produced by one
transition can form a DAG. These are deliberately separate concepts.

## Intended developer experience

The API below is illustrative and is not implemented yet:

```python
from enum import StrEnum

from fastlifecycle import Entity, FastLifecycle, job, transition


class OrderState(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FULFILLING = "fulfilling"
    SHIPPED = "shipped"
    CANCELLED = "cancelled"


class Order(Entity):
    state: OrderState = OrderState.PENDING
    payment_id: str | None = None

    @transition(source=OrderState.PENDING, target=OrderState.PAID)
    async def confirm_payment(self, payment_id: str) -> None:
        self.payment_id = payment_id


@job(trigger=Order.confirm_payment)
async def issue_invoice(order: Order) -> None: ...


lifecycle = FastLifecycle()
result = await lifecycle.execute(
    Order.confirm_payment,
    entity_id="order-123",
    payment_id="pay-456",
)
```

The same transition should support an awaited execution and durable background
execution. “Synchronous” means the caller waits for the configured result; it
does not mean external effects run inside an open SQL transaction.

## Design principles

- **Entity-first.** Business entities, their state, and their history are the
  primary model.
- **Database-native.** State should remain visible and operable in ordinary
  tables, initially with SQLite for local development and PostgreSQL for
  production.
- **Durable by default.** Accepted work must survive process crashes,
  restarts, retries, and duplicate messages.
- **Transactional transitions.** A state change, its audit record, and its
  derived pending jobs should be persisted atomically, using a transactional
  outbox where applicable.
- **DX-first and typed.** Type hints, decorators, validation, documentation,
  and error messages should make the safe path the easy path.
- **Progressive disclosure.** The local path should require minimal
  configuration; workers, storage adapters, telemetry, and advanced controls
  should appear only when needed.
- **Observable by default.** A user should be able to answer “what happened
  to this entity?” from its state, transition history, jobs, inputs, outputs,
  and failures.
- **Explicit guarantees.** Terms such as exactly-once, at-least-once,
  idempotent, and transactional must always state their scope and limits.

## Initial scope

The MVP is expected to focus on typed entities, states, decorator-based
transitions, guards and invariants, SQLite/PostgreSQL persistence, optimistic
locking, idempotency keys, append-only history, a transactional outbox, and a
small local/worker execution model.

It is not initially intended to be a general-purpose replacement for Temporal,
DBOS, Hatchet, or every message broker and database. Multiple durable runtime
backends remain a prototype-driven architectural decision, not a commitment.

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

1. Define and prototype entity and transition semantics without committing to
   a durable runtime.
2. Build a local runtime with validation, SQLite persistence, history, and
   testing utilities.
3. Add SQL durability: PostgreSQL, concurrency control, idempotency,
   transactional outbox, workers, retries, and recovery.
4. Add entity-centric inspection, timelines, execution graphs, and telemetry.
5. Stabilize extension points only after the core semantics are proven.

## License

FastLifecycle is licensed under the [Apache License 2.0](LICENSE).
