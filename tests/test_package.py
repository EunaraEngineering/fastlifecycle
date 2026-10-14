"""Tests for the package's public metadata."""

from fastlifecycle import __version__


def test_version_is_exposed() -> None:
    """Expose a package version as part of the public API."""
    assert __version__ == "0.1.0"
