import json
from pathlib import Path

from typer.testing import CliRunner

from codesetarena.cli import app
from codesetarena.constants import KIND_REVISION, PROBLEMS_PER_STUDENT, STAGE3
from codesetarena.package_names import student_package_name, teacher_package_name
from codesetarena.packages import read_package
from codesetarena.storage import load_student_state


def test_cli_uses_code_set_arena_commands(tmp_path):
    runner = CliRunner()
    result = runner.invoke(app, ["student", "init", "--data-dir", str(tmp_path / "student")])
    assert result.exit_code == 0
    assert "initialized student workspace" in result.stdout

    result = runner.invoke(app, ["teacher", "init", "--data-dir", str(tmp_path / "teacher")])
    assert result.exit_code == 0
    assert "initialized teacher workspace" in result.stdout


def test_cli_student_settings_reads_env_without_persisting_secret(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-cli-secret")
    monkeypatch.setenv("BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("MODELS", "deepseek-v4-flash|deepseek-v4-pro")
    runner = CliRunner()
    data_dir = tmp_path / "student"
    result = runner.invoke(
        app,
        [
            "student",
            "settings",
            "set",
            "--data-dir",
            str(data_dir),
            "--student-number",
            "2026000001",
            "--name",
            "Alice",
        ],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["settings"]["api_key_set"] is True
    state = load_student_state(data_dir)
    assert "api_key" not in state["settings"]
    assert "sk-cli-secret" not in (data_dir / "student-state.json").read_text(encoding="utf-8")


def test_cli_student_stage1_full_export(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-cli-secret")
    runner = CliRunner()
    data_dir = tmp_path / "student"
    result = runner.invoke(
        app,
        [
            "student",
            "settings",
            "set",
            "--data-dir",
            str(data_dir),
            "--student-number",
            "2026000001",
            "--name",
            "Alice",
        ],
    )
    assert result.exit_code == 0, result.stdout
    problem_ids = []
    for _ in range(PROBLEMS_PER_STUDENT):
        result = runner.invoke(app, ["student", "stage1", "create", "--data-dir", str(data_dir), "--sample", "identity"])
        assert result.exit_code == 0, result.stdout
        problem_id = json.loads(result.stdout)["problem_id"]
        problem_ids.append(problem_id)
        assert runner.invoke(app, ["student", "stage1", "validate", "--data-dir", str(data_dir), "--problem-id", problem_id]).exit_code == 0
        result = runner.invoke(app, ["student", "stage1", "run", "--data-dir", str(data_dir), "--problem-id", problem_id])
        assert result.exit_code == 0, result.stdout
        run_id = json.loads(result.stdout)["run_id"]
        assert runner.invoke(
            app,
            [
                "student",
                "stage1",
                "select-runs",
                "--data-dir",
                str(data_dir),
                "--problem-id",
                problem_id,
                "--run-id",
                run_id,
            ],
        ).exit_code == 0
    args = ["student", "stage1", "select-problems", "--data-dir", str(data_dir)]
    for problem_id in problem_ids:
        args.extend(["--problem-id", problem_id])
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["selected"] == PROBLEMS_PER_STUDENT
    result = runner.invoke(app, ["student", "stage1", "package", "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.stdout
    archive = Path(json.loads(result.stdout)["archive"])
    manifest, payload = read_package(archive)
    assert manifest["student_number"] == "2026000001"
    assert len(payload["problems"]) == PROBLEMS_PER_STUDENT
    payload_json = json.dumps(payload, ensure_ascii=False)
    assert "sk-cli-secret" not in payload_json
    assert "API_KEY" not in payload_json


def test_cli_student_stage1_list_delete_and_stale_run_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-cli-secret")
    runner = CliRunner()
    data_dir = tmp_path / "student"
    result = runner.invoke(
        app,
        [
            "student",
            "settings",
            "set",
            "--data-dir",
            str(data_dir),
            "--student-number",
            "2026000001",
            "--name",
            "Alice",
        ],
    )
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["student", "stage1", "create", "--data-dir", str(data_dir), "--sample", "identity"])
    assert result.exit_code == 0, result.stdout
    problem_id = json.loads(result.stdout)["problem_id"]
    result = runner.invoke(app, ["student", "stage1", "list", "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.stdout
    listed_payload = json.loads(result.stdout)
    assert listed_payload["count"] == 1
    assert listed_payload["problems"][0]["problem_id"] == problem_id
    assert listed_payload["problems"][0]["selected_valid_runs"] == 0
    assert listed_payload["problems"][0]["package_status"] == "不可打包"
    result = runner.invoke(app, ["student", "stage1", "validate", "--data-dir", str(data_dir), "--problem-id", problem_id])
    assert result.exit_code == 0, result.stdout

    problem_file = tmp_path / "changed.json"
    problem_file.write_text(
        json.dumps(
            {
                "statement": "Return x plus zero.",
                "signature": "def solve(x: int) -> int:",
                "reference_solution": "def solve(x: int) -> int:\n    return x\n",
            }
        ),
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "student",
            "stage1",
            "update",
            "--data-dir",
            str(data_dir),
            "--problem-id",
            problem_id,
            "--problem-file",
            str(problem_file),
        ],
    )
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["student", "stage1", "run", "--data-dir", str(data_dir), "--problem-id", problem_id])
    assert result.exit_code != 0

    result = runner.invoke(app, ["student", "stage1", "delete", "--data-dir", str(data_dir), "--problem-id", problem_id])
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["student", "stage1", "list", "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["count"] == 0


def test_cli_student_three_stage_import_export_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-cli-secret")
    runner = CliRunner()
    student_a_dir = tmp_path / "student-a"
    student_b_dir = tmp_path / "student-b"
    teacher_dir = tmp_path / "teacher"
    stage1_a = _make_cli_stage1_package(runner, student_a_dir, "2026000001", "Alice")
    stage1_b = _make_cli_stage1_package(runner, student_b_dir, "2026000002", "Bob")

    for archive in [stage1_a, stage1_b]:
        result = runner.invoke(
            app,
            ["teacher", "stage1", "upload", "--data-dir", str(teacher_dir), "--file", str(archive)],
        )
        assert result.exit_code == 0, result.stdout

    result = runner.invoke(
        app,
        [
            "teacher",
            "stage2",
            "assign",
            "--data-dir",
            str(teacher_dir),
            "--reviews-per-problem",
            "2",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assignment_a = (
        teacher_dir
        / "stage2-review-assignment/review-packages"
        / teacher_package_name("2026000001", "stage2", "review-assignment")
    )
    assert assignment_a.exists()

    result = runner.invoke(
        app,
        ["student", "stage2", "import", "--data-dir", str(student_a_dir), "--file", str(assignment_a)],
    )
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["student", "stage2", "list", "--data-dir", str(student_a_dir)])
    assert result.exit_code == 0, result.stdout
    assigned = json.loads(result.stdout)["assigned_problems"]
    assert len(assigned) == PROBLEMS_PER_STUDENT
    for item in assigned:
        result = runner.invoke(
            app,
            [
                "student",
                "stage2",
                "review",
                "--data-dir",
                str(student_a_dir),
                "--anonymous-id",
                item["anonymous_id"],
                "--conclusion",
                "major",
                "--explanation",
                "建议增加边界数据",
                "--quality-score",
                "4",
            ],
        )
        assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["student", "stage2", "export", "--data-dir", str(student_a_dir)])
    assert result.exit_code == 0, result.stdout
    review_archive = Path(json.loads(result.stdout)["archive"])
    assert review_archive.exists()

    result = runner.invoke(
        app,
        [
            "teacher",
            "stage2",
            "upload-reviews",
            "--data-dir",
            str(teacher_dir),
            "--file",
            str(review_archive),
        ],
    )
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["teacher", "stage3", "feedback", "--data-dir", str(teacher_dir)])
    assert result.exit_code == 0, result.stdout
    feedback_b = (
        teacher_dir
        / "stage3-revisions/feedback-packages"
        / teacher_package_name("2026000002", "stage3", "review-feedback")
    )
    assert feedback_b.exists()

    result = runner.invoke(
        app,
        ["student", "stage3", "import", "--data-dir", str(student_b_dir), "--file", str(feedback_b)],
    )
    assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["student", "stage3", "list", "--data-dir", str(student_b_dir)])
    assert result.exit_code == 0, result.stdout
    stage3_list = json.loads(result.stdout)
    assert len(stage3_list["reviews"]) == PROBLEMS_PER_STUDENT
    problem_id = stage3_list["reviews"][0]["problem_id"]
    review_ids = [item["review_id"] for item in stage3_list["reviews"]]

    problem_file = tmp_path / "revised.json"
    problem_file.write_text(
        json.dumps(
            {
                "statement": "Return x after CLI revision.",
                "signature": "def solve(x: int) -> int:",
                "reference_solution": "def solve(x: int) -> int:\n    return x\n",
            }
        ),
        encoding="utf-8",
    )
    assert (
        runner.invoke(
            app,
            [
                "student",
                "stage3",
                "update",
                "--data-dir",
                str(student_b_dir),
                "--problem-id",
                problem_id,
                "--problem-file",
                str(problem_file),
            ],
        ).exit_code
        == 0
    )
    assert (
        runner.invoke(
            app,
            ["student", "stage3", "validate", "--data-dir", str(student_b_dir), "--problem-id", problem_id],
        ).exit_code
        == 0
    )
    result = runner.invoke(
        app,
        ["student", "stage3", "run", "--data-dir", str(student_b_dir), "--problem-id", problem_id],
    )
    assert result.exit_code == 0, result.stdout
    run_id = json.loads(result.stdout)["run_id"]
    assert (
        runner.invoke(
            app,
            [
                "student",
                "stage3",
                "select-runs",
                "--data-dir",
                str(student_b_dir),
                "--problem-id",
                problem_id,
                "--run-id",
                run_id,
            ],
        ).exit_code
        == 0
    )
    problem_ids = [problem["problem_id"] for problem in load_student_state(student_b_dir)["problems"]]
    args = ["student", "stage3", "select-problems", "--data-dir", str(student_b_dir)]
    for item in problem_ids:
        args.extend(["--problem-id", item])
    assert runner.invoke(app, args).exit_code == 0
    for review_id in review_ids:
        result = runner.invoke(
            app,
            [
                "student",
                "stage3",
                "respond",
                "--data-dir",
                str(student_b_dir),
                "--review-id",
                review_id,
                "--rating",
                "5",
                "--response",
                "已根据 CLI 审稿意见修订",
            ],
        )
        assert result.exit_code == 0, result.stdout
    result = runner.invoke(app, ["student", "stage3", "export", "--data-dir", str(student_b_dir)])
    assert result.exit_code == 0, result.stdout
    revision_archive = Path(json.loads(result.stdout)["archive"])
    manifest, payload = read_package(revision_archive)
    assert manifest["package_stage"] == STAGE3
    assert manifest["package_kind"] == KIND_REVISION
    assert revision_archive.name == student_package_name("2026000002", STAGE3, KIND_REVISION)
    exported_problem = next(problem for problem in payload["problems"] if problem["problem_id"] == problem_id)
    assert exported_problem["statement"] == "Return x after CLI revision."
    assert len(payload["responses"]) == PROBLEMS_PER_STUDENT


def _make_cli_stage1_package(
    runner: CliRunner, data_dir: Path, student_number: str, name: str
) -> Path:
    result = runner.invoke(
        app,
        [
            "student",
            "settings",
            "set",
            "--data-dir",
            str(data_dir),
            "--student-number",
            student_number,
            "--name",
            name,
            "--class-id",
            "A",
        ],
    )
    assert result.exit_code == 0, result.stdout
    problem_ids = []
    for _ in range(PROBLEMS_PER_STUDENT):
        result = runner.invoke(
            app, ["student", "stage1", "create", "--data-dir", str(data_dir), "--sample", "identity"]
        )
        assert result.exit_code == 0, result.stdout
        problem_id = json.loads(result.stdout)["problem_id"]
        problem_ids.append(problem_id)
        assert (
            runner.invoke(
                app,
                ["student", "stage1", "validate", "--data-dir", str(data_dir), "--problem-id", problem_id],
            ).exit_code
            == 0
        )
        result = runner.invoke(
            app,
            ["student", "stage1", "run", "--data-dir", str(data_dir), "--problem-id", problem_id],
        )
        assert result.exit_code == 0, result.stdout
        run_id = json.loads(result.stdout)["run_id"]
        assert (
            runner.invoke(
                app,
                [
                    "student",
                    "stage1",
                    "select-runs",
                    "--data-dir",
                    str(data_dir),
                    "--problem-id",
                    problem_id,
                    "--run-id",
                    run_id,
                ],
            ).exit_code
            == 0
        )
    args = ["student", "stage1", "select-problems", "--data-dir", str(data_dir)]
    for problem_id in problem_ids:
        args.extend(["--problem-id", problem_id])
    assert runner.invoke(app, args).exit_code == 0
    result = runner.invoke(app, ["student", "stage1", "export", "--data-dir", str(data_dir)])
    assert result.exit_code == 0, result.stdout
    return Path(json.loads(result.stdout)["archive"])
