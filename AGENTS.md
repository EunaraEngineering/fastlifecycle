# FastLifecycle contribution guide

## Product intent

FastLifecycle turns typed Python entities into durable, transactional, and
observable business lifecycles. The entity and its lifecycle are the primary
abstractions; workflow runs and jobs are consequences of entity transitions.

Keep these concepts separate:

- An entity lifecycle is a state machine and may contain cycles.
- The jobs created by a single transition may form a DAG.
- An awaited execution means the caller waits for the configured result; it
  does not require external effects to run inside one open SQL transaction.

The project is in the design stage. Do not present conceptual README examples
as implemented API or as guarantees until code and tests establish them.

## Architecture constraints

- Prefer a small, embedded, Pythonic API built from type hints, classes,
  decorators, `async`/`await`, context managers, and idiomatic exceptions.
- Preserve database-native operation: domain state, versions, histories, and
  operational records must be understandable and queryable outside the runtime.
- Design for a local SQLite path and a PostgreSQL production path without
  requiring users to redefine their entities.
- When persistence is implemented, treat the state change, audit record, and
  derived pending jobs as one transactional boundary; use a transactional
  outbox where publication is involved.
- Treat optimistic locking, idempotency keys, recoverability, and an
  append-only entity history as core durability concerns, not optional polish.
- Make defaults opinionated and simple. Expose workers, leases, retries,
  storage backends, and telemetry progressively rather than requiring them in
  the first example.
- Favor errors that explain the entity, expected and actual version/state, and
  attempted transition.
- Do not claim “exactly once”, “durable”, “transactional”, or “idempotent”
  without documenting its precise boundary, failure mode, and test coverage.

## Scope discipline

Do not turn the MVP into a generic orchestration platform. Before adding a
feature, verify that it improves how users define, protect, execute, test, or
observe an entity lifecycle. Avoid prematurely supporting multiple databases,
brokers, distributed runtimes, or general-purpose control-plane features.

Runtime integrations (for example DBOS or Temporal) must be chosen through
prototypes that validate atomicity with domain data, concurrency behavior,
definition versioning, and the ability to preserve an entity-centric API. Do
not add an adapter merely to make the architecture appear extensible.

## Repository conventions

This is a distributable Python framework managed with `uv`.

- Production code lives in `src/fastlifecycle/`; tests live in `tests/`.
- Keep the public API deliberate: export only supported names from
  `src/fastlifecycle/__init__.py` and document changes in the README.
- Preserve `src/fastlifecycle/py.typed` so downstream consumers receive typing
  information.
- Add focused unit tests with every behavior change. For persistence or
  execution behavior, test failure, duplicate-command, and concurrent-command
  paths whenever applicable.
- Do not lower coverage, add broad type ignores, or relax lint/type-checking
  configuration to accommodate a change.
- When dependencies change, regenerate `uv.lock` with `uv lock` and commit it.
  Build artifacts, virtual environments, reports, and caches remain untracked.

## Commit conventions

Use Conventional Commit-style subjects:

```text
<type>(optional-scope): imperative summary
```

Use one atomic purpose per commit and choose the most specific type:

- `feat`: user-visible functionality.
- `fix`: a non-urgent defect correction.
- `hotfix`: an urgent production-critical correction.
- `docs`: documentation only.
- `test`: tests only.
- `refactor`: code restructuring with no behavior change.
- `perf`: measurable performance improvement.
- `build`: packaging, dependencies, or build tooling.
- `ci`: continuous-integration configuration.
- `chore`: maintenance that fits none of the types above.

Keep the summary concise and imperative, for example
`feat(storage): add SQLite transition history`. Use `!` or a `BREAKING CHANGE:`
footer whenever a commit introduces an incompatible public API change. Do not
use ambiguous subjects such as `update`, `changes`, or `wip`.

## Required gates

Before declaring any change complete, run the following commands from the
repository root and fix every failure:

```bash
uv run ruff format --check .
uv run ruff check .
uv run pytest
uv run mypy
```

`pytest` fails when branch coverage is below 90%. `mypy` runs in strict mode
for both package and test code. For distribution-affecting changes, also run:

```bash
uv build
```
