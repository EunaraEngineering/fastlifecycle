"""End-to-end SQLite coverage for the supported local lifecycle kernel."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable
from enum import Enum
from pathlib import Path
from typing import TypeVar

import pytest

from fastlifecycle import (
    ConcurrentTransitionError,
    Entity,
    FastLifecycle,
    GuardRejectedError,
    IdempotencyConflictError,
    InvalidStateError,
    InvariantError,
    LocalExecution,
    SchemaNotReadyError,
    SQLiteSettings,
    SQLiteStorage,
    TransitionInputError,
    invariant,
    transition,
)


class State(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    CANCELLED = "cancelled"


class Invoice(Entity):
    state: State = State.DRAFT
    amount: int = 1
    approved_by: str | None = None

    @transition(source=State.DRAFT, target=State.APPROVED, guards=("can_approve",))
    async def approve(self, approved_by: str) -> dict[str, str]:
        self.approved_by = approved_by
        return {"approved_by": approved_by}

    @transition(source=State.DRAFT, target=State.CANCELLED)
    def cancel(self, reason: str) -> str:
        return reason

    def can_approve(self) -> bool:
        return self.amount > 0

    @invariant
    def approved_has_actor(self) -> bool:
        return self.state != State.APPROVED or self.approved_by is not None


class ReversibleInvoice(Entity):
    state: State = State.DRAFT

    @transition(source=[State.DRAFT, State.APPROVED], target=State.APPROVED)
    def approve(self, note: str) -> str:
        return note


@pytest.fixture
def lifecycle(tmp_path: Path) -> FastLifecycle:
    storage = SQLiteStorage(tmp_path / "lifecycle.db")
    storage.migrate()
    return FastLifecycle(storage, LocalExecution())


Result = TypeVar("Result")


def run(awaitable: Awaitable[Result]) -> Result:
    async def wait() -> Result:
        return await awaitable

    return asyncio.run(wait())


def test_successful_transition_is_persisted_and_queryable(
    lifecycle: FastLifecycle,
) -> None:
    result = run(
        lifecycle.execute(
            Invoice.approve,
            entity_id="invoice-1",
            approved_by="ada",
            idempotency_key="request-1",
        )
    )
    assert result.version == 1
    assert result.result == {"approved_by": "ada"}
    entity, version = lifecycle.get(Invoice, "invoice-1") or pytest.fail("missing")
    assert (entity.state, entity.approved_by, version) == (State.APPROVED, "ada", 1)
    history = lifecycle.history(Invoice, "invoice-1")
    assert len(history) == 1
    assert history[0].inputs == {"approved_by": "ada"}
    assert history[0].source_state == "draft"
    assert history[0].target_state == "approved"


def test_duplicate_key_returns_canonical_result_without_new_history(
    lifecycle: FastLifecycle,
) -> None:
    first = run(
        lifecycle.execute(
            Invoice.approve,
            entity_id="invoice-1",
            approved_by="ada",
            idempotency_key="request-1",
        )
    )
    duplicate = run(
        lifecycle.execute(
            Invoice.approve,
            entity_id="invoice-1",
            approved_by="ada",
            idempotency_key="request-1",
        )
    )
    assert first.duplicate is False
    assert duplicate.duplicate is True
    assert duplicate.result == first.result
    assert len(lifecycle.history(Invoice, "invoice-1")) == 1


def test_reused_key_for_a_different_command_is_rejected(
    lifecycle: FastLifecycle,
) -> None:
    run(
        lifecycle.execute(
            Invoice.approve,
            entity_id="invoice-1",
            approved_by="ada",
            idempotency_key="request-1",
        )
    )
    with pytest.raises(IdempotencyConflictError):
        run(
            lifecycle.execute(
                Invoice.approve,
                entity_id="invoice-1",
                approved_by="grace",
                idempotency_key="request-1",
            )
        )


def test_rejections_leave_no_successful_record(lifecycle: FastLifecycle) -> None:
    with pytest.raises(TransitionInputError):
        run(lifecycle.execute(Invoice.cancel, entity_id="invoice-1"))

    class Guarded(Entity):
        state: State = State.DRAFT

        @transition(source=State.DRAFT, target=State.APPROVED, guards=("allowed",))
        def approve(self) -> None:
            pass

        def allowed(self) -> bool:
            return False

    with pytest.raises(GuardRejectedError):
        run(lifecycle.execute(Guarded.approve, entity_id="invoice-1"))
    assert lifecycle.get(Guarded, "invoice-1") is None


def test_state_and_version_conflicts_are_actionable(lifecycle: FastLifecycle) -> None:
    run(lifecycle.execute(Invoice.cancel, entity_id="invoice-1", reason="nope"))
    with pytest.raises(InvalidStateError):
        run(lifecycle.execute(Invoice.cancel, entity_id="invoice-1", reason="again"))
    with pytest.raises(ConcurrentTransitionError):
        run(
            lifecycle.execute(
                Invoice.cancel,
                entity_id="invoice-1",
                reason="old",
                expected_version=0,
            )
        )


def test_schema_is_explicit_and_unrelated_tables_are_preserved(tmp_path: Path) -> None:
    path = tmp_path / "shared.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE application_data (id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO application_data VALUES (1)")
    storage = SQLiteStorage(path)
    with pytest.raises(SchemaNotReadyError):
        FastLifecycle(storage).get(Invoice, "invoice-1")
    storage.migrate()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT id FROM application_data").fetchone() == (1,)


def test_invariant_failure_does_not_commit(tmp_path: Path) -> None:
    class BrokenInvoice(Entity):
        state: State = State.DRAFT

        @transition(source=State.DRAFT, target=State.APPROVED)
        def approve(self) -> None:
            pass

        @invariant
        def is_valid(self) -> bool:
            return False

    storage = SQLiteStorage(tmp_path / "broken.db")
    storage.migrate()
    local = FastLifecycle(storage)
    with pytest.raises(InvariantError):
        run(local.execute(BrokenInvoice.approve, entity_id="invoice-1"))
    assert local.get(BrokenInvoice, "invoice-1") is None


def test_type_validation_and_entity_construction_errors(
    lifecycle: FastLifecycle,
) -> None:
    with pytest.raises(TransitionInputError, match="approved_by"):
        run(lifecycle.execute(Invoice.approve, entity_id="bad-input", approved_by=1))
    with pytest.raises(TypeError, match="Unknown fields"):
        Invoice(unknown=True)

    class Required(Entity):
        state: State = State.DRAFT
        label: str

    with pytest.raises(TypeError, match="Missing required"):
        Required()
    with pytest.raises(TypeError, match="must be"):
        Required(label=1)


def test_updates_existing_row_and_supports_bound_transition(
    lifecycle: FastLifecycle,
) -> None:
    first = run(
        lifecycle.execute(
            ReversibleInvoice.approve, entity_id="invoice-1", note="first"
        )
    )
    second = run(
        lifecycle.execute(
            ReversibleInvoice.approve, entity_id="invoice-1", note="again"
        )
    )
    assert (first.version, second.version) == (1, 2)
    assert callable(ReversibleInvoice().approve)


def test_async_callable_guard_and_unserializable_result_rolls_back(
    lifecycle: FastLifecycle,
) -> None:
    async def allowed(entity: Entity) -> bool:
        return entity.entity_id == "allowed"

    class Guarded(Entity):
        state: State = State.DRAFT

        @transition(source=State.DRAFT, target=State.APPROVED, guards=(allowed,))
        def approve(self) -> object:
            return object()

    with pytest.raises(TypeError, match="JSON-compatible"):
        run(lifecycle.execute(Guarded.approve, entity_id="allowed"))
    assert lifecycle.get(Guarded, "allowed") is None
    with pytest.raises(GuardRejectedError):
        run(lifecycle.execute(Guarded.approve, entity_id="blocked"))


def test_migration_validation_and_forward_compatibility(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SQLiteSettings("")
    with pytest.raises(ValueError, match="greater than zero"):
        SQLiteSettings(tmp_path / "a.db", timeout_seconds=0)
    with pytest.raises(ValueError, match="parent directory"):
        SQLiteStorage(tmp_path / "missing" / "db.sqlite").migrate()

    path = tmp_path / "versioned.db"
    storage = SQLiteStorage(path)
    storage.migrate()
    storage.migrate()
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE fastlifecycle_schema_version SET version = 2")
    with pytest.raises(Exception, match="newer"):
        storage.check_compatible()
    with pytest.raises(Exception, match="newer"):
        storage.migrate()
