"""Import legacy problems into a CodeSetArena student workspace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .paths import ensure_student_tree
from .run_engine import RunEngineError
from .storage import load_student_state, save_student_state
from .student_app import _normalize_problem_for_form, _validate_problem, _validation_error

HARD_MARKER = "【难】"


def import_legacy_hard_problems(
    source_root: Path,
    student_root: Path,
    *,
    replace: bool = False,
    validate: bool = True,
) -> list[dict[str, Any]]:
    """Import legacy problem directories whose title contains ``【难】``."""

    return import_legacy_problems(
        source_root,
        student_root,
        replace=replace,
        validate=validate,
        hard_only=True,
    )


def import_legacy_problems(
    source_root: Path,
    student_root: Path,
    *,
    replace: bool = False,
    validate: bool = True,
    hard_only: bool = False,
) -> list[dict[str, Any]]:
    """Import legacy problem directories from one source directory."""

    return import_legacy_problem_dirs(
        find_legacy_problem_dirs(source_root, hard_only=hard_only),
        student_root,
        replace=replace,
        validate=validate,
    )


def import_legacy_problem_dirs(
    problem_dirs: list[Path],
    student_root: Path,
    *,
    replace: bool = False,
    validate: bool = True,
    legacy_status_by_id: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Import explicit legacy problem directories."""

    student_root = ensure_student_tree(student_root)
    state = load_student_state(student_root)
    problems = state.setdefault("problems", [])
    existing_by_id = {
        str(problem.get("problem_id")): index for index, problem in enumerate(problems)
    }

    results: list[dict[str, Any]] = []
    for problem_dir in sorted(path.resolve() for path in problem_dirs):
        problem = read_legacy_problem(problem_dir)
        _normalize_problem_for_form(problem)
        problem_id = problem["problem_id"]
        legacy_status = (legacy_status_by_id or {}).get(problem_id)
        if legacy_status:
            problem["legacy_status"] = legacy_status
            problem["notes"] = f"{problem['notes']}\n旧数据库状态：{legacy_status}"
        if problem_id in existing_by_id and not replace:
            results.append(
                {
                    "problem_id": problem_id,
                    "title": problem["title"],
                    "status": "skipped",
                    "reason": "already_exists",
                    **({"legacy_status": legacy_status} if legacy_status else {}),
                }
            )
            continue

        if validate:
            try:
                problem["validation"] = _validate_problem(problem)
            except RunEngineError as exc:
                problem["validation"] = _validation_error(problem, str(exc), exc.error_type)

        if problem_id in existing_by_id:
            problems[existing_by_id[problem_id]] = problem
            status = "replaced"
        else:
            existing_by_id[problem_id] = len(problems)
            problems.append(problem)
            status = "imported"

        results.append(
            {
                "problem_id": problem_id,
                "title": problem["title"],
                "status": status,
                "validation_status": (problem.get("validation") or {}).get("status", "missing"),
                **({"legacy_status": legacy_status} if legacy_status else {}),
            }
        )

    save_student_state(student_root, state)
    return results


def find_legacy_hard_problem_dirs(source_root: Path) -> list[Path]:
    """Return sorted legacy problem dirs whose metadata title contains ``【难】``."""

    return find_legacy_problem_dirs(source_root, hard_only=True)


def find_legacy_problem_dirs(source_root: Path, *, hard_only: bool = False) -> list[Path]:
    """Return sorted legacy problem dirs, optionally limited to hard problems."""

    source_root = source_root.resolve()
    dirs: list[Path] = []
    if not source_root.exists():
        return dirs
    for metadata_path in sorted(source_root.glob("*/problem.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        title = str(metadata.get("title", ""))
        if not hard_only or HARD_MARKER in title:
            dirs.append(metadata_path.parent)
    return dirs


def read_legacy_problem(problem_dir: Path) -> dict[str, Any]:
    metadata = json.loads((problem_dir / "problem.json").read_text(encoding="utf-8"))
    problem_id = str(metadata.get("problem_id") or problem_dir.name)
    title = str(metadata.get("title") or problem_id)
    statement = _read_required(problem_dir / "statement.md")
    signature = _read_required(problem_dir / "signature.py").strip()
    reference_solution = _read_required(problem_dir / "reference_solution.py").rstrip() + "\n"
    public_tests = _read_jsonl(problem_dir / "public_tests.jsonl")
    author_tests = _read_jsonl(problem_dir / "author_tests.jsonl")
    run_analysis = _read_optional(problem_dir / "run_analysis.md")
    legacy_judge_type = str(metadata.get("judge_type", "exact") or "exact")

    notes_parts = [
        f"迁移自旧项目目录：{problem_dir}",
        f"旧题标题：{title}",
        f"旧判题类型：{legacy_judge_type}",
    ]
    failure_hypothesis = str(metadata.get("failure_hypothesis", "") or "").strip()
    if failure_hypothesis:
        notes_parts.append(f"旧 failure hypothesis：{failure_hypothesis}")

    return {
        "problem_id": problem_id,
        "title": title,
        "statement": statement,
        "signature": signature,
        "reference_solution": reference_solution,
        "public_tests": public_tests,
        "author_tests": author_tests,
        "failure_hypothesis": failure_hypothesis,
        "legacy_judge_type": legacy_judge_type,
        "notes": "\n".join(notes_parts),
        "run_analysis": run_analysis,
        "run_records": [],
        "validation": None,
    }


def _read_required(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"legacy problem missing {path.name}: {path}")
    return path.read_text(encoding="utf-8").strip()


def _read_optional(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def _read_jsonl(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"legacy problem missing {path.name}: {path}")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
