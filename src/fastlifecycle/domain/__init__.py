"""Lifecycle domain primitives with no persistence dependencies."""

from .entity import Entity, Transition, invariant, transition
from .errors import (
    ConcurrentTransitionError,
    ConfigurationError,
    FastLifecycleError,
    GuardRejectedError,
    IdempotencyConflictError,
    InvalidStateError,
    InvariantError,
    SchemaNotReadyError,
    TransitionError,
    TransitionInputError,
    UnsupportedSchemaError,
)

__all__ = (
    "ConcurrentTransitionError",
    "ConfigurationError",
    "Entity",
    "FastLifecycleError",
    "GuardRejectedError",
    "IdempotencyConflictError",
    "InvalidStateError",
    "InvariantError",
    "SchemaNotReadyError",
    "Transition",
    "TransitionError",
    "TransitionInputError",
    "UnsupportedSchemaError",
    "invariant",
    "transition",
)
