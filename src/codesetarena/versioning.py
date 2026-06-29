"""System version helpers for snapshot compatibility."""

from __future__ import annotations

from . import __version__


def snapshot_version(system_version: str | None = None) -> str:
    """Return the major.minor compatibility version used by problem snapshots."""
    version = (system_version or __version__).strip()
    parts = version.split(".")
    if len(parts) < 2:
        return version
    return ".".join(parts[:2])
