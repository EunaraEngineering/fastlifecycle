"""Errors raised when a lifecycle command cannot be accepted."""

from __future__ import annotations


class FastLifecycleError(Exception):
    """Base class for all public FastLifecycle errors."""


class TransitionError(FastLifecycleError):
    """Base class for rejected transitions."""


class TransitionInputError(TransitionError):
    """The arguments supplied to a transition do not match its signature."""


class InvalidStateError(TransitionError):
    """A transition was attempted from a state it does not accept."""

    def __init__(
        self,
        *,
        entity_type: str,
        entity_id: str,
        transition: str,
        expected: tuple[object, ...],
        actual: object,
    ) -> None:
        super().__init__(
            f"Cannot run transition {transition!r} for {entity_type} {entity_id!r}: "
            f"expected state {expected!r}, got {actual!r}."
        )


class GuardRejectedError(TransitionError):
    """A transition guard returned false."""


class InvariantError(TransitionError):
    """An entity invariant did not hold after a transition."""


class ConcurrentTransitionError(TransitionError):
    """The stored entity version changed before the transition was committed."""

    def __init__(
        self, *, entity_type: str, entity_id: str, expected: int, actual: int
    ) -> None:
        super().__init__(
            f"Concurrent update for {entity_type} {entity_id!r}: expected version "
            f"{expected}, got {actual}."
        )


class IdempotencyConflictError(TransitionError):
    """An idempotency key was reused for a different command."""


class StorageError(FastLifecycleError):
    """Base class for persistence and schema errors."""


class SchemaNotReadyError(StorageError):
    """The framework-owned SQLite schema has not been migrated."""


class UnsupportedSchemaError(StorageError):
    """The database was created by a newer FastLifecycle version."""


class ConfigurationError(FastLifecycleError):
    """Backend configuration is missing, invalid, or incompatible."""
