import json
import re

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from codesetarena.cli import app
from codesetarena.constants import (
    AI_REVIEWER_STUDENT_NUMBER,
    PROBLEMS_PER_STUDENT,
    RUN_ORIGIN_TA_OFFICIAL_EVAL,
)
from codesetarena.demo_data import seed_demo_course
from codesetarena.storage import load_teacher_state, save_teacher_state
from codesetarena.teacher_app import create_teacher_app
from codesetarena.teacher_eval import (
    add_eval_display_model,
    clear_eval_run_selection,
    eval_executed_models,
    eval_problem_rows,
    eval_result_for_model,
    remove_eval_display_model,
    run_official_eval_for_model,
    set_eval_run_selection,
)


def test_demo_seed_course_builds_full_chain(tmp_path):
    root = tmp_path / "teacher"

    summary = seed_demo_course(root, force=True)

    state = load_teacher_state(root)
    assert summary == {
        "students": 10,
        "problems": 50,
        "reviews": 200,
        "revision_responses": 200,
    }
    assert len(state["submissions"]) == 10
    assert sum(len(row["problems"]) for row in state["submissions"].values()) == 50
    assert AI_REVIEWER_STUDENT_NUMBER in state["reviews"]
    assert len(state["reviews"][AI_REVIEWER_STUDENT_NUMBER]["reviews"]) == 50
    for student_number, row in state["submissions"].items():
        assert len(row["problems"]) == PROBLEMS_PER_STUDENT
        assert len(state["feedback"][student_number]["reviews"]) == PROBLEMS_PER_STUDENT * 4
        assert len(state["revisions"][student_number]["responses"]) == PROBLEMS_PER_STUDENT * 4
    assert set(eval_executed_models(state)) >= set(state["settings"]["models"][:2])


def test_eval_model_display_is_limited_to_executed_models_and_does_not_delete_runs(tmp_path):
    root = tmp_path / "teacher"
    seed_demo_course(root, force=True)
    state = load_teacher_state(root)
    run_count = len(state["eval_runs"])
    model = state["settings"]["models"][0]
    state["eval_display_models"] = []

    add_eval_display_model(state, model)
    remove_eval_display_model(state, model)

    assert state["eval_display_models"] == []
    assert len(state["eval_runs"]) == run_count
    try:
        add_eval_display_model(state, "not-yet-executed")
    except ValueError as exc:
        assert "尚未执行" in str(exc)
    else:
        raise AssertionError("adding a model without official eval history should fail")


def test_official_eval_cache_first_skips_existing_and_force_appends(tmp_path):
    root = tmp_path / "teacher"
    seed_demo_course(root, force=True)
    state = load_teacher_state(root)
    model = state["settings"]["models"][0]
    initial = len([run for run in state["eval_runs"] if run.get("model") == model])

    cached = run_official_eval_for_model(state, root, model, mode="cache_first")
    forced = run_official_eval_for_model(state, root, model, mode="force")

    assert cached["completed"] == 0
    assert cached["skipped"] == 50
    assert forced["completed"] == 50
    assert forced["skipped"] == 0
    assert len([run for run in state["eval_runs"] if run.get("model") == model]) == initial + 50
    assert all(run["run_origin"] == RUN_ORIGIN_TA_OFFICIAL_EVAL for run in state["eval_runs"])


def test_official_eval_real_api_error_does_not_create_legal_runs(tmp_path, monkeypatch):
    def failing_completion(*, config, model, prompt, timeout=60.0):
        raise RuntimeError("真实模型请求失败：HTTP 400 model kfcvivo50 not found")

    root = tmp_path / "teacher"
    seed_demo_course(root, force=True)
    state = load_teacher_state(root)
    state["settings"]["models"] = ["kfcvivo50"]
    existing = len(state.get("eval_runs", []))
    monkeypatch.setattr("codesetarena.teacher_eval.real_completion", failing_completion, raising=False)

    summary = run_official_eval_for_model(state, root, "kfcvivo50", mode="force")

    assert summary["completed"] == 0
    assert summary["failed"] == 50
    assert len(state.get("eval_runs", [])) == existing
    assert "kfcvivo50" not in eval_executed_models(state)


