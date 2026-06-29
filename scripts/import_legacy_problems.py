#!/usr/bin/env python3
"""Import legacy registered problems into the local student app workspace."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from codesetarena.legacy_import import (
    HARD_MARKER,
    find_legacy_problem_dirs,
    import_legacy_problem_dirs,
)


def default_paths() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[1]
    course_root = repo_root.parent.parent
    return (
        course_root / "code/BugHunter/.bughunter/bughunter.db",
        repo_root / ".codesetarena-student",
    )


def load_registered_problem_dirs(
    db_path: Path,
    *,
    hard_only: bool = False,
) -> tuple[list[Path], dict[str, str], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    status_by_id: dict[str, str] = {}
    missing: list[dict[str, str]] = []
    with sqlite3.connect(db_path) as conn:
        for problem_id, title, status, path in conn.execute(
            "select problem_id,title,status,path from problems order by problem_id"
        ):
            if hard_only and HARD_MARKER not in str(title):
                continue
            problem_dir = Path(str(path))
            if not (problem_dir / "problem.json").exists():
                missing.append({"problem_id": str(problem_id), "path": str(problem_dir)})
                continue
            rows.append(
                {
                    "problem_id": str(problem_id),
                    "status": str(status),
                    "path": str(problem_dir),
                }
            )
            status_by_id[str(problem_id)] = str(status)
    return [Path(row["path"]) for row in rows], status_by_id, missing


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": dict(Counter(str(item.get("status", "unknown")) for item in results)),
        "validation_status": dict(
            Counter(str(item.get("validation_status", "missing")) for item in results)
        ),
        "legacy_status": dict(
            Counter(str(item.get("legacy_status", "missing")) for item in results)
        ),
    }


def main() -> None:
    default_db, default_student_dir = default_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=default_db)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--student-dir", type=Path, default=default_student_dir)
    parser.add_argument("--hard-only", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args()

    if args.source:
        problem_dirs = find_legacy_problem_dirs(args.source, hard_only=args.hard_only)
        legacy_status_by_id: dict[str, str] = {}
        source = {"type": "directory", "path": str(args.source)}
        missing: list[dict[str, str]] = []
    else:
        problem_dirs, legacy_status_by_id, missing = load_registered_problem_dirs(
            args.db,
            hard_only=args.hard_only,
        )
        source = {"type": "sqlite", "path": str(args.db)}

    results = import_legacy_problem_dirs(
        problem_dirs,
        args.student_dir,
        replace=args.replace,
        validate=not args.no_validate,
        legacy_status_by_id=legacy_status_by_id,
    )
    payload = {
        "source": source,
        "student_dir": str(args.student_dir),
        "hard_only": args.hard_only,
        "total": len(results),
        "summary": summarize(results),
        "missing": missing,
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
