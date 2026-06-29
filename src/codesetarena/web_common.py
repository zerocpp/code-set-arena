"""Shared web helpers."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable

from fastapi import UploadFile
from fastapi.responses import RedirectResponse
from starlette.datastructures import URL


def redirect(path: str, **query: str) -> RedirectResponse:
    url = URL(path)
    for key, value in query.items():
        if value:
            url = url.include_query_params(**{key: value})
    return RedirectResponse(str(url), status_code=303)


def safe_filename(name: str | None, fallback: str = "upload.tar.gz") -> str:
    return Path(name or fallback).name


def save_upload(upload: UploadFile, target_dir: Path) -> Path:
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / safe_filename(upload.filename)
    with target.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return target


def find_download(root: Path, filename: str, directories: Iterable[str]) -> Path | None:
    safe_name = safe_filename(filename, "")
    if not safe_name:
        return None
    for directory in directories:
        candidate = root / directory / safe_name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]
