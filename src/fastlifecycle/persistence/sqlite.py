"""SQLite adapter and explicit framework-owned schema migrations."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from fastlifecycle.application.models import HistoryRecord, StoredCommand, StoredEntity
from fastlifecycle.domain.errors import (
    ConcurrentTriggerError,
    IdempotencyConflictError,
    SchemaNotReadyError,
    UnsupportedSchemaError,
)

SCHEMA_VERSION = 2


def _json_default(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _encode(value: object) -> str:
    try:
        return json.dumps(
            value, default=_json_default, sort_keys=True, separators=(",", ":")
        )
    except (TypeError, ValueError) as error:
        raise TypeError(
            "FastLifecycle can persist only JSON-compatible entity fields, inputs, "
            f"and results: {error}"
        ) from error


def _decode(value: str) -> Any:
    return json.loads(value)


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class SQLiteSettings:
    """Explicit configuration for the supported SQLite storage adapter."""

    path: str | Path
    timeout_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not str(self.path):
            raise ValueError("SQLite path must not be empty.")
        if self.timeout_seconds <= 0:
            raise ValueError("SQLite timeout_seconds must be greater than zero.")


class SQLiteStorage:
    """SQLite persistence for the local single-application MVP.

    ``migrate`` is deliberately explicit. Constructing this adapter or checking
    compatibility never creates tables or applies DDL.
    """

    def __init__(self, settings: SQLiteSettings | str | Path) -> None:
        self.settings = (
            settings
            if isinstance(settings, SQLiteSettings)
            else SQLiteSettings(settings)
        )

    @property
    def path(self) -> str:
        return str(self.settings.path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self.settings.timeout_seconds,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            f"PRAGMA busy_timeout = {int(self.settings.timeout_seconds * 1000)}"
        )
        return connection

    def migrate(self) -> None:
        """Apply the current forward-only FastLifecycle schema migration."""
        parent = Path(self.path).parent
        if self.path != ":memory:" and not parent.exists():
            raise ValueError(f"SQLite parent directory does not exist: {parent}")
        with self._connect() as connection:
            connection.execute("BEGIN EXCLUSIVE")
            try:
                exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'fastlifecycle_schema_version'"
                ).fetchone()
                if exists is None:
                    connection.execute(
                        "CREATE TABLE fastlifecycle_schema_version ("
                        "version INTEGER NOT NULL)"
                    )
                    version = 0
                else:
                    row = connection.execute(
                        "SELECT version FROM fastlifecycle_schema_version"
                    ).fetchone()
                    version = 0 if row is None else int(row["version"])
                if version > SCHEMA_VERSION:
                    raise UnsupportedSchemaError(
                        f"FastLifecycle SQLite schema version {version} is newer than "
                        f"this package supports ({SCHEMA_VERSION})."
                    )
                if version < 1:
                    self._apply_v1(connection)
                    version = 1
                if version < 2:
                    self._apply_v2(connection)
                    connection.execute("DELETE FROM fastlifecycle_schema_version")
                    connection.execute(
                        "INSERT INTO fastlifecycle_schema_version(version) VALUES (?)",
                        (SCHEMA_VERSION,),
                    )
                connection.execute("COMMIT")
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _apply_v1(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE fastlifecycle_entities ("
            "entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, "
            "state_json TEXT NOT NULL, data_json TEXT NOT NULL, "
            "version INTEGER NOT NULL, updated_at TEXT NOT NULL, "
            "PRIMARY KEY(entity_type, entity_id))"
        )
        connection.execute(
            "CREATE TABLE fastlifecycle_history ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, entity_type TEXT NOT NULL, "
            "entity_id TEXT NOT NULL, transition_name TEXT NOT NULL, "
            "source_state_json TEXT NOT NULL, target_state_json TEXT NOT NULL, "
            "version INTEGER NOT NULL, inputs_json TEXT NOT NULL, "
            "result_json TEXT NOT NULL, "
            "occurred_at TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE INDEX fastlifecycle_history_entity_idx ON fastlifecycle_history "
            "(entity_type, entity_id, id)"
        )
        connection.execute(
            "CREATE TABLE fastlifecycle_commands ("
            "entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, "
            "idempotency_key TEXT NOT NULL, transition_name TEXT NOT NULL, "
            "inputs_json TEXT NOT NULL, result_json TEXT NOT NULL, "
            "version INTEGER NOT NULL, created_at TEXT NOT NULL, "
            "PRIMARY KEY(entity_type, entity_id, idempotency_key))"
        )

    @staticmethod
    def _apply_v2(connection: sqlite3.Connection) -> None:
        """Upgrade v1 transition records into trigger records without data loss."""
        connection.execute(
            "ALTER TABLE fastlifecycle_history ADD COLUMN trigger_name TEXT"
        )
        connection.execute("ALTER TABLE fastlifecycle_history ADD COLUMN outcome TEXT")
        connection.execute(
            "ALTER TABLE fastlifecycle_history ADD COLUMN state_changed INTEGER "
            "NOT NULL DEFAULT 1"
        )
        connection.execute(
            "UPDATE fastlifecycle_history SET trigger_name = transition_name, "
            "outcome = 'transition'"
        )
        connection.execute(
            "ALTER TABLE fastlifecycle_commands ADD COLUMN trigger_name TEXT"
        )
        connection.execute("ALTER TABLE fastlifecycle_commands ADD COLUMN outcome TEXT")
        connection.execute(
            "ALTER TABLE fastlifecycle_commands ADD COLUMN source_state_json TEXT"
        )
        connection.execute(
            "ALTER TABLE fastlifecycle_commands ADD COLUMN target_state_json TEXT"
        )
        connection.execute(
            "ALTER TABLE fastlifecycle_commands ADD COLUMN state_changed INTEGER"
        )
        connection.execute(
            "UPDATE fastlifecycle_commands SET trigger_name = transition_name, "
            "outcome = 'transition', source_state_json = ("
            "SELECT source_state_json FROM fastlifecycle_history history "
            "WHERE history.entity_type = fastlifecycle_commands.entity_type "
            "AND history.entity_id = fastlifecycle_commands.entity_id "
            "AND history.transition_name = fastlifecycle_commands.transition_name "
            "AND history.version = fastlifecycle_commands.version), "
            "target_state_json = (SELECT target_state_json FROM fastlifecycle_history "
            "history WHERE history.entity_type = fastlifecycle_commands.entity_type "
            "AND history.entity_id = fastlifecycle_commands.entity_id "
            "AND history.transition_name = fastlifecycle_commands.transition_name "
            "AND history.version = fastlifecycle_commands.version), state_changed = 1"
        )

    def check_compatible(self) -> None:
        try:
            with self._connect() as connection:
                table = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'fastlifecycle_schema_version'"
                ).fetchone()
                if table is None:
                    raise SchemaNotReadyError(
                        "FastLifecycle SQLite schema is not installed. "
                        "Run storage.migrate() "
                        "or the fastlifecycle-migrate command before accepting work."
                    )
                row = connection.execute(
                    "SELECT version FROM fastlifecycle_schema_version"
                ).fetchone()
                if row is None or int(row["version"]) < SCHEMA_VERSION:
                    raise SchemaNotReadyError(
                        "FastLifecycle SQLite schema needs migration. "
                        "Run storage.migrate() "
                        "before accepting work."
                    )
                if int(row["version"]) > SCHEMA_VERSION:
                    raise UnsupportedSchemaError(
                        "FastLifecycle SQLite schema was created by a newer "
                        "package version."
                    )
        except sqlite3.OperationalError as error:
            raise SchemaNotReadyError(
                "FastLifecycle could not inspect the SQLite schema. "
                "Run storage.migrate() "
                "against an accessible SQLite database first."
            ) from error

    def load(self, *, entity_type: str, entity_id: str) -> StoredEntity | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT data_json, version FROM fastlifecycle_entities "
                "WHERE entity_type = ? AND entity_id = ?",
                (entity_type, entity_id),
            ).fetchone()
        if row is None:
            return None
        return StoredEntity(
            entity_id=entity_id,
            entity_type=entity_type,
            values=_decode(str(row["data_json"])),
            version=int(row["version"]),
        )

    def find_command(
        self,
        *,
        entity_type: str,
        entity_id: str,
        idempotency_key: str | None,
        trigger: str,
        inputs: dict[str, Any],
    ) -> StoredCommand | None:
        """Return an existing equivalent command before trigger code is invoked."""
        inputs_json = _encode(inputs)
        with self._connect() as connection:
            return self._existing_command(
                connection,
                entity_type=entity_type,
                entity_id=entity_id,
                idempotency_key=idempotency_key,
                trigger=trigger,
                inputs_json=inputs_json,
            )

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
        """Atomically store state, audit history, and a successful trigger record."""
        inputs_json = _encode(inputs)
        result_json = _encode(result)
        values_json = _encode(entity_values)
        source_json = _encode(source_state)
        target_json = _encode(target_state)
        now = _timestamp()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                duplicate = self._existing_command(
                    connection,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    idempotency_key=idempotency_key,
                    trigger=trigger,
                    inputs_json=inputs_json,
                )
                if duplicate is not None:
                    connection.execute("COMMIT")
                    return duplicate
                row = connection.execute(
                    "SELECT version FROM fastlifecycle_entities "
                    "WHERE entity_type = ? AND entity_id = ?",
                    (entity_type, entity_id),
                ).fetchone()
                actual_version = 0 if row is None else int(row["version"])
                if actual_version != expected_version:
                    raise ConcurrentTriggerError(
                        entity_type=entity_type,
                        entity_id=entity_id,
                        expected=expected_version,
                        actual=actual_version,
                    )
                version = actual_version + 1
                if row is None:
                    connection.execute(
                        "INSERT INTO fastlifecycle_entities("
                        "entity_type, entity_id, state_json, data_json, "
                        "version, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            entity_type,
                            entity_id,
                            target_json,
                            values_json,
                            version,
                            now,
                        ),
                    )
                else:
                    connection.execute(
                        "UPDATE fastlifecycle_entities SET state_json = ?, "
                        "data_json = ?, version = ?, updated_at = ? "
                        "WHERE entity_type = ? AND entity_id = ? "
                        "AND version = ?",
                        (
                            target_json,
                            values_json,
                            version,
                            now,
                            entity_type,
                            entity_id,
                            expected_version,
                        ),
                    )
                connection.execute(
                    "INSERT INTO fastlifecycle_history("
                    "entity_type, entity_id, transition_name, trigger_name, outcome, "
                    "source_state_json, target_state_json, state_changed, "
                    "version, inputs_json, result_json, "
                    "occurred_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        entity_type,
                        entity_id,
                        trigger,
                        trigger,
                        outcome,
                        source_json,
                        target_json,
                        int(state_changed),
                        version,
                        inputs_json,
                        result_json,
                        now,
                    ),
                )
                if idempotency_key is not None:
                    connection.execute(
                        "INSERT INTO fastlifecycle_commands("
                        "entity_type, entity_id, idempotency_key, transition_name, "
                        "trigger_name, "
                        "outcome, source_state_json, target_state_json, "
                        "state_changed, inputs_json, result_json, version, "
                        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            entity_type,
                            entity_id,
                            idempotency_key,
                            trigger,
                            trigger,
                            outcome,
                            source_json,
                            target_json,
                            int(state_changed),
                            inputs_json,
                            result_json,
                            version,
                            now,
                        ),
                    )
                connection.execute("COMMIT")
                return StoredCommand(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    trigger=trigger,
                    outcome=outcome,
                    source_state=source_state,
                    target_state=target_state,
                    state_changed=state_changed,
                    version=version,
                    result=result,
                    duplicate=False,
                )
            except BaseException:
                connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _existing_command(
        connection: sqlite3.Connection,
        *,
        entity_type: str,
        entity_id: str,
        idempotency_key: str | None,
        trigger: str,
        inputs_json: str,
    ) -> StoredCommand | None:
        if idempotency_key is None:
            return None
        row = connection.execute(
            "SELECT trigger_name, outcome, source_state_json, target_state_json, "
            "state_changed, inputs_json, result_json, version "
            "FROM fastlifecycle_commands WHERE entity_type = ? AND entity_id = ? "
            "AND idempotency_key = ?",
            (entity_type, entity_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        if row["trigger_name"] != trigger or row["inputs_json"] != inputs_json:
            raise IdempotencyConflictError(
                f"Idempotency key {idempotency_key!r} for {entity_type} {entity_id!r} "
                "was already used for a different trigger."
            )
        return StoredCommand(
            entity_id=entity_id,
            entity_type=entity_type,
            trigger=trigger,
            outcome=str(row["outcome"]),
            source_state=_decode(str(row["source_state_json"])),
            target_state=_decode(str(row["target_state_json"])),
            state_changed=bool(row["state_changed"]),
            version=int(row["version"]),
            result=_decode(str(row["result_json"])),
            duplicate=True,
        )

    def history(self, *, entity_type: str, entity_id: str) -> list[HistoryRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, trigger_name, outcome, source_state_json, "
                "target_state_json, state_changed, version, "
                "inputs_json, result_json, occurred_at FROM fastlifecycle_history "
                "WHERE entity_type = ? AND entity_id = ? ORDER BY id",
                (entity_type, entity_id),
            ).fetchall()
        return [
            HistoryRecord(
                id=int(row["id"]),
                entity_id=entity_id,
                entity_type=entity_type,
                trigger=str(row["trigger_name"]),
                outcome=str(row["outcome"]),
                source_state=_decode(str(row["source_state_json"])),
                target_state=_decode(str(row["target_state_json"])),
                state_changed=bool(row["state_changed"]),
                version=int(row["version"]),
                inputs=_decode(str(row["inputs_json"])),
                result=_decode(str(row["result_json"])),
                occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
            )
            for row in rows
        ]
