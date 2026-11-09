"""End-to-end SQLite coverage for the trigger-driven lifecycle kernel."""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable
from enum import Enum
from pathlib import Path
from typing import TypeVar

import pytest

from fastlifecycle import (
    ConcurrentTriggerError,
    Entity,
    FastLifecycle,
    GuardRejectedError,
    IdempotencyConflictError,
    InvalidStateError,
    InvalidTriggerDecisionError,
    InvariantError,
    LocalExecution,
    SchemaNotReadyError,
    SQLiteSettings,
    SQLiteStorage,
    TriggerInputError,
    invariant,
    stay,
    transition_to,
    trigger,
)


class State(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    CANCELLED = "cancelled"


class Invoice(Entity):
    state: State = State.DRAFT
    amount: int = 1
    approved_by: str | None = None

    @trigger(from_states=[State.DRAFT], guards=("can_approve",))
    async def receive_payment(self, approved: bool, actor: str) -> object:
        if approved:
            self.approved_by = actor
            return transition_to(
                State.APPROVED,
                outcome="payment_approved",
                result={"approved_by": actor},
            )
        return stay(outcome="payment_pending", result={"actor": actor})

    @trigger(from_states=State.DRAFT)
    def cancel(self, reason: str) -> object:
        return transition_to(State.CANCELLED, outcome="cancelled", result=reason)

    def can_approve(self) -> bool:
        return self.amount > 0

    @invariant
    def approved_has_actor(self) -> bool:
        return self.state != State.APPROVED or self.approved_by is not None


class RefreshableInvoice(Entity):
    state: State = State.DRAFT

    @trigger
    def receive_message(self, note: str) -> object:
        return stay(outcome="noted", result=note)


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


def test_trigger_resolves_and_persists_its_transition(lifecycle: FastLifecycle) -> None:
    result = run(
        lifecycle.dispatch(
            Invoice.receive_payment,
            entity_id="invoice-1",
            approved=True,
            actor="ada",
            idempotency_key="message-1",
        )
    )
    assert result.trigger == "receive_payment"
    assert result.outcome == "payment_approved"
    assert result.state_changed is True
    assert result.version == 1
    assert result.result == {"approved_by": "ada"}
    entity, version = lifecycle.get(Invoice, "invoice-1") or pytest.fail("missing")
    assert (entity.state, entity.approved_by, version) == (State.APPROVED, "ada", 1)
    history = lifecycle.history(Invoice, "invoice-1")
    assert len(history) == 1
    assert history[0].trigger == "receive_payment"
    assert history[0].outcome == "payment_approved"
    assert history[0].source_state == "draft"
    assert history[0].target_state == "approved"


def test_stay_is_an_accepted_audited_outcome(lifecycle: FastLifecycle) -> None:
    result = run(
        lifecycle.dispatch(
            Invoice.receive_payment,
            entity_id="invoice-1",
            approved=False,
            actor="ada",
        )
    )
    assert (result.outcome, result.state_changed, result.version) == (
        "payment_pending",
        False,
        1,
    )
    entity, version = lifecycle.get(Invoice, "invoice-1") or pytest.fail("missing")
    assert (entity.state, version) == (State.DRAFT, 1)
    history = lifecycle.history(Invoice, "invoice-1")
    assert history[0].state_changed is False
    assert history[0].target_state == "draft"


def test_duplicate_trigger_returns_canonical_result_without_new_history(
    lifecycle: FastLifecycle,
) -> None:
    first = run(
        lifecycle.dispatch(
            Invoice.receive_payment,
            entity_id="invoice-1",
            approved=True,
            actor="ada",
            idempotency_key="message-1",
        )
    )
    duplicate = run(
        lifecycle.dispatch(
            Invoice.receive_payment,
            entity_id="invoice-1",
            approved=True,
            actor="ada",
            idempotency_key="message-1",
        )
    )
    assert duplicate.duplicate is True
    assert duplicate.outcome == first.outcome
    assert duplicate.result == first.result
    assert len(lifecycle.history(Invoice, "invoice-1")) == 1


def test_reused_key_for_different_trigger_input_is_rejected(
    lifecycle: FastLifecycle,
) -> None:
    run(
        lifecycle.dispatch(
            Invoice.receive_payment,
            entity_id="invoice-1",
            approved=True,
            actor="ada",
            idempotency_key="message-1",
        )
    )
    with pytest.raises(IdempotencyConflictError):
        run(
            lifecycle.dispatch(
                Invoice.receive_payment,
                entity_id="invoice-1",
                approved=True,
                actor="grace",
                idempotency_key="message-1",
            )
        )


def test_rejections_leave_no_accepted_trigger_record(lifecycle: FastLifecycle) -> None:
    with pytest.raises(TriggerInputError):
        run(lifecycle.dispatch(Invoice.cancel, entity_id="invoice-1"))

    class Guarded(Entity):
        state: State = State.DRAFT

        @trigger(from_states=State.DRAFT, guards=("allowed",))
        def receive(self) -> object:
            return stay(outcome="ignored")

        def allowed(self) -> bool:
            return False

    with pytest.raises(GuardRejectedError):
        run(lifecycle.dispatch(Guarded.receive, entity_id="invoice-1"))
    assert lifecycle.get(Guarded, "invoice-1") is None


def test_state_and_version_conflicts_are_actionable(lifecycle: FastLifecycle) -> None:
    run(lifecycle.dispatch(Invoice.cancel, entity_id="invoice-1", reason="nope"))
    with pytest.raises(InvalidStateError):
        run(lifecycle.dispatch(Invoice.cancel, entity_id="invoice-1", reason="again"))
    with pytest.raises(ConcurrentTriggerError):
        run(
            lifecycle.dispatch(
                Invoice.cancel,
                entity_id="invoice-1",
                reason="old",
                expected_version=0,
            )
        )


def test_invalid_decisions_and_direct_state_mutation_do_not_commit(
    lifecycle: FastLifecycle,
) -> None:
    class Broken(Entity):
        state: State = State.DRAFT

        @trigger
        def no_decision(self) -> object:
            return None

        @trigger
        def direct_mutation(self) -> object:
            self.state = State.APPROVED
            return transition_to(State.APPROVED, outcome="invalid")

        @trigger
        def missing_outcome(self) -> object:
            return stay(outcome="")

        @trigger
        def wrong_target(self) -> object:
            return transition_to("approved", outcome="invalid")

    with pytest.raises(InvalidTriggerDecisionError, match="must return"):
        run(lifecycle.dispatch(Broken.no_decision, entity_id="invoice-1"))
    with pytest.raises(InvalidTriggerDecisionError, match="modified state"):
        run(lifecycle.dispatch(Broken.direct_mutation, entity_id="invoice-2"))
    with pytest.raises(InvalidTriggerDecisionError, match="non-empty outcome"):
        run(lifecycle.dispatch(Broken.missing_outcome, entity_id="invoice-3"))
    with pytest.raises(InvalidTriggerDecisionError, match="does not match"):
        run(lifecycle.dispatch(Broken.wrong_target, entity_id="invoice-4"))
    assert lifecycle.get(Broken, "invoice-1") is None
    assert lifecycle.get(Broken, "invoice-2") is None
    assert lifecycle.get(Broken, "invoice-3") is None
    assert lifecycle.get(Broken, "invoice-4") is None


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

        @trigger
        def receive(self) -> object:
            return transition_to(State.APPROVED, outcome="approved")

        @invariant
        def is_valid(self) -> bool:
            return False

    storage = SQLiteStorage(tmp_path / "broken.db")
    storage.migrate()
    local = FastLifecycle(storage)
    with pytest.raises(InvariantError):
        run(local.dispatch(BrokenInvoice.receive, entity_id="invoice-1"))
    assert local.get(BrokenInvoice, "invoice-1") is None


def test_type_validation_and_entity_construction_errors(
    lifecycle: FastLifecycle,
) -> None:
    with pytest.raises(TriggerInputError, match="approved"):
        run(
            lifecycle.dispatch(
                Invoice.receive_payment,
                entity_id="bad-input",
                approved="yes",
                actor="ada",
            )
        )
    with pytest.raises(TypeError, match="Unknown fields"):
        Invoice(unknown=True)

    class Required(Entity):
        state: State = State.DRAFT
        label: str

    with pytest.raises(TypeError, match="Missing required"):
        Required()
    with pytest.raises(TypeError, match="must be"):
        Required(label=1)


def test_trigger_without_state_filter_updates_existing_entity(
    lifecycle: FastLifecycle,
) -> None:
    first = run(
        lifecycle.dispatch(
            RefreshableInvoice.receive_message, entity_id="invoice-1", note="first"
        )
    )
    second = run(
        lifecycle.dispatch(
            RefreshableInvoice.receive_message, entity_id="invoice-1", note="again"
        )
    )
    assert (first.version, second.version, second.state_changed) == (1, 2, False)
    assert callable(RefreshableInvoice().receive_message)


def test_async_callable_guard_and_unserializable_result_rolls_back(
    lifecycle: FastLifecycle,
) -> None:
    async def allowed(entity: Entity) -> bool:
        return entity.entity_id == "allowed"

    class Guarded(Entity):
        state: State = State.DRAFT

        @trigger(guards=(allowed,))
        def receive(self) -> object:
            return stay(outcome="accepted", result=object())

    with pytest.raises(TypeError, match="JSON-compatible"):
        run(lifecycle.dispatch(Guarded.receive, entity_id="allowed"))
    assert lifecycle.get(Guarded, "allowed") is None
    with pytest.raises(GuardRejectedError):
        run(lifecycle.dispatch(Guarded.receive, entity_id="blocked"))


def test_v1_schema_is_upgraded_to_trigger_history(tmp_path: Path) -> None:
    path = tmp_path / "v1.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE fastlifecycle_schema_version (version INTEGER)"
        )
        connection.execute("INSERT INTO fastlifecycle_schema_version VALUES (1)")
        connection.execute(
            "CREATE TABLE fastlifecycle_entities (entity_type TEXT, entity_id TEXT, "
            "state_json TEXT, data_json TEXT, version INTEGER, updated_at TEXT)"
        )
        connection.execute(
            "CREATE TABLE fastlifecycle_history (id INTEGER PRIMARY KEY, "
            "entity_type TEXT, entity_id TEXT, transition_name TEXT, "
            "source_state_json TEXT, target_state_json TEXT, version INTEGER, "
            "inputs_json TEXT, result_json TEXT, "
            "occurred_at TEXT)"
        )
        connection.execute(
            "CREATE TABLE fastlifecycle_commands (entity_type TEXT, entity_id TEXT, "
            "idempotency_key TEXT, transition_name TEXT, inputs_json TEXT, "
            "result_json TEXT, "
            "version INTEGER, created_at TEXT)"
        )
        connection.execute(
            "INSERT INTO fastlifecycle_history VALUES "
            "(1, 'Invoice', 'one', 'approve', '\"draft\"', '\"approved\"', "
            "1, '{}', 'null', '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO fastlifecycle_commands VALUES "
            "('Invoice', 'one', 'key', 'approve', '{}', 'null', 1, "
            "'2026-01-01T00:00:00+00:00')"
        )
    storage = SQLiteStorage(path)
    storage.migrate()
    storage.check_compatible()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT trigger_name, outcome FROM fastlifecycle_history"
        ).fetchone() == ("approve", "transition")


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
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE fastlifecycle_schema_version SET version = 3")
    with pytest.raises(Exception, match="newer"):
        storage.check_compatible()
    with pytest.raises(Exception, match="newer"):
        storage.migrate()
