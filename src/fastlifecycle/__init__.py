"""Public API for the SQLite/local FastLifecycle MVP."""

from .application import DispatchResult, FastLifecycle, HistoryRecord
from .configuration import lifecycle_from_environment, redact
from .domain import (
    ConcurrentTriggerError,
    ConfigurationError,
    Entity,
    FastLifecycleError,
    GuardRejectedError,
    IdempotencyConflictError,
    InvalidStateError,
    InvalidTriggerDecisionError,
    InvariantError,
    SchemaNotReadyError,
    Trigger,
    TriggerDecision,
    TriggerError,
    TriggerInputError,
    UnsupportedSchemaError,
    invariant,
    stay,
    transition_to,
    trigger,
)
from .execution import LocalExecution
from .persistence import SCHEMA_VERSION, SQLiteSettings, SQLiteStorage

__all__ = (
    "SCHEMA_VERSION",
    "ConcurrentTriggerError",
    "ConfigurationError",
    "DispatchResult",
    "Entity",
    "FastLifecycle",
    "FastLifecycleError",
    "GuardRejectedError",
    "HistoryRecord",
    "IdempotencyConflictError",
    "InvalidStateError",
    "InvalidTriggerDecisionError",
    "InvariantError",
    "LocalExecution",
    "SQLiteSettings",
    "SQLiteStorage",
    "SchemaNotReadyError",
    "Trigger",
    "TriggerDecision",
    "TriggerError",
    "TriggerInputError",
    "UnsupportedSchemaError",
    "__version__",
    "invariant",
    "lifecycle_from_environment",
    "redact",
    "stay",
    "transition_to",
    "trigger",
)

__version__ = "0.1.0"
