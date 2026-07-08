"""Small JSON state store used by the local v7 apps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import DEFAULT_ALLOWED_STUDENT_VERSION_TAGS, DEFAULT_RANDOM_SEED


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def student_state_path(root: Path) -> Path:
    return root / "student-state.json"


def teacher_state_path(root: Path) -> Path:
    return root / "teacher-state.json"


def default_student_state() -> dict[str, Any]:
    return {
        "student": {"student_number": "", "name": "", "class_id": ""},
        "settings": {
            "configured": False,
            "base_url": "",
            "api_key_set": False,
            "api_key_source": "未设置",
            "models": [],
        },
        "problems": [],
        "assignment": None,
        "reviews": {},
        "feedback": None,
        "revision_responses": {},
        "downloads": [],
    }


def default_teacher_state() -> dict[str, Any]:
    return {
        "settings": {
            "configured": False,
            "course_name": "CodeSetArena v7",
            "base_url": "",
            "api_key_set": False,
            "api_key_source": "未设置",
            "models": [],
            "random_seed": DEFAULT_RANDOM_SEED,
            "allowed_student_versions": DEFAULT_ALLOWED_STUDENT_VERSION_TAGS,
        },
        "students": {},
        "stage1_package_status": {},
        "submissions": {},
        "assignments": {},
        "stage2_assignment_manifest": {},
        "stage3_feedback_manifest": {},
        "reviews": {},
        "feedback": {},
        "revisions": {},
        "eval_runs": [],
        "eval_display_models": [],
        "eval_run_selections": {},
        "eval_manual_scores": {},
        "eval_jobs": {},
        "downloads": [],
        "audit": [],
    }


def load_student_state(root: Path) -> dict[str, Any]:
    return read_json(student_state_path(root), default_student_state())


def save_student_state(root: Path, state: dict[str, Any]) -> None:
    write_json(student_state_path(root), state)


def load_teacher_state(root: Path) -> dict[str, Any]:
    return _merge_missing_defaults(default_teacher_state(), read_json(teacher_state_path(root), {}))


def save_teacher_state(root: Path, state: dict[str, Any]) -> None:
    write_json(teacher_state_path(root), state)


def _merge_missing_defaults(default: dict[str, Any], loaded: Any) -> dict[str, Any]:
    if not isinstance(loaded, dict):
        return default
    merged = dict(loaded)
    for key, default_value in default.items():
        if key not in merged:
            merged[key] = default_value
        elif isinstance(default_value, dict) and isinstance(merged[key], dict):
            merged[key] = _merge_missing_defaults(default_value, merged[key])
    return merged


def append_audit(state: dict[str, Any], event: str, detail: str) -> None:
    state.setdefault("audit", []).append({"event": event, "detail": detail})
