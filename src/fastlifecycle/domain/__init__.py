"""Lifecycle domain primitives with no persistence dependencies."""

from .entity import (
    Entity,
    Trigger,
    TriggerDecision,
    invariant,
    stay,
    transition_to,
    trigger,
)
from .errors import (
    ConcurrentTriggerError,
    ConfigurationError,
    FastLifecycleError,
    GuardRejectedError,
    IdempotencyConflictError,
    InvalidStateError,
    InvalidTriggerDecisionError,
    InvariantError,
    SchemaNotReadyError,
    TriggerError,
    TriggerInputError,
    UnsupportedSchemaError,
)

__all__ = (
    "ConcurrentTriggerError",
    "ConfigurationError",
    "Entity",
    "FastLifecycleError",
    "GuardRejectedError",
    "IdempotencyConflictError",
    "InvalidStateError",
    "InvalidTriggerDecisionError",
    "InvariantError",
    "SchemaNotReadyError",
    "Trigger",
    "TriggerDecision",
    "TriggerError",
    "TriggerInputError",
    "UnsupportedSchemaError",
    "invariant",
    "stay",
    "transition_to",
    "trigger",
)
