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
        transition: str,
        inputs: dict[str, Any],
    ) -> StoredCommand | None:
        """Find a canonical idempotent result before transition code is run."""

    def commit(
        self,
        *,
        entity_type: str,
        entity_id: str,
        transition: str,
        expected_version: int,
        source_state: Any,
        target_state: Any,
        entity_values: dict[str, Any],
        inputs: dict[str, Any],
        result: Any,
        idempotency_key: str | None,
    ) -> StoredCommand:
        """Atomically persist one accepted transition or return its duplicate."""

    def history(self, *, entity_type: str, entity_id: str) -> list[HistoryRecord]:
        """Return committed transition records in their append-only order."""


class Execution(Protocol):
    """Awaited execution boundary, independent from persistence."""

    async def run(self, callback: Callable[..., object], **inputs: object) -> object:
        """Run transition code and await its configured local result."""
