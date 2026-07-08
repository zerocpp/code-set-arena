"""Directory layout helpers for local student and teacher deployments."""

from __future__ import annotations

import os
from pathlib import Path

from .constants import (
    DEFAULT_STUDENT_DATA_DIR,
    DEFAULT_TEACHER_DATA_DIR,
    STUDENT_DATA_ENV,
    TEACHER_DATA_ENV,
)


def default_student_root() -> Path:
    return Path(os.environ.get(STUDENT_DATA_ENV, DEFAULT_STUDENT_DATA_DIR)).expanduser()


def default_teacher_root() -> Path:
    return Path(os.environ.get(TEACHER_DATA_ENV, DEFAULT_TEACHER_DATA_DIR)).expanduser()


STUDENT_DIRS = [
    "settings",
    "stage1-original/workspace/problems",
    "stage1-original/uploads",
    "stage1-original/exports",
    "stage2-review/imports",
    "stage2-review/workspace/reviews",
    "stage2-review/exports",
    "stage3-revision/imports",
    "stage3-revision/workspace/problems",
    "stage3-revision/workspace/responses",
    "stage3-revision/exports",
    "downloads",
]

TEACHER_DIRS = [
    "settings",
    "stage1-submissions/uploads",
    "stage1-submissions/imports",
    "stage1-submissions/validation-reports",
    "stage1-submissions/exports",
    "stage2-review-assignment/anonymous-corpus",
    "stage2-review-assignment/assignments",
    "stage2-review-assignment/review-packages",
    "stage2-review-assignment/imported-reviews",
    "stage3-revisions/uploads",
    "stage3-revisions/imports",
    "stage3-revisions/author-responses",
    "stage3-revisions/feedback-packages",
    "ta-eval/runs",
    "stats/exports",
    "audit",
    "downloads",
]


def ensure_student_tree(root: Path) -> Path:
    return _ensure_tree(root, STUDENT_DIRS)


def ensure_teacher_tree(root: Path) -> Path:
    return _ensure_tree(root, TEACHER_DIRS)


def _ensure_tree(root: Path, directories: list[str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name in directories:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root
