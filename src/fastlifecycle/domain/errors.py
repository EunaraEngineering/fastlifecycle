"""Errors raised when a lifecycle command cannot be accepted."""

from __future__ import annotations


class FastLifecycleError(Exception):
    """Base class for all public FastLifecycle errors."""


class TriggerError(FastLifecycleError):
    """Base class for rejected triggers."""


class TriggerInputError(TriggerError):
    """The arguments supplied to a trigger do not match its signature."""


class InvalidStateError(TriggerError):
    """A trigger was attempted from a state it does not accept."""

    def __init__(
        self,
        *,
        entity_type: str,
        entity_id: str,
        trigger: str,
        expected: tuple[object, ...],
        actual: object,
    ) -> None:
        super().__init__(
            f"Cannot dispatch trigger {trigger!r} for {entity_type} {entity_id!r}: "
            f"expected state {expected!r}, got {actual!r}."
        )


class GuardRejectedError(TriggerError):
    """A trigger guard returned false."""


class InvariantError(TriggerError):
    """An entity invariant did not hold after a trigger."""


class InvalidTriggerDecisionError(TriggerError):
    """A trigger handler returned an invalid decision or mutated state directly."""


class ConcurrentTriggerError(TriggerError):
    """The stored entity version changed before the trigger was committed."""

    def __init__(
        self, *, entity_type: str, entity_id: str, expected: int, actual: int
    ) -> None:
        super().__init__(
            f"Concurrent trigger for {entity_type} {entity_id!r}: expected version "
            f"{expected}, got {actual}."
        )


class IdempotencyConflictError(TriggerError):
    """An idempotency key was reused for a different command."""


class StorageError(FastLifecycleError):
    """Base class for persistence and schema errors."""


class SchemaNotReadyError(StorageError):
    """The framework-owned SQLite schema has not been migrated."""


class UnsupportedSchemaError(StorageError):
    """The database was created by a newer FastLifecycle version."""


class ConfigurationError(FastLifecycleError):
    """Backend configuration is missing, invalid, or incompatible."""
