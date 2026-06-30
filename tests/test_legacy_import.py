import json
from pathlib import Path

from fastapi.testclient import TestClient

from codesetarena.legacy_import import (
    find_legacy_hard_problem_dirs,
    find_legacy_problem_dirs,
    import_legacy_hard_problems,
    import_legacy_problems,
    read_legacy_problem,
)
from codesetarena.storage import default_student_state, load_student_state, save_student_state
from codesetarena.student_app import (
    _problem_signature_hash,
    _test_edit_rows,
    _validate_problem,
    _validation_view,
    create_student_app,
)


def test_import_legacy_hard_problems_validates_and_skips_duplicates(tmp_path):
    source_root = tmp_path / "legacy"
    _write_legacy_problem(source_root / "hard_one", title="【难】旧难题", problem_id="pb_old_hard")
    _write_legacy_problem(source_root / "normal_one", title="普通题", problem_id="pb_old_normal")

    assert [path.name for path in find_legacy_hard_problem_dirs(source_root)] == ["hard_one"]

    student_root = tmp_path / "student"
    results = import_legacy_hard_problems(source_root, student_root)

    assert results == [
        {
            "problem_id": "pb_old_hard",
            "title": "【难】旧难题",
            "status": "imported",
            "validation_status": "passed",
        }
    ]
    state = load_student_state(student_root)
    assert len(state["problems"]) == 1
    problem = state["problems"][0]
    assert problem["problem_id"] == "pb_old_hard"
    assert problem["run_records"] == []
    assert not problem["reference_solution"].endswith("\n")
    assert problem["validation"]["status"] == "passed"
    assert problem["validation"]["content_hash"] == _problem_signature_hash(problem)
    assert len(problem["validation"]["test_results"]) == 7

    duplicate_results = import_legacy_hard_problems(source_root, student_root)
    assert duplicate_results[0]["status"] == "skipped"
    assert len(load_student_state(student_root)["problems"]) == 1


def test_import_legacy_problems_can_import_all_problem_dirs(tmp_path):
    source_root = tmp_path / "legacy"
    _write_legacy_problem(source_root / "hard_one", title="【难】旧难题", problem_id="pb_old_hard")
    _write_legacy_problem(source_root / "normal_one", title="普通题", problem_id="pb_old_normal")

    assert [path.name for path in find_legacy_problem_dirs(source_root)] == [
        "hard_one",
        "normal_one",
    ]

    student_root = tmp_path / "student"
    results = import_legacy_problems(source_root, student_root)

    assert [item["problem_id"] for item in results] == ["pb_old_hard", "pb_old_normal"]
    assert {item["validation_status"] for item in results} == {"passed"}
    state = load_student_state(student_root)
    assert [problem["problem_id"] for problem in state["problems"]] == [
        "pb_old_hard",
        "pb_old_normal",
    ]
    assert "旧判题类型：exact" in state["problems"][0]["notes"]


def test_legacy_problem_with_pre_normalized_validation_does_not_self_invalidate_on_run(tmp_path):
    source_root = tmp_path / "legacy"
    problem_dir = source_root / "hard_one"
    _write_legacy_problem(problem_dir, title="【难】旧难题", problem_id="pb_old_hard")
    problem = read_legacy_problem(problem_dir)
    assert problem["reference_solution"].endswith("\n")
    problem["validation"] = _validate_problem(problem)

    student_root = tmp_path / "student"
    state = default_student_state()
    state["student"] = {"student_number": "2026000001", "name": "Alice", "class_id": "A"}
    state["problems"] = [problem]
    save_student_state(student_root, state)

    client = TestClient(create_student_app(student_root))
    client.post(
        "/settings",
        data={
            "base_url": "https://api.example.test",
            "api_key": "sk-student-secret",
            "models": ["deepseek-v4-flash"],
        },
    )
    detail_path = "/stage1/problems/pb_old_hard"
    detail = client.get(detail_path)
    assert detail.status_code == 200
    assert 'id="validation-status" data-valid="true"' in detail.text
    assert '<span class="status-pill ok">校验通过</span>' in detail.text

    repaired = load_student_state(student_root)["problems"][0]
    assert not repaired["reference_solution"].endswith("\n")
    assert repaired["validation"]["content_hash"] == _problem_signature_hash(repaired)
    assert _validation_view(repaired)["ok"] is True

    response = client.post(detail_path + "/run", data=_problem_form_data(repaired), follow_redirects=False)
    assert response.status_code == 303
    detail = client.get(response.headers["location"])
    validation_panel = _panel_text(detail.text, "validation-panel", "参考答案执行结果")
    assert '<span class="status-pill ok">校验通过</span>' in validation_panel
    assert "已失效" not in validation_panel
    state = load_student_state(student_root)
    assert _validation_view(state["problems"][0])["ok"] is True
    assert len(state["problems"][0]["run_records"]) == 1


