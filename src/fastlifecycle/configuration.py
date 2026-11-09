"""Opt-in configuration loading for the SQLite/local MVP profile."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from .application.service import FastLifecycle
from .domain.errors import ConfigurationError
from .execution import LocalExecution
from .persistence.sqlite import SQLiteSettings, SQLiteStorage


def redact(value: str) -> str:
    """Redact credentials if a value resembling a connection URL is reported."""
    return re.sub(r"(?<=//)[^/@:]+(?::[^/@]*)?@", "***@", value)


def lifecycle_from_environment(
    environ: Mapping[str, str] | None = None,
) -> FastLifecycle:
    """Build the explicitly supported SQLite/local composition from an env mapping.

    Environment access is opt-in; passing a mapping makes configuration tests and
    embedding applications deterministic.
    """
    values = os.environ if environ is None else environ
    storage = values.get("FASTLIFECYCLE_STORAGE")
    execution = values.get("FASTLIFECYCLE_EXECUTION", "local")
    if storage != "sqlite":
        rendered = "unset" if storage is None else repr(storage)
        raise ConfigurationError(
            "FASTLIFECYCLE_STORAGE must be 'sqlite' for the current MVP; got "
            f"{rendered}."
        )
    if execution != "local":
        raise ConfigurationError(
            "FASTLIFECYCLE_EXECUTION must be 'local' for the current MVP; got "
            f"{execution!r}."
        )
    path = values.get("FASTLIFECYCLE_SQLITE_PATH")
    if not path:
        raise ConfigurationError(
            "FASTLIFECYCLE_SQLITE_PATH is required when FASTLIFECYCLE_STORAGE='sqlite'."
        )
    try:
        settings = SQLiteSettings(path=path)
    except ValueError as error:
        raise ConfigurationError(
            f"Invalid SQLite configuration: {redact(str(error))}"
        ) from error
    return FastLifecycle(SQLiteStorage(settings), LocalExecution())
