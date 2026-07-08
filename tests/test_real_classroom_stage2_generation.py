import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from codesetarena.constants import (
    AI_REVIEWER_STUDENT_NUMBER,
    PROBLEMS_PER_STUDENT,
    STAGE2,
)
from codesetarena.package_names import teacher_package_name
from codesetarena.packages import read_package
from codesetarena.paths import ensure_teacher_tree
from codesetarena.storage import default_teacher_state
from codesetarena.student_app import create_student_app
from codesetarena.teacher_assignments import build_review_assignment_packages
from codesetarena.teacher_stage1 import import_stage1_archive, load_student_roster_xlsx


COURSE_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MOCK_ROOT = COURSE_ROOT / "v7/mock"
REAL_DATA_ROOT = Path(os.environ.get("CODESETARENA_REAL_DATA_ROOT", DEFAULT_MOCK_ROOT))
ROSTER_PATH = REAL_DATA_ROOT / "学生名单.xlsx"
STAGE1_DIR = REAL_DATA_ROOT / "真实课堂数据/收集学生提交的Stage 1题目包"
REQUIRE_REAL_DATA = os.environ.get("CODESETARENA_REQUIRE_REAL_DATA") == "1"
EXPECTED_FAILURES = {
    "20241034079-student-stage1-problems.tar.gz": "学号",
    "20241034738-student-stage1-problems.tar.gz": "学号",
    "20241034799-student-stage1-problems.tar.gz": "hash",
    "20241034651-student-stage1-problems.tar.gz": "reasoning",
}


def test_real_classroom_stage1_packages_generate_importable_stage2_assignments(tmp_path):
    _require_real_data()
    teacher_root = ensure_teacher_tree(tmp_path / "teacher")
    state = default_teacher_state()
    state["settings"]["random_seed"] = 42
    state["settings"]["allowed_student_versions"] = [
        "v7.1.10",
        "v7.1.9",
        "v7.1.8",
        "v7.1.7",
        "v7.1.3",
    ]
    state["students"] = load_student_roster_xlsx(ROSTER_PATH)

    failures: dict[str, str] = {}
    for archive in sorted(STAGE1_DIR.glob("*.tar.gz")):
        try:
            import_stage1_archive(teacher_root, state, archive)
        except Exception as exc:  # noqa: BLE001 - test records exact import failures.
            failures[archive.name] = str(exc)

    assert set(failures) == set(EXPECTED_FAILURES)
    for archive_name, expected_message in EXPECTED_FAILURES.items():
        assert expected_message in failures[archive_name]
    assert {"20241034239", "20241034397", "20241034527", "20243131169"}.issubset(
        state["submissions"]
    )

    bundle, package_paths, manifest = build_review_assignment_packages(
        teacher_root, state, reviews_per_problem=4
    )

    legal_student_count = len(state["submissions"])
    problem_count = legal_student_count * PROBLEMS_PER_STUDENT
    assert bundle.exists()
    assert len(package_paths) == legal_student_count + 1
    assert len(manifest["anonymous_problem_map"]) == problem_count
    assert manifest["reviews_per_problem"] == 4
    assert manifest["ai_reviews_per_problem"] == 1
    assert manifest["human_reviews_per_problem"] == 3
    assert {item["real_user_id"] for item in manifest["anonymous_user_map"] if item["role"] == "human"} <= set(
        state["students"]
    )

    by_problem: dict[str, list[dict]] = {}
    for item in manifest["assignments"]:
        by_problem.setdefault(item["anonymous_problem_id"], []).append(item)
        if item["review_origin"] == "human":
            assert item["reviewer_student_number"] != item["author_student_number"]
    assert len(by_problem) == problem_count
    assert all(len(items) == 4 for items in by_problem.values())
    assert all(
        sum(item["reviewer_student_number"] == AI_REVIEWER_STUDENT_NUMBER for item in items) == 1
        for items in by_problem.values()
    )
    assert all(
        sum(item["review_origin"] == "human" for item in items) == 3
        for items in by_problem.values()
    )

    ai_package = teacher_root / "stage2-review-assignment/review-packages" / teacher_package_name(
        AI_REVIEWER_STUDENT_NUMBER, STAGE2, "review-assignment"
    )
    _, ai_payload = read_package(ai_package)
    assert len(ai_payload["assigned_problems"]) == problem_count

    for package_path in package_paths:
        student_root = tmp_path / "student-imports" / package_path.name.removesuffix(".tar.gz")
        student = TestClient(create_student_app(student_root))
        with package_path.open("rb") as handle:
            response = student.post(
                "/stage2/import",
                files={"file": (package_path.name, handle, "application/gzip")},
                follow_redirects=False,
            )
        assert response.status_code == 303
        assert "error=" not in response.headers["location"]


def _require_real_data() -> None:
    missing = [path for path in [ROSTER_PATH, STAGE1_DIR] if not path.exists()]
    if not missing:
        return
    message = "缺少真实课堂测试数据：" + ", ".join(str(path) for path in missing)
    if REQUIRE_REAL_DATA:
        pytest.fail(message)
    pytest.skip(message)
