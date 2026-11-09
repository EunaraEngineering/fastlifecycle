"""Outbound ports owned by the application layer."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from .models import HistoryRecord, StoredCommand, StoredEntity


class Storage(Protocol):
    """Operations needed by the local lifecycle application service."""

    def check_compatible(self) -> None:
        """Verify the framework schema is ready without changing it."""

    def load(self, *, entity_type: str, entity_id: str) -> StoredEntity | None:
        """Load the latest snapshot for one entity."""

    def find_command(
        self,
        *,
        entity_type: str,
        entity_id: str,
        idempotency_key: str | None,
        trigger: str,
        inputs: dict[str, Any],
    ) -> StoredCommand | None:
        """Find a canonical idempotent result before trigger code is run."""

    def commit(
        self,
        *,
        entity_type: str,
        entity_id: str,
        trigger: str,
        outcome: str,
        source_state: Any,
        target_state: Any,
        state_changed: bool,
        expected_version: int,
        entity_values: dict[str, Any],
        inputs: dict[str, Any],
        result: Any,
        idempotency_key: str | None,
    ) -> StoredCommand:
        """Atomically persist one accepted trigger or return its duplicate."""

    def history(self, *, entity_type: str, entity_id: str) -> list[HistoryRecord]:
        """Return committed trigger records in their append-only order."""


class Execution(Protocol):
    """Awaited execution boundary, independent from persistence."""

    async def run(self, callback: Callable[..., object], **inputs: object) -> object:
        """Run trigger code and await its configured local result."""
