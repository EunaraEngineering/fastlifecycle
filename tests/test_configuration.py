"""Tests for explicit environment composition and safe error rendering."""

from __future__ import annotations

import pytest

from fastlifecycle import ConfigurationError, lifecycle_from_environment, redact
from fastlifecycle.cli import main


def test_environment_loader_requires_supported_complete_profile() -> None:
    with pytest.raises(ConfigurationError, match="FASTLIFECYCLE_STORAGE"):
        lifecycle_from_environment({})
    with pytest.raises(ConfigurationError, match="SQLITE_PATH"):
        lifecycle_from_environment({"FASTLIFECYCLE_STORAGE": "sqlite"})
    with pytest.raises(ConfigurationError, match="EXECUTION"):
        lifecycle_from_environment(
            {
                "FASTLIFECYCLE_STORAGE": "sqlite",
                "FASTLIFECYCLE_SQLITE_PATH": "db.sqlite",
                "FASTLIFECYCLE_EXECUTION": "worker",
            }
        )


def test_environment_loader_composes_without_migrating(tmp_path: object) -> None:
    lifecycle = lifecycle_from_environment(
        {
            "FASTLIFECYCLE_STORAGE": "sqlite",
            "FASTLIFECYCLE_SQLITE_PATH": str(tmp_path) + "/db.sqlite",
        }
    )
    assert lifecycle is not None


def test_redact_hides_url_credentials() -> None:
    assert (
        redact("sqlite://user:secret@example.test/db") == "sqlite://***@example.test/db"
    )


def test_migration_cli_applies_schema_and_reports_bad_path(tmp_path: object) -> None:
    database = str(tmp_path) + "/cli.db"
    assert main([database]) == 0
    with pytest.raises(SystemExit):
        main([str(tmp_path) + "/missing/db.sqlite"])
