"""Public API for the SQLite/local FastLifecycle MVP."""

from .application import ExecutionResult, FastLifecycle, HistoryRecord
from .configuration import lifecycle_from_environment, redact
from .domain import (
    ConcurrentTransitionError,
    ConfigurationError,
    Entity,
    FastLifecycleError,
    GuardRejectedError,
    IdempotencyConflictError,
    InvalidStateError,
    InvariantError,
    SchemaNotReadyError,
    Transition,
    TransitionError,
    TransitionInputError,
    UnsupportedSchemaError,
    invariant,
    transition,
)
from .execution import LocalExecution
from .persistence import SCHEMA_VERSION, SQLiteSettings, SQLiteStorage

__all__ = (
    "SCHEMA_VERSION",
    "ConcurrentTransitionError",
    "ConfigurationError",
    "Entity",
    "ExecutionResult",
    "FastLifecycle",
    "FastLifecycleError",
    "GuardRejectedError",
    "HistoryRecord",
    "IdempotencyConflictError",
    "InvalidStateError",
    "InvariantError",
    "LocalExecution",
    "SQLiteSettings",
    "SQLiteStorage",
    "SchemaNotReadyError",
    "Transition",
    "TransitionError",
    "TransitionInputError",
    "UnsupportedSchemaError",
    "__version__",
    "invariant",
    "lifecycle_from_environment",
    "redact",
    "transition",
)

__version__ = "0.1.0"
