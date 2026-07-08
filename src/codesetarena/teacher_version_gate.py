"""Teacher-side whitelist checks for student package versions."""

from __future__ import annotations

import re
from typing import Any

from .constants import DEFAULT_ALLOWED_STUDENT_VERSION_TAGS
from .packages import PackageError

VERSION_PATTERN = re.compile(r"^v\d+\.\d+\.\d+$")


def normalize_allowed_student_versions(values: Any) -> list[str]:
    if isinstance(values, str):
        raw_values = values.replace("\n", "|").split("|")
    elif isinstance(values, list):
        raw_values = values
    else:
        raw_values = []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        value = str(raw or "").strip()
        if not value:
            continue
        if not VERSION_PATTERN.fullmatch(value):
            raise ValueError("合法学生端版本号必须使用 vX.Y.Z 格式，例如 v7.1.8")
        if value not in seen:
            normalized.append(value)
            seen.add(value)
    if not normalized:
        raise ValueError("合法学生端版本号白名单不能为空")
    return normalized


def default_allowed_student_versions() -> list[str]:
    return list(DEFAULT_ALLOWED_STUDENT_VERSION_TAGS)


def allowed_student_versions_from_settings(settings: dict[str, Any] | None) -> list[str]:
    if not isinstance(settings, dict):
        return default_allowed_student_versions()
    raw_versions = settings.get("allowed_student_versions")
    if raw_versions:
        return normalize_allowed_student_versions(raw_versions)
    return default_allowed_student_versions()


def assert_student_package_version_allowed(manifest: dict[str, Any], settings: dict[str, Any]) -> None:
    version = str(manifest.get("version_tag") or "").strip()
    if not version:
        raise PackageError("学生包缺少 version_tag，无法确认学生端版本")
    if not VERSION_PATTERN.fullmatch(version):
        raise PackageError("学生包 version_tag 格式不合法，必须使用 vX.Y.Z")
    allowed = allowed_student_versions_from_settings(settings)
    if version not in allowed:
        raise PackageError(f"学生端版本 {version} 不在当前允许列表中，请联系助教确认是否放行。")