def test_eval_result_defaults_to_latest_legal_run_and_allows_manual_selection(tmp_path):
    root = tmp_path / "teacher"
    seed_demo_course(root, force=True)
    state = load_teacher_state(root)
    first_row = eval_problem_rows(state)[0]
    student_number = first_row["student_number"]
    problem_id = first_row["problem_id"]
    model = state["settings"]["models"][0]
    original = eval_result_for_model(state, student_number, problem_id, model)

    run_official_eval_for_model(state, root, model, mode="force")
    latest = eval_result_for_model(state, student_number, problem_id, model)
    set_eval_run_selection(state, student_number, problem_id, model, original["run"]["run_id"])
    selected = eval_result_for_model(state, student_number, problem_id, model)
    clear_eval_run_selection(state, student_number, problem_id, model)
    restored = eval_result_for_model(state, student_number, problem_id, model)

    assert latest["run"]["run_id"] != original["run"]["run_id"]
    assert selected["run"]["run_id"] == original["run"]["run_id"]
    assert selected["selection_source"] == "manual"
    assert restored["run"]["run_id"] == latest["run"]["run_id"]
    assert restored["selection_source"] == "latest"


def test_eval_rows_mark_missing_cells_and_merge_student_rowspans(tmp_path):
    root = tmp_path / "teacher"
    seed_demo_course(root, force=True)
    state = load_teacher_state(root)

    rows = eval_problem_rows(state)
    first_student_rows = [row for row in rows if row["student_number"] == "1001"]

    assert len(rows) == 50
    assert first_student_rows[0]["student_rowspan"] == 5
    assert all(row["student_rowspan"] == 0 for row in first_student_rows[1:])
    assert "manual_score" not in first_student_rows[0]
    assert "manual_score_missing" not in first_student_rows[0]
    assert first_student_rows[0]["quality_scores_text"].count("/") == 3
    assert first_student_rows[0]["author_rating_text"].count("/") == 3
    assert " = " in first_student_rows[0]["author_rating_text"]
    assert first_student_rows[0]["author_rating_average"] > 0


def test_eval_author_rating_text_uses_review_order_like_quality_scores():
    state = {
        "submissions": {
            "1001": {
                "student": {"student_number": "1001", "name": "学生1001"},
                "problems": [{"problem_id": "pb_order", "title": "顺序题", "run_records": []}],
            }
        },
        "feedback": {
            "1001": {
                "reviews": [
                    {"problem_id": "pb_order", "review_id": "rev_a", "review": {"quality_score": "1"}},
                    {"problem_id": "pb_order", "review_id": "rev_b", "review": {"quality_score": "2"}},
                    {"problem_id": "pb_order", "review_id": "rev_c", "review": {"quality_score": "3"}},
                    {"problem_id": "pb_order", "review_id": "rev_d", "review": {"quality_score": "4"}},
                ]
            }
        },
        "revisions": {
            "1001": {
                "responses": [
                    {"review_id": "rev_d", "rating": "2"},
                    {"review_id": "rev_b", "rating": "4"},
                    {"review_id": "rev_c", "rating": "3"},
                    {"review_id": "rev_a", "rating": "5"},
                ]
            }
        },
    }

    row = eval_problem_rows(state)[0]

    assert row["quality_scores_text"] == "1/2/3/4 = 2.5"
    assert row["author_rating_text"] == "5/4/3/2 = 3.5"


def test_teacher_eval_web_page_starts_job_and_shows_progress(tmp_path):
    root = tmp_path / "teacher"
    seed_demo_course(root, force=True)
    client = TestClient(create_teacher_app(root))

    page = client.get("/eval")
    assert page.status_code == 200
    assert "选择模型执行" in page.text
    assert "选择模型展示" in page.text
    assert 'rowspan="5"' in page.text
    assert "助教手动评分" not in page.text

    response = client.post(
        "/eval/jobs",
        data={"model": load_teacher_state(root)["settings"]["models"][0], "mode": "cache_first"},
    )
    assert response.status_code == 200
    job = response.json()
    assert job["ok"] is True
    progress = client.get(f"/eval/jobs/{job['job_id']}")
    assert progress.status_code == 200
    assert progress.json()["status"] in {"pending", "running", "completed"}


