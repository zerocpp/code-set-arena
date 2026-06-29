"""Package naming and validation rules."""

from __future__ import annotations

import re
from pathlib import Path

from .constants import (
    KIND_COURSE_STATS,
    KIND_OFFICIAL_EVAL,
    KIND_PROBLEMS,
    KIND_REVIEW_ASSIGNMENT,
    KIND_REVIEW_FEEDBACK,
    KIND_REVIEWS,
    KIND_REVISION,
    ROLE_STUDENT,
    ROLE_TEACHER,
    STAGE1,
    STAGE2,
    STAGE3,
    STAGE4,
)


class PackageNameError(ValueError):
    """Raised when an archive filename does not match the v7 contract."""


STUDENT_NUMBER_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def student_package_name(student_number: str, stage: str, kind: str) -> str:
    _validate_student_number(student_number)
    _validate_student_combo(stage, kind)
    return f"{student_number}-{ROLE_STUDENT}-{stage}-{kind}.tar.gz"


def teacher_package_name(student_number: str, stage: str, kind: str) -> str:
    _validate_student_number(student_number)
    _validate_teacher_combo(stage, kind)
    return f"{student_number}-{ROLE_TEACHER}-{stage}-{kind}.tar.gz"


def teacher_bulk_name(stage: str, kind: str, suffix: str = ".tar.gz") -> str:
    if stage == STAGE4 and kind == KIND_COURSE_STATS:
        suffix = ".json"
    _validate_teacher_bulk_combo(stage, kind)
    return f"{ROLE_TEACHER}-{stage}-{kind}{suffix}"


def assert_student_archive(path: Path, student_number: str, stage: str, kind: str) -> None:
    expected = student_package_name(student_number, stage, kind)
    if path.name != expected:
        raise PackageNameError(f"expected {expected}, got {path.name}")


def assert_teacher_archive(path: Path, student_number: str, stage: str, kind: str) -> None:
    expected = teacher_package_name(student_number, stage, kind)
    if path.name != expected:
        raise PackageNameError(f"expected {expected}, got {path.name}")


def _validate_student_number(student_number: str) -> None:
    if not student_number or not STUDENT_NUMBER_RE.match(student_number):
        raise PackageNameError("student number must contain only letters, digits, _ or -")


def _validate_student_combo(stage: str, kind: str) -> None:
    allowed = {
        (STAGE1, KIND_PROBLEMS),
        (STAGE2, KIND_REVIEWS),
        (STAGE3, KIND_REVISION),
    }
    if (stage, kind) not in allowed:
        raise PackageNameError(f"invalid student package combo: {stage}/{kind}")


def _validate_teacher_combo(stage: str, kind: str) -> None:
    allowed = {
        (STAGE2, KIND_REVIEW_ASSIGNMENT),
        (STAGE3, KIND_REVIEW_FEEDBACK),
    }
    if (stage, kind) not in allowed:
        raise PackageNameError(f"invalid teacher package combo: {stage}/{kind}")


def _validate_teacher_bulk_combo(stage: str, kind: str) -> None:
    allowed = {
        (STAGE2, "review-assignments"),
        (STAGE3, "review-feedbacks"),
        (STAGE4, KIND_OFFICIAL_EVAL),
        (STAGE4, KIND_COURSE_STATS),
    }
    if (stage, kind) not in allowed:
        raise PackageNameError(f"invalid teacher bulk package combo: {stage}/{kind}")
