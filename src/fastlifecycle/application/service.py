"""Use case for locally awaited trigger dispatch."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastlifecycle.domain.entity import (
    Entity,
    Trigger,
    TriggerDecision,
    validate_guards,
    validate_invariants,
)
from fastlifecycle.domain.errors import (
    ConcurrentTriggerError,
    InvalidStateError,
    InvalidTriggerDecisionError,
    TriggerInputError,
)

from .models import (
    DispatchResult,
    HistoryRecord,
    StoredCommand,
    StoredEntity,
    entity_from_snapshot,
)
from .ports import Execution, Storage

EntityType = TypeVar("EntityType", bound=Entity)


class FastLifecycle:
    """Dispatch public triggers against explicitly supplied backend instances."""

    def __init__(self, storage: Storage, execution: Execution | None = None) -> None:
        self._storage = storage
        self._execution = execution or _InlineExecution()

    async def dispatch(
        self,
        trigger: Trigger,
        *,
        entity_id: str,
        idempotency_key: str | None = None,
        expected_version: int | None = None,
        **inputs: object,
    ) -> DispatchResult:
        """Await and atomically persist an accepted trigger decision."""
        if not isinstance(trigger, Trigger) or trigger.owner is None:
            raise TriggerInputError(
                "Pass a trigger declared with @trigger, for example "
                "Order.receive_message."
            )
        if not entity_id:
            raise TriggerInputError("entity_id must be a non-empty string.")
        if idempotency_key == "":
            raise TriggerInputError("idempotency_key must be non-empty when supplied.")
        trigger.validate_arguments(dict(inputs))
        self._storage.check_compatible()

        entity_type = trigger.owner
        type_name = _entity_type_name(entity_type)
        duplicate = self._storage.find_command(
            entity_type=type_name,
            entity_id=entity_id,
            idempotency_key=idempotency_key,
            trigger=trigger.name,
            inputs=dict(inputs),
        )
        if duplicate is not None:
            return _dispatch_result(duplicate)
        snapshot = self._storage.load(entity_type=type_name, entity_id=entity_id)
        entity, current_version = self._entity_for_dispatch(
            entity_type, entity_id, snapshot
        )
        required_version = (
            current_version if expected_version is None else expected_version
        )
        if required_version != current_version:
            raise ConcurrentTriggerError(
                entity_type=type_name,
                entity_id=entity_id,
                expected=required_version,
                actual=current_version,
            )
        source_state = entity.__dict__["state"]
        if trigger.sources and source_state not in trigger.sources:
            raise InvalidStateError(
                entity_type=type_name,
                entity_id=entity_id,
                trigger=trigger.name,
                expected=trigger.sources,
                actual=source_state,
            )
        await validate_guards(entity, trigger)
        method = trigger.function.__get__(entity, entity_type)
        decision = await self._execution.run(method, **inputs)
        if not isinstance(decision, TriggerDecision):
            raise InvalidTriggerDecisionError(
                f"Trigger {trigger.name!r} must return stay(...) or transition_to(...)."
            )
        if not decision.outcome:
            raise InvalidTriggerDecisionError(
                f"Trigger {trigger.name!r} must provide a non-empty outcome."
            )
        if entity.__dict__["state"] != source_state:
            raise InvalidTriggerDecisionError(
                f"Trigger {trigger.name!r} modified state directly; return "
                "transition_to(...) instead."
            )
        target_state = (
            source_state if decision.target_state is None else decision.target_state
        )
        if not isinstance(target_state, type(source_state)):
            raise InvalidTriggerDecisionError(
                f"Trigger {trigger.name!r} chose state {target_state!r}, which does "
                f"not match {type(source_state).__name__}."
            )
        state_changed = target_state != source_state
        entity.__dict__["state"] = target_state
        await validate_invariants(entity, trigger)

        stored = self._storage.commit(
            entity_type=type_name,
            entity_id=entity_id,
            trigger=trigger.name,
            outcome=decision.outcome,
            source_state=source_state,
            target_state=target_state,
            state_changed=state_changed,
            expected_version=required_version,
            entity_values=entity._persistent_values(),
            inputs=dict(inputs),
            result=decision.result,
            idempotency_key=idempotency_key,
        )
        return _dispatch_result(stored)

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
        """Read ordinary append-only trigger history."""
        self._storage.check_compatible()
        return self._storage.history(
            entity_type=_entity_type_name(entity_type), entity_id=entity_id
        )

    @staticmethod
    def _entity_for_dispatch(
        entity_type: type[EntityType], entity_id: str, snapshot: StoredEntity | None
    ) -> tuple[EntityType, int]:
        if snapshot is None:
            entity = entity_type()
            entity._entity_id = entity_id
            return entity, 0
        return entity_from_snapshot(entity_type, snapshot), snapshot.version


def _dispatch_result(stored: StoredCommand) -> DispatchResult:
    return DispatchResult(
        entity_id=stored.entity_id,
        entity_type=stored.entity_type,
        trigger=stored.trigger,
        outcome=stored.outcome,
        source_state=stored.source_state,
        target_state=stored.target_state,
        state_changed=stored.state_changed,
        version=stored.version,
        result=stored.result,
        duplicate=stored.duplicate,
    )


def _entity_type_name(entity_type: type[Entity]) -> str:
    return f"{entity_type.__module__}.{entity_type.__qualname__}"


class _InlineExecution:
    """The dependency-free default local executor used when none is selected."""

    async def run(self, callback: Callable[..., object], **inputs: object) -> object:
        value = callback(**inputs)
        return await value if isinstance(value, Awaitable) else value
