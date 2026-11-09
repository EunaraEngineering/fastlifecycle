# FastLifecycle implementation roadmap

## Purpose and status

This document translates the intended direction in the README into macro
implementation stages. It is a planning artifact, not a statement of current
capabilities or a stable public API contract.

## Current implementation status

Stage 1's SQLite/local MVP is implemented in this repository. The supported
surface is the typed entity and transition kernel, `SQLiteStorage` with the
explicit `migrate()` step, `LocalExecution`, optimistic entity versions,
append-only history, command idempotency, and the opt-in SQLite/local
environment loader. Its guarantees and limits are documented in the README and
covered by the real SQLite test suite.

Stages 2 through 4 remain planned work. In particular, this implementation
does not include PostgreSQL, a worker fleet, pending jobs, retries, leases,
outbox publication, crash recovery of jobs, or durable external-effect
delivery.

The primary abstraction remains an entity and its lifecycle. A transition may
derive jobs, but an entity lifecycle and the job graph for one transition are
separate concepts. Each stage must preserve that distinction.

## Guiding constraints

- Keep the public API small, typed, Pythonic, and suitable for gradual adoption.
- Treat entity state, version, append-only history, and derived pending jobs as
  database-native records.
- Establish precise failure and transaction boundaries before making durability
  claims.
- Start with RDBMS storage, first SQLite and then other relational backends,
  while preserving a path for non-relational storage when its semantics fit.
- Let users select storage and execution capabilities with PyPI extras, while
  keeping their third-party dependencies out of the minimal installation.
- Do not publish a generic storage/runtime adapter or select a third-party
  runtime without a prototype that validates the entity-centric model.
- Validate persistence and execution guarantees with integration tests against
  real backend engines; mocks may complement unit tests but cannot establish
  database semantics.

## Repository architecture policy