def test_teacher_eval_page_removes_manual_score_and_formats_author_ratings(tmp_path):
    root = tmp_path / "teacher"
    seed_demo_course(root, force=True)
    client = TestClient(create_teacher_app(root))

    html = client.get("/eval").text

    assert "助教手动评分" not in html
    assert "data-eval-manual-score" not in html
    assert "/eval/manual-score" not in html
    assert "作者评分均值" in html
    assert re.search(r"[1-5]/[1-5]/[1-5]/[1-5] = [1-5]\.[0-9]", html)


def test_teacher_eval_detail_displays_case_results_as_rows(tmp_path):
    root = tmp_path / "teacher"
    seed_demo_course(root, force=True)
    state = load_teacher_state(root)
    row = eval_problem_rows(state)[0]
    client = TestClient(create_teacher_app(root))

    html = client.get(f"/eval/problems/{row['student_number']}/{row['problem_id']}").text

    assert "<th>用例 ID</th>" in html
    assert "<th>集合</th>" in html
    assert "<th>结果</th>" in html
    assert "<th>期望</th>" in html
    assert "<th>实际/错误</th>" in html
    assert "样例数据" in html
    assert "测试数据" in html
    assert "run.test_results" not in html


def test_teacher_eval_detail_selects_latest_run_without_default_placeholder(tmp_path):
    root = tmp_path / "teacher"
    seed_demo_course(root, force=True)
    state = load_teacher_state(root)
    row = eval_problem_rows(state)[0]
    model = state["settings"]["models"][0]
    latest_run_id = eval_result_for_model(state, row["student_number"], row["problem_id"], model)["run"][
        "run_id"
    ]
    client = TestClient(create_teacher_app(root))

    html = client.get(f"/eval/problems/{row['student_number']}/{row['problem_id']}").text

    assert "默认最近合法记录" not in html
    assert f'<option value="{latest_run_id}" selected>' in html


def test_teacher_eval_run_controls_use_settings_models_in_one_row(tmp_path):
    root = tmp_path / "teacher"
    state = load_teacher_state(root)
    state["settings"]["models"] = ["model-alpha", "model-beta"]
    save_teacher_state(root, state)
    client = TestClient(create_teacher_app(root))

    html = client.get("/eval").text

    assert 'id="eval-job-form" class="eval-run-controls"' in html
    assert 'class="eval-inline-field"' in html
    assert '<option value="model-alpha">model-alpha</option>' in html
    assert '<option value="model-beta">model-beta</option>' in html
    assert html.index('name="model"') < html.index('name="mode"') < html.index("开始正式评测")


def test_teacher_eval_run_controls_ignore_environment_models_when_state_models_empty(tmp_path, monkeypatch):
    root = tmp_path / "teacher"
    state = load_teacher_state(root)
    state["settings"]["models"] = []
    save_teacher_state(root, state)
    monkeypatch.setenv("MODELS", "env-model-alpha|env-model-beta")
    client = TestClient(create_teacher_app(root))

    html = client.get("/eval").text

    assert '<option value="env-model-alpha">env-model-alpha</option>' not in html
    assert '<option value="env-model-beta">env-model-beta</option>' not in html


def test_teacher_demo_seed_and_eval_cli(tmp_path):
    runner = CliRunner()
    teacher_dir = tmp_path / "teacher"

    result = runner.invoke(
        app,
        ["teacher", "demo", "seed-course", "--data-dir", str(teacher_dir), "--force"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["summary"]["students"] == 10

    result = runner.invoke(
        app,
        [
            "teacher",
            "eval",
            "run",
            "--data-dir",
            str(teacher_dir),
            "--model",
            load_teacher_state(teacher_dir)["settings"]["models"][0],
            "--mode",
            "cache-first",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["summary"]["skipped"] == 50

    result = runner.invoke(
        app,
        [
            "teacher",
            "eval",
            "models",
            "add",
            "--data-dir",
            str(teacher_dir),
            "--model",
            load_teacher_state(teacher_dir)["settings"]["models"][0],
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert load_teacher_state(teacher_dir)["settings"]["models"][0] in json.loads(result.stdout)["display_models"]
