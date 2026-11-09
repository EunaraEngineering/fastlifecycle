"""Use case for locally awaited lifecycle transitions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastlifecycle.domain.entity import (
    Entity,
    Transition,
    validate_guards,
    validate_invariants,
)
from fastlifecycle.domain.errors import InvalidStateError, TransitionInputError

from .models import ExecutionResult, HistoryRecord, StoredEntity, entity_from_snapshot
from .ports import Execution, Storage

EntityType = TypeVar("EntityType", bound=Entity)


class FastLifecycle:
    """Execute entity transitions against an explicitly supplied storage backend.

    Transition code runs in the caller's awaited context before the short SQLite
    commit transaction.  It therefore must not assume that external effects are
    part of the database transaction.
    """

    def __init__(self, storage: Storage, execution: Execution | None = None) -> None:
        self._storage = storage
        self._execution = execution or _InlineExecution()

    async def execute(
        self,
        transition: Transition,
        *,
        entity_id: str,
        idempotency_key: str | None = None,
        expected_version: int | None = None,
        **inputs: object,
    ) -> ExecutionResult:
        """Await a transition and atomically persist a successful command.

        A key is scoped to ``(entity type, entity id)``. Reusing it with a
        different transition or inputs is rejected; reusing it for the same
        command returns the originally stored result with ``duplicate=True``.
        """
        if not isinstance(transition, Transition) or transition.owner is None:
            raise TransitionInputError(
                "Pass a transition declared with @transition, for example "
                "Order.confirm_payment."
            )
        if not entity_id:
            raise TransitionInputError("entity_id must be a non-empty string.")
        if idempotency_key == "":
            raise TransitionInputError(
                "idempotency_key must be non-empty when supplied."
            )
        transition.validate_arguments(dict(inputs))
        self._storage.check_compatible()

        entity_type = transition.owner
        type_name = _entity_type_name(entity_type)
        duplicate = self._storage.find_command(
            entity_type=type_name,
            entity_id=entity_id,
            idempotency_key=idempotency_key,
            transition=transition.name,
            inputs=dict(inputs),
        )
        if duplicate is not None:
            return ExecutionResult(
                entity_id=duplicate.entity_id,
                entity_type=duplicate.entity_type,
                transition=duplicate.transition,
                version=duplicate.version,
                result=duplicate.result,
                duplicate=True,
            )
        snapshot = self._storage.load(entity_type=type_name, entity_id=entity_id)
        entity, current_version = self._entity_for_execution(
            entity_type, entity_id, snapshot
        )
        actual_version = current_version
        required_version = (
            actual_version if expected_version is None else expected_version
        )
        if required_version != actual_version:
            from fastlifecycle.domain.errors import ConcurrentTransitionError

            raise ConcurrentTransitionError(
                entity_type=type_name,
                entity_id=entity_id,
                expected=required_version,
                actual=actual_version,
            )
        state = getattr(entity, "state", None)
        if state not in transition.sources:
            raise InvalidStateError(
                entity_type=type_name,
                entity_id=entity_id,
                transition=transition.name,
                expected=transition.sources,
                actual=state,
            )
        await validate_guards(entity, transition)
        method = transition.function.__get__(entity, entity_type)
        result = await self._execution.run(method, **inputs)
        entity.__dict__["state"] = transition.target
        await validate_invariants(entity, transition)

        stored = self._storage.commit(
            entity_type=type_name,
            entity_id=entity_id,
            transition=transition.name,
            expected_version=required_version,
            source_state=state,
            target_state=transition.target,
            entity_values=entity._persistent_values(),
            inputs=dict(inputs),
            result=result,
            idempotency_key=idempotency_key,
        )
        return ExecutionResult(
            entity_id=stored.entity_id,
            entity_type=stored.entity_type,
            transition=stored.transition,
            version=stored.version,
            result=stored.result,
            duplicate=stored.duplicate,
        )

    def get(
        self, entity_type: type[EntityType], entity_id: str
    ) -> tuple[EntityType, int] | None:
        """Get the latest persisted entity and its optimistic-lock version."""
        self._storage.check_compatible()
        snapshot = self._storage.load(
            entity_type=_entity_type_name(entity_type), entity_id=entity_id
        )
        if snapshot is None:
            return None
        return entity_from_snapshot(entity_type, snapshot), snapshot.version

    def history(self, entity_type: type[Entity], entity_id: str) -> list[HistoryRecord]:
        """Read ordinary append-only lifecycle history."""
        self._storage.check_compatible()
        return self._storage.history(
            entity_type=_entity_type_name(entity_type), entity_id=entity_id
        )

    @staticmethod
    def _entity_for_execution(
        entity_type: type[EntityType], entity_id: str, snapshot: StoredEntity | None
    ) -> tuple[EntityType, int]:
        if snapshot is None:
            entity = entity_type()
            entity._entity_id = entity_id
            return entity, 0
        return entity_from_snapshot(entity_type, snapshot), snapshot.version


def _entity_type_name(entity_type: type[Entity]) -> str:
    return f"{entity_type.__module__}.{entity_type.__qualname__}"


class _InlineExecution:
    """The dependency-free default local executor used when none is selected."""

    async def run(self, callback: Callable[..., object], **inputs: object) -> object:
        value = callback(**inputs)
        return await value if isinstance(value, Awaitable) else value