def test_legacy_problem_marked_stale_by_old_form_submit_is_repaired_on_detail_load(tmp_path):
    source_root = tmp_path / "legacy"
    problem_dir = source_root / "hard_one"
    _write_legacy_problem(problem_dir, title="【难】旧难题", problem_id="pb_old_hard")
    problem = read_legacy_problem(problem_dir)
    problem["validation"] = _validate_problem(problem)
    problem["reference_solution"] = problem["reference_solution"].rstrip("\n").replace("\n", "\r\n")
    problem["validation"]["status"] = "stale"
    problem["validation"]["message"] = "题目已变更，校验已失效，需要重新校验"

    student_root = tmp_path / "student"
    state = default_student_state()
    state["student"] = {"student_number": "2026000001", "name": "Alice", "class_id": "A"}
    state["problems"] = [problem]
    save_student_state(student_root, state)

    client = TestClient(create_student_app(student_root))
    detail = client.get("/stage1/problems/pb_old_hard")
    validation_panel = _panel_text(detail.text, "validation-panel", "参考答案执行结果")
    assert '<span class="status-pill ok">校验通过</span>' in validation_panel
    assert "已失效" not in validation_panel

    repaired = load_student_state(student_root)["problems"][0]
    assert "\r\n" not in repaired["reference_solution"]
    assert repaired["validation"]["status"] == "passed"
    assert repaired["validation"]["content_hash"] == _problem_signature_hash(repaired)
    assert _validation_view(repaired)["ok"] is True


def _write_legacy_problem(problem_dir: Path, *, title: str, problem_id: str) -> None:
    problem_dir.mkdir(parents=True)
    (problem_dir / "problem.json").write_text(
        json.dumps(
            {
                "schema_version": "problem.v1",
                "problem_id": problem_id,
                "title": title,
                "function_name": "solve",
                "judge_type": "exact",
                "failure_hypothesis": "模型容易漏边界。",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (problem_dir / "statement.md").write_text("返回 x。", encoding="utf-8")
    (problem_dir / "signature.py").write_text("def solve(x: int) -> int:\n", encoding="utf-8")
    (problem_dir / "reference_solution.py").write_text(
        "def solve(x: int) -> int:\n    return x\n",
        encoding="utf-8",
    )
    (problem_dir / "public_tests.jsonl").write_text(
        '{"input":{"kwargs":{"x":1}},"expected":1}\n'
        '{"input":{"kwargs":{"x":2}},"expected":2}\n',
        encoding="utf-8",
    )
    (problem_dir / "author_tests.jsonl").write_text(
        '{"input":{"kwargs":{"x":0}},"expected":0}\n'
        '{"input":{"kwargs":{"x":3}},"expected":3}\n'
        '{"input":{"kwargs":{"x":4}},"expected":4}\n'
        '{"input":{"kwargs":{"x":5}},"expected":5}\n'
        '{"input":{"kwargs":{"x":6}},"expected":6}\n',
        encoding="utf-8",
    )


def _problem_form_data(problem: dict) -> dict[str, str]:
    data = {
        "statement": problem["statement"],
        "signature": problem["signature"],
        "reference_solution": problem["reference_solution"],
        "notes": problem.get("notes", ""),
        "model": "deepseek-v4-flash",
    }
    for prefix, rows in [
        ("public", _test_edit_rows(problem.get("public_tests", []), 2)),
        ("author", _test_edit_rows(problem.get("author_tests", []), 5)),
    ]:
        for row in rows:
            data[f"{prefix}_kwargs_{row['index']}"] = str(row["kwargs_json"])
            data[f"{prefix}_expected_{row['index']}"] = str(row["expected_json"])
    return data


def _panel_text(html: str, start_id: str, end_marker: str) -> str:
    start = html.find(f'id="{start_id}"')
    end = html.find(end_marker, start)
    return html[start:end]
