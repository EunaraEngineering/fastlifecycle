"""Application-level records returned by lifecycle operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypeVar

from fastlifecycle.domain.entity import Entity


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """The canonical result of an accepted trigger dispatch."""

    entity_id: str
    entity_type: str
    trigger: str
    outcome: str
    source_state: Any
    target_state: Any
    state_changed: bool
    version: int
    result: Any
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    """An append-only record of one successfully committed trigger."""

    id: int
    entity_id: str
    entity_type: str
    trigger: str
    outcome: str
    source_state: Any
    target_state: Any
    state_changed: bool
    version: int
    inputs: dict[str, Any]
    result: Any
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class StoredEntity:
    """Persistence-neutral entity snapshot used by application ports."""

    entity_id: str
    entity_type: str
    values: dict[str, Any]
    version: int


@dataclass(frozen=True, slots=True)
class StoredCommand:
    """Persistence-neutral accepted trigger result."""

    entity_id: str
    entity_type: str
    trigger: str
    outcome: str
    source_state: Any
    target_state: Any
    state_changed: bool
    version: int
    result: Any
    duplicate: bool


EntityType = TypeVar("EntityType", bound=Entity)


def entity_from_snapshot(
    entity_type: type[EntityType], snapshot: StoredEntity
) -> EntityType:
    """Reconstruct an entity owned by a lifecycle definition from storage."""
    return entity_type._from_persistent_values(
        snapshot.values, entity_id=snapshot.entity_id
    )
