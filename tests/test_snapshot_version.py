from fastapi.testclient import TestClient

from codesetarena.storage import load_student_state
from codesetarena.student_app import _run_record_matches_current_prompt, _validation_view, create_student_app
from codesetarena.versioning import snapshot_version


def test_snapshot_version_uses_major_minor_only():
    assert snapshot_version("1.2.3") == "1.2"
    assert snapshot_version("1.2.4") == "1.2"
    assert snapshot_version("1.3.0") == "1.3"
    assert snapshot_version("2.0.0") == "2.0"


def test_student_validation_and_run_records_require_snapshot_version_match(tmp_path):
    client = TestClient(create_student_app(tmp_path))
    client.post(
        "/settings",
        data={
            "base_url": "https://api.example.test",
            "api_key": "sk-student-secret",
            "models": ["deepseek-v4-flash"],
        },
    )
    client.post("/student-info", data={"student_number": "2026000001", "name": "Alice", "class_id": "A"})
    response = client.post("/stage1/problems", follow_redirects=False)
    detail_path = response.headers["location"].split("?", 1)[0]
    problem_data = {
        "signature": "def solve(x: int) -> int:",
        "statement": "Return x.",
        "reference_solution": "def solve(x: int) -> int:\n    return x\n",
        "public_kwargs_0": '{"x":1}',
        "public_expected_0": "1",
        "public_kwargs_1": '{"x":2}',
        "public_expected_1": "2",
        "author_kwargs_0": '{"x":0}',
        "author_expected_0": "0",
        "author_kwargs_1": '{"x":3}',
        "author_expected_1": "3",
        "author_kwargs_2": '{"x":4}',
        "author_expected_2": "4",
        "author_kwargs_3": '{"x":5}',
        "author_expected_3": "5",
        "author_kwargs_4": '{"x":6}',
        "author_expected_4": "6",
        "notes": "",
        "model": "deepseek-v4-flash",
    }

    assert client.post(f"{detail_path}/validate", data=problem_data, follow_redirects=False).status_code == 303
    assert client.post(f"{detail_path}/run", data=problem_data, follow_redirects=False).status_code == 303

    problem = load_student_state(tmp_path)["problems"][0]
    assert problem["validation"]["snapshot_version"] == snapshot_version()
    assert problem["run_records"][0]["snapshot_version"] == snapshot_version()
    assert _validation_view(problem)["ok"] is True
    assert _run_record_matches_current_prompt(problem, problem["run_records"][0])[0] is True

    problem["validation"]["snapshot_version"] = snapshot_version("0.8.0")
    view = _validation_view(problem)
    assert view["ok"] is False
    assert view["snapshot_mismatch"] is True
    assert "系统版本" in view["message"]

    problem["validation"]["snapshot_version"] = snapshot_version()
    problem["run_records"][0]["snapshot_version"] = snapshot_version("0.8.0")
    matches, reason = _run_record_matches_current_prompt(problem, problem["run_records"][0])
    assert matches is False
    assert "系统版本" in reason
