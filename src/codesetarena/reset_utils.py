"""Helpers for clearing one local workflow step."""

from __future__ import annotations

import shutil
from pathlib import Path


def clear_relative_dirs(root: Path, relative_dirs: list[str]) -> None:
    for name in relative_dirs:
        clear_directory_contents(root / name)


def clear_directory_contents(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def remove_file(path: Path) -> None:
    if path.exists():
        path.unlink()
