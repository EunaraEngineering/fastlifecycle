"""Command-line entry point for explicit FastLifecycle SQLite migrations."""

from __future__ import annotations

import argparse
import sys

from .persistence.sqlite import SQLiteStorage


def main(argv: list[str] | None = None) -> int:
    """Migrate a SQLite file without starting an application or worker."""
    parser = argparse.ArgumentParser(
        description="Apply FastLifecycle SQLite migrations."
    )
    parser.add_argument("path", help="Path to the SQLite database file")
    arguments = parser.parse_args(argv)
    try:
        SQLiteStorage(arguments.path).migrate()
    except (OSError, ValueError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    sys.exit(main())