FastLifecycle follows a hexagonal architecture adapted to a distributable
Python framework. The reference structure is the user's
[simple GraphQL service example](https://github.com/abend-arg/simple-graphql-service-with-db),
which separates domain, application, persistence, and presentation concerns
and applies migrations explicitly rather than creating schema at service
startup. The framework adapts that shape as follows:

```text
src/fastlifecycle/
  domain/          # Lifecycle semantics, entities, transitions, invariants, errors
  application/     # Use cases and ports for storage, execution, and observability
  persistence/     # Storage adapters and their migrations: SQLite, PostgreSQL, ...
  execution/       # Runtime adapters: local worker, DBOS, other proven runtimes
  presentation/    # Public Python facade, CLI, and opt-in environment loaders
```

The exact module names remain an implementation detail until Stage 0, but the
dependency direction is mandatory: `domain` depends on nothing outside the
standard library and typed shared primitives; `application` depends on
`domain`; outer adapters implement application-owned ports and may depend on
drivers or optional extras. No domain or application code may import a database
driver, Alembic, a worker/runtime SDK, `os.environ`, or a concrete adapter.

`persistence` and `execution` are distinct outbound adapter families. Their
selection and wiring happen at the outer composition boundary. The public
facade must remain lightweight: importing `fastlifecycle` cannot require an
optional backend dependency or establish a connection. CLI and environment
configuration are also outer adapters; users may bypass them by passing
explicit, typed backend instances and settings.

Migrations reside with the owning persistence adapter and operate only on that
adapter's framework schema. Tests mirror the architecture: domain and
application tests use in-memory test doubles for ports, while persistence and
execution adapter tests run against the real backend services. Architecture
tests must enforce the import direction so backend-specific concerns do not
leak into lifecycle semantics.

## Backend selection and packaging policy

Storage and execution are independent capability axes. A storage backend owns
the persistence model and transaction boundary; an execution backend owns how
accepted transition work is run and recovered. Selecting one must not silently
select a particular implementation of the other.

The base package should contain the entity model, lifecycle semantics, shared
backend contracts, and only dependencies required by every installation.
Concrete backends and their drivers should be installed through documented
PyPI extras. The intended shape is:

```text
fastlifecycle                 # Core model and backend contracts
fastlifecycle[sqlite]         # First supported relational storage path
fastlifecycle[postgres]       # Future PostgreSQL driver and integration
fastlifecycle[local]          # First supported execution backend
fastlifecycle[dbos]           # Possible future execution backend, if proven
fastlifecycle[mongo]          # Possible future storage backend, if proven
fastlifecycle[dynamodb]       # Possible future storage backend, if proven
```

The extra names above are an intended packaging convention, not a commitment
that every named backend will be implemented. A composed installation may
select one storage and one execution extra, for example
`fastlifecycle[postgres,local]`. The configuration API must select explicit
backend instances and fail clearly when the selected capability is not
installed, unavailable, or incompatible with the requested guarantees.

SQLite is the first supported storage backend because it validates the
relational schema and local developer experience. PostgreSQL is the next
relational target. MongoDB, DynamoDB, DBOS, and any other backend remain
prototype-driven candidates; they must not distort the first relational model
or appear in the base dependency set prematurely.

## Backend configuration policy

Backend selection and backend configuration are separate concerns. Application
code should select explicit storage and execution backend instances; each
backend receives a typed configuration object that expresses only the settings
it needs. Environment variables are a supported configuration source, not an
implicit global API used by the lifecycle core.

The intended precedence is explicit constructor arguments first, then an
explicit settings object, and finally an opt-in environment loader. This keeps
tests and embedded applications deterministic while supporting twelve-factor
deployments. An environment loader should use a common selector namespace and
backend-specific setting namespaces, for example:

```text
FASTLIFECYCLE_STORAGE=postgres
FASTLIFECYCLE_POSTGRES_URL=postgresql://user:password@host:5432/database
FASTLIFECYCLE_EXECUTION=local
```

The names are illustrative and not a public contract yet. SQLite would require
a file path or an explicit in-memory mode; PostgreSQL would require a validated
connection URL and could expose typed pool, timeout, TLS, and schema settings.
A future MongoDB, DynamoDB, DBOS, or custom backend would define an equivalent
typed configuration object and documented environment mapping without adding
its settings to the core API.

Configuration validation must happen before the process accepts lifecycle work.
Errors must name the selected backend and the missing or invalid setting, while
redacting passwords, tokens, and sensitive parts of connection strings. Backend
configuration, driver installation, credential availability, and storage /
execution compatibility are all startup checks with actionable remediation.

The framework should not dictate how an application obtains secrets. It must
accept fully resolved, explicitly supplied settings so applications can use an
environment loader, a secrets manager, or their existing configuration system.
The framework owns redaction after a secret is supplied; it must not log raw
settings, connection strings, or backend configuration objects by default.

## Schema ownership and migration policy

FastLifecycle owns only its operational schema: tables and indexes needed for
entity state and versioning, append-only history, idempotency, derived jobs,
the outbox, and worker leases. It must never inspect, infer, create, or migrate
application domain tables. A backend may support a configured database schema
or table prefix to make this ownership visible and avoid name collisions.

Each relational backend needs a framework-owned migration ledger and an ordered
set of immutable schema migrations. The migration command determines the
current framework schema version, applies pending revisions under an appropriate
migration lock, and records the resulting version only after success. Normal
application and worker startup may check that the schema is compatible, but
must not apply DDL or schema upgrades implicitly while accepting work.

Alembic is the preferred implementation candidate for the first relational
backends because it provides a tested revision model and SQL dialect support.
This still needs a Stage 0 prototype for SQLite and PostgreSQL. If selected,
FastLifecycle will bundle and execute its own Alembic revisions rather than
requiring users to merge them into, or grant access to, their application's
Alembic environment. It will use a framework-specific version-table name (and
configured schema where applicable), distinct from the application's Alembic
version table. The user may therefore run both migration systems against the
same database because their schema ownership and version ledgers remain
separate.

Production deployment performs an explicit migration step before application
processes start accepting lifecycle commands or jobs. Migrations are
forward-only by default; a downgrade is exposed only for a revision that is
explicitly demonstrated to be safe for existing operational data.

## Integration-test policy

Every supported storage or execution backend requires a focused integration
suite that runs against the real engine or service, not an in-memory fake or a
mock. These suites are the evidence for backend-specific guarantees, including
transactions, isolation, locking, migrations, leasing, retries, recovery, and
the transactional outbox where applicable.

- SQLite integration tests use actual temporary SQLite database files.
- PostgreSQL and other self-hosted databases run as disposable real services,
  normally in containers, with isolated databases per test run.
- Managed-only backends must use isolated real test resources in the provider;
  an emulator can speed up local development but cannot be the sole evidence
  for a supported guarantee.
- Each backend suite includes success, rollback, concurrent command,
  duplicate-command, crash/restart recovery, migration, and cleanup cases as
  applicable to its capabilities.
- Migration suites start from representative prior schemas with persisted
  operational data, test interrupted/contended migration behavior, and verify
  the supported upgrade path before a release.
- Unit tests remain fast and can use test doubles at the backend boundary, but
  no release may claim a backend guarantee that is covered only by unit tests.

The test layout and CI tiers should keep unit tests quick while making real
backend integration tests required for changes affecting a supported backend.
The contributor documentation must state the container or provider credentials
needed to run each integration profile locally and in CI.

## MVP and initial PyPI publication

The MVP is a usable, SQLite-first lifecycle kernel for a single application.
It proves the entity-centric model and its persistence semantics without
claiming a production distributed job platform. Its first public stable
pre-1.0 release is `0.1.0`. It remains publishable only when the publication
gate below is verified in CI; implementation alone is not sufficient reason to
publish.

**MVP scope**

- Installable `fastlifecycle[sqlite,local]` package on every documented Python
  version, with a tested clean-environment installation and a working
  quickstart.
- Typed entities with declared states, transitions, guards, invariants, and
  clear errors for rejected commands.
- SQLite persistence for entity state, optimistic versioning, append-only
  transition history, and accepted-command inputs/results, all queryable with
  ordinary SQL.
- An explicit idempotency key for commands, with documented scope and a stable
  duplicate-command result.
- Atomic persistence of a successful transition's state, version, history, and
  command record. Failed validation, guards, invariants, or persistence leave
  no partial successful transition record.
- Explicit framework-owned schema migrations, a compatibility check at startup,
  and documented deployment steps.
- A local, awaited execution path for transition code and developer testing
  utilities. It must document exactly which result the caller waits for.
- Focused unit tests plus real SQLite integration tests for transaction,
  concurrency, idempotency, migration, and configuration/redaction behavior.

**Deliberately outside the MVP**

- PostgreSQL and every other storage backend.
- Durable background job delivery, a worker fleet, leases, automatic retries,
  crash recovery for jobs, and a transactional outbox. The MVP must not expose
  partial versions of these features as durable execution.
- DBOS, Temporal, broker, MongoDB, DynamoDB, or other runtime/storage
  integrations.
- A generic plugin ecosystem, administrative UI, or mandatory telemetry
  service.

**Publication gate**

Publish `0.1.0` to PyPI only when all of the following are true:

1. Every MVP behavior is public, documented, and covered by tests; illustrative
   README concepts outside the MVP remain clearly labelled as planned.
2. The SQLite/local extras install from the built wheel in a clean environment;
   the package has no unnecessary backend or development dependencies.
3. The full quality suite, real SQLite integration profile, package build, and
   installed-wheel smoke test pass in CI on every supported Python version.
4. The public API exports, migration command, configuration sources, storage
   guarantees, idempotency boundary, and known SQLite limits are documented.
5. A release contains a changelog, upgrade policy for the 0.x line, Apache-2.0
   licensing metadata, and no unredacted credentials or accidental build
   artifacts.

A `0.1.0aN` PyPI pre-release is appropriate only if the project intentionally
wants feedback from external design partners before the MVP gate. It must be
labelled experimental and must not be the first place core behavior is tested.
Until then, source installs, a private package index, or TestPyPI are better
channels for internal iteration.

## Stage 0 — Semantic foundation and prototypes

**Goal:** define the core lifecycle model and remove unresolved semantic risks
before committing to storage or an execution backend.

**Scope**

- Specify typed entities, state declarations, transitions, guards, invariants,
  and transition inputs and outputs.
- Define transition validation and actionable error behavior, including invalid
  source state, failed guards, and invalid inputs.
- Decide the lifecycle definition and schema/versioning model needed to evolve
  definitions safely.
- Define minimal internal contracts separating storage from execution, including
  capabilities, transaction ownership, migrations, and error reporting.
- Define the hexagonal package boundaries, application-owned ports, composition
  boundary, and import rules; add architecture tests before concrete adapters
  are introduced.
- Define the packaging and configuration model for optional backend extras;
  verify that absent optional dependencies produce helpful errors.
- Define typed backend configuration, explicit environment-loading behavior,
  validation, and redaction rules without making environment variables a hidden
  dependency of the core API.
- Define framework schema ownership, a version ledger, explicit migration
  lifecycle, migration locking, and the conditions under which a downgrade is
  safe to support.
- Prototype Alembic as an internal migration engine for SQLite and PostgreSQL;
  confirm it can keep FastLifecycle revisions separate from application-owned
  migration environments.
- Define integration-test profiles and the real-service lifecycle required to
  verify each backend before it becomes supported.
- Prototype awaited execution semantics and job dependency modeling without
  claiming persistence or durability.
- Establish a test vocabulary for state transitions, failures, and cycles in an
  entity lifecycle.

**Exit criteria**

- A documented internal model distinguishes lifecycle state transitions from
  transition-derived job DAGs.
- Prototype tests demonstrate expected transition, guard, invariant, and error
  semantics.
- The team has written down the boundaries of awaited execution, particularly
  that waiting does not hold a database transaction open for external effects.
- Storage and execution contracts identify the capabilities a backend must
  provide without prematurely committing to a generic adapter ecosystem.
- Architecture tests demonstrate that the domain/application core has no
  dependency on persistence drivers, migration tools, runtime SDKs, or
  environment configuration.
- The first SQLite integration profile uses temporary database files and is
  runnable by contributors without a mocked persistence layer.
- Configuration tests establish precedence, validation, and secret redaction
  for the SQLite/local profile before other backend settings are added.
- The migration prototype proves that FastLifecycle can upgrade its own
  SQLite schema without touching application-owned tables.

**Not included**

- A supported durable runtime, worker system, database adapter, or public
  extensibility surface.

## Stage 1 — Local runtime and SQLite persistence

**Goal:** deliver the smallest useful local developer experience with a real,
inspectable persistence model.

**Scope**

- Implement the supported public API for entities, state machines,
  decorator-based transitions, guards, and invariants.
- Add SQLite-backed entity state, versions, append-only transition history, and
  transition input/result records.
- Implement SQLite only as a persistence adapter behind application-owned ports;
  it must not alter domain or application semantics.
- Ship a framework-owned SQLite migration ledger and an explicit migration
  command; startup checks compatibility but does not apply DDL automatically.
- Ship SQLite as the first installable relational storage extra, including any
  non-stdlib dependencies it requires, without making them base dependencies.
- Add optimistic locking and focused errors that identify the entity, expected
  and actual state/version, and attempted transition.
- Implement command idempotency keys and persist the canonical result returned
  for an accepted duplicate command within the documented MVP scope.
- Provide a separately selectable local execution backend and testing utilities
  with minimal configuration.
- Support an explicit SQLite path and an opt-in environment configuration path;
  validate both before executing a transition.
- Make the stored model queryable with ordinary SQL outside the runtime.

**Exit criteria**

- A developer can define, persist, execute, inspect, and test a lifecycle in a
  local SQLite database using explicitly selected storage and execution
  backends.
- The MVP publication gate is met without claiming durable background jobs or
  production multi-process execution.
- Integration tests exercise actual SQLite transaction, locking, history, and
  migration behavior using temporary database files.
- SQLite migrations preserve representative existing FastLifecycle data and do
  not modify unrelated application tables in the same database.
- Installing the core package without optional backends, and installing the
  SQLite/local profile, are both tested as supported packaging paths.
- Missing, invalid, or conflicting SQLite/local configuration fails before work
  is accepted and never exposes a secret in an error or log.
- Tests cover successful, rejected, and failed transitions, plus concurrent
  commands that conflict on an entity version and duplicate commands using the
  same idempotency key.
- The documentation describes exactly what SQLite persistence guarantees and
  what it does not yet guarantee.

**Not included**

- Production PostgreSQL support, asynchronous workers, retries, crash recovery,
  broker integrations, or claims of durable external-effect execution.

## Stage 2 — Production SQL durability and execution

**Goal:** make accepted transitions and their derived work recoverable under
production failures and concurrent requests.

**Scope**

- Add PostgreSQL while retaining the same entity definition and public
  lifecycle model used with SQLite, distributed as a separate optional extra.
- Implement PostgreSQL as a second persistence adapter behind the existing
  application ports; backend-specific behavior must be explicit rather than
  leaking into the domain model.
- Define PostgreSQL connection, TLS, pooling, timeout, and schema configuration
  as typed backend settings with an opt-in environment mapping.
- Run FastLifecycle migrations under a PostgreSQL-safe migration lock and keep
  their revision ledger separate from application migrations.
- Implement idempotency keys and specify their ownership, retention, response,
  and duplicate-command semantics.
- Persist the entity state change, audit history, and derived pending jobs in
  one transaction.
- Introduce a transactional outbox where publication is required, with explicit
  publication and recovery behavior.
- Add a small worker model with leases, retries, timeouts, and restart/crash
  recovery.
- Test database concurrency, duplicate commands, worker retries, and failures
  around commit, publication, and execution boundaries.
- Run PostgreSQL integration tests against a real, disposable PostgreSQL server
  in CI and document the equivalent local profile.

**Exit criteria**

- The transactional boundary and all at-least-once or idempotency guarantees
  are documented and covered by failure-oriented tests.
- A process restart can recover accepted pending work without losing the
  corresponding entity history.
- PostgreSQL and SQLite differences are explicit in documentation and tests.
- Backend configuration rejects unsupported storage/execution combinations
  before accepted work can be processed.
- PostgreSQL configuration integration tests validate connection URLs and
  credential redaction against a real PostgreSQL service.
- PostgreSQL migration integration tests verify upgrades with populated
  operational data, migration contention, and coexistence with application
  tables and a separate application migration ledger.
- Release gates run the SQLite and PostgreSQL real-backend integration suites;
  a unit-test-only result is insufficient for persistence claims.

**Not included**

- A general-purpose distributed orchestration platform, multiple message
  brokers, or a commitment to DBOS or any other runtime backend.

## Stage 3 — Entity-centric operations and observability

**Goal:** let an operator answer what happened to an entity and act safely on
recoverable work.

**Scope**

- Provide entity timelines combining state, transition history, jobs, inputs,
  outputs, attempts, and failures.
- Add inspection APIs and execution-graph views tied to the entity and its
  transition history.
- Introduce structured logs, metrics, and tracing with an entity identifier and
  transition context.
- Define operational controls for retrying, recovering, and diagnosing jobs
  without mutating append-only audit history.

**Exit criteria**

- A documented operator workflow can inspect an entity and correlate a failed
  job with its originating transition and persisted inputs.
- Telemetry validates the same state and execution boundaries described by the
  runtime guarantees.
- Operational actions have authorization, audit, and recovery semantics where
  applicable.

**Not included**

- A mandatory control plane, a full workflow dashboard product, or telemetry
  providers required for local use.

## Stage 4 — Stabilization and deliberate extension points

**Goal:** turn proven core behavior into a stable framework without freezing
premature abstractions.

**Scope**

- Harden public API compatibility, documentation, examples, typing, and
  migration guidance.
- Publish a guarantee matrix that names the storage, transaction, idempotency,
  delivery, and external-effect boundaries for each supported mode.
- Identify extension points only after concrete implementations demonstrate a
  recurring need, beginning with prototypes rather than adapters. This includes
  non-relational storage and third-party execution runtimes.
- Validate packaging, database migrations, upgrade paths, and production
  failure scenarios.

**Exit criteria**

- Supported names are deliberately exported and versioned, with clear upgrade
  and compatibility expectations.
- Extension points are backed by more than one validated use case or remain
  internal.
- The project can make evidence-backed durability and operational claims.

## Cross-stage decisions

The following questions should be resolved by prototypes and recorded before a
stage depends on them:

1. How lifecycle definitions and their schema changes are versioned for
   existing entities.
2. Which values are persisted as transition inputs, results, and job payloads,
   and how they are serialized.
3. The exact idempotency-key scope and the result returned for a duplicate
   command.
4. The lease, retry, and recovery rules that prevent unsafe concurrent job
   execution while acknowledging unavoidable external-effect failure modes.
5. The minimum storage capabilities required by the relational model, and how
   a non-relational backend would make equivalent consistency boundaries
   explicit rather than emulate SQL guarantees implicitly.
6. The execution-backend capabilities and compatibility rules for each storage
   backend, including transaction and recovery ownership.
7. Whether a proposed DBOS or other runtime integration improves the
   entity-centric API and can preserve atomicity with domain data, concurrency
   behavior, and definition versioning.
8. The minimum real-engine integration suite and CI resources needed before a
   backend can be called supported.
9. The stable selector names, typed setting boundaries, environment prefixes,
   secret-provider integration, and configuration precedence rules for each
   supported backend.
10. Whether the Alembic prototype meets the SQLite and PostgreSQL migration
    requirements, or whether a smaller framework-owned migration runner is
    safer and easier to support.
11. The minimal architecture-test mechanism that enforces dependency direction
    without adding unnecessary framework dependencies.

## Suggested delivery discipline

Each increment within a stage should be independently testable and documented.
For persistence or execution work, include success, failure, duplicate-command,
and concurrent-command cases. Do not promote an illustrative README example to
a supported API until the corresponding behavior, documentation, and quality
gates are in place.
