#!/usr/bin/env python3
"""Import legacy ``【难】`` problems into the local student app workspace."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from codesetarena.legacy_import import import_legacy_hard_problems


def default_paths() -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[1]
    course_root = repo_root.parent.parent
    return (
        course_root / "code/BugHunter/.bughunter/workspace/problems",
        repo_root / ".codesetarena-student",
    )


def main() -> None:
    default_source, default_student_dir = default_paths()
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=default_source)
    parser.add_argument("--student-dir", type=Path, default=default_student_dir)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--no-validate", action="store_true")
    args = parser.parse_args()

    results = import_legacy_hard_problems(
        args.source,
        args.student_dir,
        replace=args.replace,
        validate=not args.no_validate,
    )
    payload = {
        "source": str(args.source),
        "student_dir": str(args.student_dir),
        "results": results,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
