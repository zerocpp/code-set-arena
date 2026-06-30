"""CodeSetArena CLI."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
import uvicorn

from .config import load_runtime_config, parse_models, update_local_api_key
from .course_validation import (
    validate_author_response,
    validate_review_assignment_payload,
    validate_review,
    validate_reviews_for_assignment,
    validate_responses_for_feedback,
    validate_stage1_problem_package,
)
from .demo_data import seed_demo_course
from .form_limits import ensure_list_max_length, ensure_max_length
from .constants import (
    AI_REVIEWER_STUDENT_NUMBER,
    APP_NAME,
    AUTHOR_TESTS_PER_PROBLEM,
    DEFAULT_REVIEWS_PER_PROBLEM,
    KIND_COURSE_STATS,
    KIND_PROBLEMS,
    KIND_REVIEW_ASSIGNMENT,
    KIND_REVIEW_FEEDBACK,
    KIND_REVIEWS,
    KIND_REVISION,
    PUBLIC_TESTS_PER_PROBLEM,
    ROLE_STUDENT,
    ROLE_TEACHER,
    RUN_ORIGIN_TA_OFFICIAL_EVAL,
    STAGE1,
    STAGE2,
    STAGE3,
    STAGE4,
)
from .package_names import (
    assert_student_archive,
    assert_teacher_archive,
    student_package_name,
    teacher_bulk_name,
    teacher_package_name,
)
from .packages import read_package, write_package
from .paths import default_student_root, default_teacher_root, ensure_student_tree, ensure_teacher_tree
from .storage import append_audit, load_student_state, load_teacher_state, save_student_state, save_teacher_state, write_json
from .student_app import (
    _build_run_record,
    _default_problem,
    _effective_settings as _student_effective_settings,
    _find_problem,
    _invalidate_validation_if_changed,
    _problems_for_export,
    _set_package_run_selection,
    _set_stage1_problem_selection,
    _stage1_problem_rows,
    _test_json_from_parts,
    _validate_problem,
    _validation_error,
    _validation_view,
)
from .teacher_app import _assert_manifest as _teacher_assert_manifest
from .teacher_app import _ai_reviewer_student
from .teacher_app import _effective_settings as _teacher_effective_settings
from .teacher_app import _review_assignment_problem
from .teacher_app import _stats as _teacher_stats
from .student_app import _assert_manifest as _student_assert_manifest
from .student_app import _require_student
from .student_app import _student_from_payload
from .run_engine import RunEngineError
from .student_app import create_student_app
from .teacher_app import create_teacher_app
from .teacher_eval import (
    add_eval_display_model,
    clear_eval_run_selection,
    remove_eval_display_model,
    run_official_eval_for_model,
    set_eval_run_selection,
    write_official_eval_package,
)
from .teacher_assignments import build_review_assignment_packages, build_review_feedback_packages

app = typer.Typer(help=f"{APP_NAME} local course system")
student_app = typer.Typer(help="Student-side commands")
teacher_app = typer.Typer(help="Teacher-side commands")
student_settings_app = typer.Typer(help="Student settings commands")
student_stage1_app = typer.Typer(help="Student Stage 1 commands")
student_stage2_app = typer.Typer(help="Student Stage 2 commands")
student_stage3_app = typer.Typer(help="Student Stage 3 commands")
teacher_settings_app = typer.Typer(help="Teacher settings commands")
teacher_stage1_app = typer.Typer(help="Teacher Stage 1 commands")
teacher_stage2_app = typer.Typer(help="Teacher Stage 2 commands")
teacher_stage3_app = typer.Typer(help="Teacher Stage 3 commands")
teacher_eval_app = typer.Typer(help="Teacher official evaluation commands")
teacher_eval_models_app = typer.Typer(help="Teacher official evaluation display model commands")
teacher_demo_app = typer.Typer(help="Teacher demo data commands")
teacher_stats_app = typer.Typer(help="Teacher stats commands")
teacher_audit_app = typer.Typer(help="Teacher audit commands")

app.add_typer(student_app, name="student")
app.add_typer(teacher_app, name="teacher")
student_app.add_typer(student_settings_app, name="settings")
student_app.add_typer(student_stage1_app, name="stage1")
student_app.add_typer(student_stage2_app, name="stage2")
student_app.add_typer(student_stage3_app, name="stage3")
teacher_app.add_typer(teacher_settings_app, name="settings")
teacher_app.add_typer(teacher_stage1_app, name="stage1")
teacher_app.add_typer(teacher_stage2_app, name="stage2")
teacher_app.add_typer(teacher_stage3_app, name="stage3")
teacher_app.add_typer(teacher_eval_app, name="eval")
teacher_eval_app.add_typer(teacher_eval_models_app, name="models")
teacher_app.add_typer(teacher_demo_app, name="demo")
teacher_app.add_typer(teacher_stats_app, name="stats")
teacher_app.add_typer(teacher_audit_app, name="audit")


@student_app.command("init")
def student_init(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    """Initialize the student work directory."""
    ensure_student_tree(data_dir)
    typer.echo(f"initialized student workspace: {data_dir}")


@student_app.command("reset")
def student_reset(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    """Reset the student work directory."""
    if data_dir.exists():
        shutil.rmtree(data_dir)
    ensure_student_tree(data_dir)
    typer.echo(f"reset student workspace: {data_dir}")


@student_app.command("serve")
def student_serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    """Run the student web app."""
    ensure_student_tree(data_dir)
    uvicorn.run(create_student_app(data_dir), host=host, port=port)


@student_settings_app.command("set")
def student_settings_set(
    student_number: str = typer.Option("", "--student-number"),
    name: str = typer.Option("", "--name"),
    class_id: str = typer.Option("", "--class-id"),
    base_url: str = typer.Option("", "--base-url"),
    api_key: str = typer.Option("", "--api-key"),
    clear_api_key: bool = typer.Option(False, "--clear-api-key"),
    models: str = typer.Option("", "--models"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    runtime = load_runtime_config(root)
    student_number = student_number.strip()
    name = name.strip()
    class_id = class_id.strip()
    try:
        base_url = base_url.strip() or runtime.base_url
        parsed_models = parse_models(models or runtime.models)
        ensure_max_length("student_number", student_number)
        ensure_max_length("person_name", name)
        ensure_max_length("class_id", class_id)
        ensure_max_length("base_url", base_url)
        ensure_list_max_length("model_name", parsed_models)
        update_local_api_key(root, api_key, clear=clear_api_key)
        runtime = load_runtime_config(root)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    state["student"] = {"student_number": student_number, "name": name, "class_id": class_id}
    state["settings"] = {
        "base_url": base_url,
        "api_key_set": runtime.api_key_set,
        "api_key_source": runtime.api_key_source,
        "models": parsed_models,
    }
    save_student_state(root, state)
    _echo_json(_redacted_settings_state(state, root, role="student"))


@student_settings_app.command("show")
def student_settings_show(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    root = ensure_student_tree(data_dir)
    _echo_json(_redacted_settings_state(load_student_state(root), root, role="student"))


@student_stage1_app.command("create")
def student_stage1_create(
    sample: str = typer.Option("", "--sample"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    problem_id = f"pb_cli_{len(state.get('problems', [])) + 1:02d}"
    problem = _default_problem(problem_id)
    if sample:
        _apply_sample_problem(problem, sample)
    state.setdefault("problems", []).append(problem)
    save_student_state(root, state)
    _echo_json({"problem_id": problem_id})


@student_stage1_app.command("list")
def student_stage1_list(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    _echo_json(
        {
            "count": len(state.get("problems", [])),
            "problems": [
                {
                    "problem_id": row["problem"].get("problem_id", ""),
                    "title": row["problem"].get("title", ""),
                    "validation_status": (row["problem"].get("validation") or {}).get("status", "missing"),
                    "run_count": len(row["problem"].get("run_records", [])),
                    "selected_valid_runs": row["selected_run_count"],
                    "legal_runs": row["legal_run_count"],
                    "package_status": row["package_status"],
                    "package_selected": row["selected_for_package"],
                }
                for row in _stage1_problem_rows(state)
            ],
        }
    )


@student_stage1_app.command("update")
def student_stage1_update(
    problem_id: str = typer.Option(..., "--problem-id"),
    problem_file: Path = typer.Option(..., "--problem-file"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    problem = _require_cli_problem(state, problem_id)
    _apply_problem_payload(problem, _read_json(problem_file))
    _invalidate_validation_if_changed(problem)
    save_student_state(root, state)
    _echo_json({"problem_id": problem_id, "updated": True})


@student_stage1_app.command("validate")
def student_stage1_validate(
    problem_id: str = typer.Option(..., "--problem-id"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    problem = _require_cli_problem(state, problem_id)
    try:
        problem["validation"] = _validate_problem(problem)
    except RunEngineError as exc:
        problem["validation"] = _validation_error(problem, str(exc), exc.error_type)
    save_student_state(root, state)
    _echo_json(problem["validation"])
    if problem["validation"]["status"] != "passed":
        raise typer.Exit(1)


@student_stage1_app.command("run")
def student_stage1_run(
    problem_id: str = typer.Option(..., "--problem-id"),
    model: str = typer.Option("", "--model"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    problem = _require_cli_problem(state, problem_id)
    if not _validation_view(problem)["ok"]:
        typer.echo("题目发生变更或尚未校验，请先校验参考答案", err=True)
        raise typer.Exit(1)
    try:
        run = _build_run_record(problem, state, model, root)
    except RunEngineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    problem.setdefault("run_records", []).insert(0, run)
    save_student_state(root, state)
    _echo_json({"run_id": run["run_id"], "verdict": run["verdict"], "model": run["model"]})


@student_stage1_app.command("select-runs")
def student_stage1_select_runs(
    problem_id: str = typer.Option(..., "--problem-id"),
    run_id: list[str] = typer.Option(..., "--run-id"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    count = _set_package_run_selection(_require_cli_problem(state, problem_id), set(run_id))
    save_student_state(root, state)
    _echo_json({"selected": count})


@student_stage1_app.command("select-problems")
def student_stage1_select_problems(
    problem_id: list[str] = typer.Option(..., "--problem-id"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    count = _set_stage1_problem_selection(state, set(problem_id))
    save_student_state(root, state)
    _echo_json({"selected": count})


@student_stage1_app.command("delete-run")
def student_stage1_delete_run(
    problem_id: str = typer.Option(..., "--problem-id"),
    run_id: str = typer.Option(..., "--run-id"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    problem = _require_cli_problem(state, problem_id)
    before = len(problem.get("run_records", []))
    problem["run_records"] = [run for run in problem.get("run_records", []) if run.get("run_id") != run_id]
    save_student_state(root, state)
    if before == len(problem["run_records"]):
        raise typer.BadParameter("模型运行记录不存在")
    _echo_json({"deleted": run_id})


@student_stage1_app.command("delete")
def student_stage1_delete(
    problem_id: str = typer.Option(..., "--problem-id"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    before = len(state.get("problems", []))
    state["problems"] = [problem for problem in state.get("problems", []) if problem.get("problem_id") != problem_id]
    save_student_state(root, state)
    if before == len(state["problems"]):
        raise typer.BadParameter("题目不存在")
    _echo_json({"deleted": problem_id})


@student_stage1_app.command("package")
def student_stage1_package(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    student = _require_student(state)
    output = root / "stage1-original/exports" / student_package_name(student["student_number"], STAGE1, KIND_PROBLEMS)
    write_package(
        output,
        role=ROLE_STUDENT,
        stage=STAGE1,
        kind=KIND_PROBLEMS,
        student_number=student["student_number"],
        payload={"student": student, "problems": _problems_for_export(state)},
    )
    _echo_json({"archive": str(output), "filename": output.name})


@student_stage1_app.command("export")
def student_stage1_export(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    """Alias for exporting the Stage 1 submission package."""
    student_stage1_package(data_dir)


@student_stage1_app.command("import")
def student_stage1_import(
    file: Path = typer.Option(..., "--file"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    manifest, payload = read_package(file)
    _student_assert_manifest(manifest, ROLE_STUDENT, STAGE1, KIND_PROBLEMS)
    student = _student_from_payload(payload)
    assert_student_archive(file, student["student_number"], STAGE1, KIND_PROBLEMS)
    problems = payload.get("problems")
    if not isinstance(problems, list):
        raise typer.BadParameter("payload problems must be a list")
    state["student"] = student
    state["problems"] = problems
    save_student_state(root, state)
    _echo_json({"imported": len(problems), "student_number": student["student_number"]})


@student_stage2_app.command("import")
def student_stage2_import(
    file: Path = typer.Option(..., "--file"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    manifest, payload = read_package(file)
    _student_assert_manifest(manifest, ROLE_TEACHER, STAGE2, KIND_REVIEW_ASSIGNMENT)
    validate_review_assignment_payload(payload)
    student = _student_from_payload(payload)
    assert_teacher_archive(file, student["student_number"], STAGE2, KIND_REVIEW_ASSIGNMENT)
    state["student"] = student
    state["assignment"] = payload
    state["reviews"] = {}
    state.pop("stage2_assignment_error", None)
    save_student_state(root, state)
    _echo_json({"assigned": len(payload.get("assigned_problems", []))})


@student_stage2_app.command("list")
def student_stage2_list(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    assignment = state.get("assignment") or {}
    reviews = state.get("reviews") or {}
    _echo_json(
        {
            "assignment_id": assignment.get("assignment_id", ""),
            "assigned_problems": [
                {
                    "anonymous_id": item.get("anonymous_id", ""),
                    "problem_id": item.get("problem_id", ""),
                    "title": item.get("title", ""),
                    "reviewed": item.get("anonymous_id", "") in reviews,
                    "conclusion": reviews.get(item.get("anonymous_id", ""), {}).get("conclusion", ""),
                    "quality_score": reviews.get(item.get("anonymous_id", ""), {}).get("quality_score", ""),
                }
                for item in assignment.get("assigned_problems", [])
            ],
        }
    )


@student_stage2_app.command("review")
def student_stage2_review(
    anonymous_id: str = typer.Option(..., "--anonymous-id"),
    conclusion: str = typer.Option(..., "--conclusion"),
    explanation: str = typer.Option(..., "--explanation"),
    quality_score: str = typer.Option("3", "--quality-score"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    _require_assigned_anonymous_id(state, anonymous_id)
    review = {
        "anonymous_id": anonymous_id,
        "conclusion": conclusion,
        "quality_score": quality_score,
        "explanation": explanation,
    }
    try:
        validate_review(review)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    state.setdefault("reviews", {})[anonymous_id] = review
    save_student_state(root, state)
    _echo_json({"reviewed": anonymous_id})


@student_stage2_app.command("package")
def student_stage2_package(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    student = _require_student(state)
    assignment = state.get("assignment")
    if not assignment:
        raise typer.BadParameter("请先导入助教发放的 Stage 2 审稿任务包")
    reviews = []
    for item in assignment.get("assigned_problems", []):
        review = state.get("reviews", {}).get(item["anonymous_id"])
        if not review:
            raise typer.BadParameter("审稿尚未完成")
        reviews.append(review)
    try:
        validate_reviews_for_assignment(
            {item["anonymous_id"] for item in assignment.get("assigned_problems", [])},
            reviews,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    output = root / "stage2-review/exports" / student_package_name(student["student_number"], STAGE2, KIND_REVIEWS)
    write_package(
        output,
        role=ROLE_STUDENT,
        stage=STAGE2,
        kind=KIND_REVIEWS,
        student_number=student["student_number"],
        payload={"student": student, "assignment_id": assignment.get("assignment_id", ""), "reviews": reviews},
    )
    _echo_json({"archive": str(output), "filename": output.name})


@student_stage2_app.command("export")
def student_stage2_export(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    """Alias for exporting the Stage 2 review package."""
    student_stage2_package(data_dir)


@student_stage3_app.command("import")
def student_stage3_import(
    file: Path = typer.Option(..., "--file"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    manifest, payload = read_package(file)
    _student_assert_manifest(manifest, ROLE_TEACHER, STAGE3, KIND_REVIEW_FEEDBACK)
    student = _student_from_payload(payload)
    assert_teacher_archive(file, student["student_number"], STAGE3, KIND_REVIEW_FEEDBACK)
    state["student"] = student
    state["feedback"] = payload
    state["revision_responses"] = {}
    save_student_state(root, state)
    _echo_json({"feedback": len(payload.get("reviews_for_author", []))})


@student_stage3_app.command("list")
def student_stage3_list(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    feedback = state.get("feedback") or {}
    responses = state.get("revision_responses") or {}
    _echo_json(
        {
            "feedback_count": len(feedback.get("reviews_for_author", [])),
            "problems": _cli_problem_rows(state),
            "reviews": [
                {
                    "review_id": item.get("review_id", ""),
                    "problem_id": item.get("problem_id", ""),
                    "anonymous_id": item.get("anonymous_id", ""),
                    "reviewer_student_number": item.get("reviewer_student_number", ""),
                    "conclusion": (item.get("review") or {}).get("conclusion", ""),
                    "explanation": (item.get("review") or {}).get("explanation", ""),
                    "responded": item.get("review_id", "") in responses,
                    "rating": responses.get(item.get("review_id", ""), {}).get("rating", ""),
                }
                for item in feedback.get("reviews_for_author", [])
            ],
        }
    )


@student_stage3_app.command("update")
def student_stage3_update(
    problem_id: str = typer.Option(..., "--problem-id"),
    problem_file: Path = typer.Option(..., "--problem-file"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    _require_stage3_feedback(state)
    problem = _require_cli_problem(state, problem_id)
    _apply_problem_payload(problem, _read_json(problem_file))
    _invalidate_validation_if_changed(problem)
    save_student_state(root, state)
    _echo_json({"problem_id": problem_id, "updated": True})


@student_stage3_app.command("validate")
def student_stage3_validate(
    problem_id: str = typer.Option(..., "--problem-id"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    _require_stage3_feedback(state)
    problem = _require_cli_problem(state, problem_id)
    try:
        problem["validation"] = _validate_problem(problem)
    except RunEngineError as exc:
        problem["validation"] = _validation_error(problem, str(exc), exc.error_type)
    save_student_state(root, state)
    _echo_json(problem["validation"])
    if problem["validation"]["status"] != "passed":
        raise typer.Exit(1)


@student_stage3_app.command("run")
def student_stage3_run(
    problem_id: str = typer.Option(..., "--problem-id"),
    model: str = typer.Option("", "--model"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    _require_stage3_feedback(state)
    problem = _require_cli_problem(state, problem_id)
    if not _validation_view(problem)["ok"]:
        typer.echo("题目发生变更或尚未校验，请先校验参考答案", err=True)
        raise typer.Exit(1)
    try:
        run = _build_run_record(problem, state, model, root)
    except RunEngineError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    problem.setdefault("run_records", []).insert(0, run)
    save_student_state(root, state)
    _echo_json({"run_id": run["run_id"], "verdict": run["verdict"], "model": run["model"]})


@student_stage3_app.command("select-runs")
def student_stage3_select_runs(
    problem_id: str = typer.Option(..., "--problem-id"),
    run_id: list[str] = typer.Option(..., "--run-id"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    _require_stage3_feedback(state)
    try:
        count = _set_package_run_selection(_require_cli_problem(state, problem_id), set(run_id))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    save_student_state(root, state)
    _echo_json({"selected": count})


@student_stage3_app.command("select-problems")
def student_stage3_select_problems(
    problem_id: list[str] = typer.Option(..., "--problem-id"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    _require_stage3_feedback(state)
    try:
        count = _set_stage1_problem_selection(state, set(problem_id))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    save_student_state(root, state)
    _echo_json({"selected": count})


@student_stage3_app.command("respond")
def student_stage3_respond(
    review_id: str = typer.Option(..., "--review-id"),
    rating: str = typer.Option(..., "--rating"),
    response: str = typer.Option(..., "--response"),
    data_dir: Path = typer.Option(default_student_root(), "--data-dir"),
) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    _require_feedback_review_id(state, review_id)
    response_payload = {
        "review_id": review_id,
        "rating": rating,
        "response": response,
    }
    try:
        validate_author_response(response_payload)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    state.setdefault("revision_responses", {})[review_id] = response_payload
    save_student_state(root, state)
    _echo_json({"responded": review_id})


@student_stage3_app.command("package")
def student_stage3_package(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    root = ensure_student_tree(data_dir)
    state = load_student_state(root)
    student = _require_student(state)
    feedback = state.get("feedback")
    if not feedback:
        raise typer.BadParameter("请先导入助教发放的 Stage 3 修订反馈包")
    responses = []
    for item in feedback.get("reviews_for_author", []):
        response = state.get("revision_responses", {}).get(item["review_id"])
        if not response:
            raise typer.BadParameter("作者回应尚未完成")
        responses.append(response)
    try:
        validate_responses_for_feedback(
            {item["review_id"] for item in feedback.get("reviews_for_author", [])},
            responses,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    output = root / "stage3-revision/exports" / student_package_name(student["student_number"], STAGE3, KIND_REVISION)
    write_package(
        output,
        role=ROLE_STUDENT,
        stage=STAGE3,
        kind=KIND_REVISION,
        student_number=student["student_number"],
        payload={"student": student, "problems": _problems_for_export(state), "responses": responses},
    )
    _echo_json({"archive": str(output), "filename": output.name})


@student_stage3_app.command("export")
def student_stage3_export(data_dir: Path = typer.Option(default_student_root(), "--data-dir")) -> None:
    """Alias for exporting the Stage 3 revision package."""
    student_stage3_package(data_dir)


@teacher_app.command("init")
def teacher_init(data_dir: Path = typer.Option(default_teacher_root(), "--data-dir")) -> None:
    """Initialize the teacher work directory."""
    ensure_teacher_tree(data_dir)
    typer.echo(f"initialized teacher workspace: {data_dir}")


@teacher_app.command("reset")
def teacher_reset(data_dir: Path = typer.Option(default_teacher_root(), "--data-dir")) -> None:
    """Reset the teacher work directory."""
    if data_dir.exists():
        shutil.rmtree(data_dir)
    ensure_teacher_tree(data_dir)
    typer.echo(f"reset teacher workspace: {data_dir}")


@teacher_app.command("serve")
def teacher_serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8010, "--port"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    """Run the teacher web app."""
    ensure_teacher_tree(data_dir)
    uvicorn.run(create_teacher_app(data_dir), host=host, port=port)


@teacher_settings_app.command("set")
def teacher_settings_set(
    course_name: str = typer.Option("CodeSetArena v7", "--course-name"),
    base_url: str = typer.Option("", "--base-url"),
    api_key: str = typer.Option("", "--api-key"),
    clear_api_key: bool = typer.Option(False, "--clear-api-key"),
    models: str = typer.Option("", "--models"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    runtime = load_runtime_config(root)
    course_name = course_name.strip() or "CodeSetArena v7"
    try:
        base_url = base_url.strip() or runtime.base_url
        parsed_models = parse_models(models or runtime.models)
        ensure_max_length("course_name", course_name)
        ensure_max_length("base_url", base_url)
        ensure_list_max_length("model_name", parsed_models)
        update_local_api_key(root, api_key, clear=clear_api_key)
        runtime = load_runtime_config(root)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    state["settings"] = {
        "course_name": course_name,
        "base_url": base_url,
        "api_key_set": runtime.api_key_set,
        "api_key_source": runtime.api_key_source,
        "models": parsed_models,
    }
    append_audit(state, "settings.saved", "teacher settings updated by cli")
    save_teacher_state(root, state)
    _echo_json(_redacted_settings_state(state, root, role="teacher"))


@teacher_settings_app.command("show")
def teacher_settings_show(data_dir: Path = typer.Option(default_teacher_root(), "--data-dir")) -> None:
    root = ensure_teacher_tree(data_dir)
    _echo_json(_redacted_settings_state(load_teacher_state(root), root, role="teacher"))


@teacher_stage1_app.command("upload")
def teacher_stage1_upload(
    file: Path = typer.Option(..., "--file"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    manifest, payload = read_package(file, root / "stage1-submissions/imports" / file.stem)
    _teacher_assert_manifest(manifest, ROLE_STUDENT, STAGE1, KIND_PROBLEMS)
    student = payload.get("student", {})
    student_number = student.get("student_number", "")
    assert_student_archive(file, student_number, STAGE1, KIND_PROBLEMS)
    problems = payload.get("problems", [])
    try:
        validate_stage1_problem_package(problems)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    state.setdefault("submissions", {})[student_number] = {
        "student": student,
        "problems": problems,
        "archive": file.name,
        "received_at": datetime.now(UTC).isoformat(),
    }
    append_audit(state, "stage1.uploaded", file.name)
    save_teacher_state(root, state)
    _echo_json({"student_number": student_number, "problems": len(problems)})


@teacher_stage1_app.command("list")
def teacher_stage1_list(data_dir: Path = typer.Option(default_teacher_root(), "--data-dir")) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    _echo_json({"students": sorted(state.get("submissions", {}))})


@teacher_stage2_app.command("assign")
def teacher_stage2_assign(
    reviews_per_problem: int = typer.Option(DEFAULT_REVIEWS_PER_PROBLEM, "--reviews-per-problem"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    bundle, package_paths, _ = build_review_assignment_packages(root, state, reviews_per_problem)
    append_audit(state, "stage2.assignments.generated", bundle.name)
    save_teacher_state(root, state)
    _echo_json({"bundle": str(bundle), "packages": [path.name for path in package_paths]})


@teacher_stage2_app.command("upload-reviews")
def teacher_stage2_upload_reviews(
    file: Path = typer.Option(..., "--file"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    manifest, payload = read_package(file)
    _teacher_assert_manifest(manifest, ROLE_STUDENT, STAGE2, KIND_REVIEWS)
    student = payload.get("student", {})
    reviewer = student.get("student_number", "")
    assert_student_archive(file, reviewer, STAGE2, KIND_REVIEWS)
    allowed = set(state.get("assignments", {}).get(reviewer, {}))
    try:
        validate_reviews_for_assignment(allowed, payload.get("reviews", []))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    state.setdefault("reviews", {})[reviewer] = {
        "student": student,
        "reviews": payload.get("reviews", []),
        "archive": file.name,
        "received_at": datetime.now(UTC).isoformat(),
    }
    append_audit(state, "stage2.reviews.uploaded", file.name)
    save_teacher_state(root, state)
    _echo_json({"reviewer": reviewer, "reviews": len(payload.get("reviews", []))})


@teacher_stage3_app.command("feedback")
def teacher_stage3_feedback(data_dir: Path = typer.Option(default_teacher_root(), "--data-dir")) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    bundle, package_paths, _ = build_review_feedback_packages(root, state)
    append_audit(state, "stage3.feedback.generated", bundle.name)
    save_teacher_state(root, state)
    _echo_json({"bundle": str(bundle), "packages": [path.name for path in package_paths]})


@teacher_stage3_app.command("upload-revision")
def teacher_stage3_upload_revision(
    file: Path = typer.Option(..., "--file"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    manifest, payload = read_package(file, root / "stage3-revisions/imports" / file.stem)
    _teacher_assert_manifest(manifest, ROLE_STUDENT, STAGE3, KIND_REVISION)
    student = payload.get("student", {})
    student_number = student.get("student_number", "")
    assert_student_archive(file, student_number, STAGE3, KIND_REVISION)
    feedback = state.get("feedback", {}).get(student_number)
    if not feedback:
        raise typer.BadParameter("student has no Stage 3 feedback package")
    try:
        validate_stage1_problem_package(payload.get("problems", []))
        validate_responses_for_feedback(
            {item.get("review_id", "") for item in feedback.get("reviews", [])},
            payload.get("responses", []),
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    state.setdefault("revisions", {})[student_number] = {
        "student": student,
        "problems": payload.get("problems", []),
        "responses": payload.get("responses", []),
        "archive": file.name,
        "received_at": datetime.now(UTC).isoformat(),
    }
    append_audit(state, "stage3.revision.uploaded", file.name)
    save_teacher_state(root, state)
    _echo_json({"student_number": student_number})


@teacher_eval_app.command("run")
def teacher_eval_run(
    model: str = typer.Option("", "--model"),
    mode: str = typer.Option("cache-first", "--mode"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    selected_model = model.strip() or _teacher_effective_settings(state, root)["models"][0]
    try:
        summary = run_official_eval_for_model(state, root, selected_model, mode=mode)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    output = write_official_eval_package(root, state)
    append_audit(state, "stage4.official_eval.run", output.name)
    save_teacher_state(root, state)
    _echo_json(
        {
            "archive": str(output),
            "summary": summary,
            "run": state.get("eval_runs", [{}])[-1] if state.get("eval_runs") else {},
        }
    )


@teacher_eval_models_app.command("list")
def teacher_eval_models_list(data_dir: Path = typer.Option(default_teacher_root(), "--data-dir")) -> None:
    state = load_teacher_state(ensure_teacher_tree(data_dir))
    _echo_json(
        {
            "executed_models": sorted(
                {
                    run.get("model")
                    for run in state.get("eval_runs", [])
                    if run.get("run_origin") == RUN_ORIGIN_TA_OFFICIAL_EVAL and run.get("model")
                }
            ),
            "display_models": state.get("eval_display_models", []),
        }
    )


@teacher_eval_models_app.command("add")
def teacher_eval_models_add(
    model: str = typer.Option(..., "--model"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    try:
        display_models = add_eval_display_model(state, model)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    save_teacher_state(root, state)
    _echo_json({"display_models": display_models})


@teacher_eval_models_app.command("remove")
def teacher_eval_models_remove(
    model: str = typer.Option(..., "--model"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    display_models = remove_eval_display_model(state, model)
    save_teacher_state(root, state)
    _echo_json({"display_models": display_models})


@teacher_eval_app.command("select-run")
def teacher_eval_select_run(
    student_number: str = typer.Option(..., "--student-number"),
    problem_id: str = typer.Option(..., "--problem-id"),
    model: str = typer.Option(..., "--model"),
    run_id: str = typer.Option(..., "--run-id"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    try:
        set_eval_run_selection(state, student_number, problem_id, model, run_id)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    save_teacher_state(root, state)
    _echo_json({"selected": run_id})


@teacher_eval_app.command("clear-run-selection")
def teacher_eval_clear_run_selection(
    student_number: str = typer.Option(..., "--student-number"),
    problem_id: str = typer.Option(..., "--problem-id"),
    model: str = typer.Option(..., "--model"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    clear_eval_run_selection(state, student_number, problem_id, model)
    save_teacher_state(root, state)
    _echo_json({"cleared": True})


@teacher_demo_app.command("seed-course")
def teacher_demo_seed_course(
    force: bool = typer.Option(False, "--force"),
    data_dir: Path = typer.Option(default_teacher_root(), "--data-dir"),
) -> None:
    try:
        summary = seed_demo_course(ensure_teacher_tree(data_dir), force=force)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    _echo_json({"summary": summary, "data_dir": str(data_dir)})


@teacher_stats_app.command("export")
def teacher_stats_export(data_dir: Path = typer.Option(default_teacher_root(), "--data-dir")) -> None:
    root = ensure_teacher_tree(data_dir)
    state = load_teacher_state(root)
    output = root / "stats/exports" / teacher_bulk_name(STAGE4, KIND_COURSE_STATS)
    write_json(output, _teacher_stats(state))
    append_audit(state, "stage4.stats.exported", output.name)
    save_teacher_state(root, state)
    _echo_json({"archive": str(output), "stats": _teacher_stats(state)})


@teacher_audit_app.command("list")
def teacher_audit_list(data_dir: Path = typer.Option(default_teacher_root(), "--data-dir")) -> None:
    root = ensure_teacher_tree(data_dir)
    _echo_json({"audit": load_teacher_state(root).get("audit", [])})


def _redacted_settings_state(state: dict[str, Any], root: Path, role: str) -> dict[str, Any]:
    effective = (
        _student_effective_settings(state, root)
        if role == "student"
        else _teacher_effective_settings(state, root)
    )
    return {"student": state.get("student", {}), "settings": effective}


def _echo_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require_cli_problem(state: dict[str, Any], problem_id: str) -> dict[str, Any]:
    problem = _find_problem(state, problem_id)
    if problem is None:
        raise typer.BadParameter("题目不存在")
    return problem


def _cli_problem_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "problem_id": row["problem"].get("problem_id", ""),
            "title": row["problem"].get("title", ""),
            "validation_status": (row["problem"].get("validation") or {}).get("status", "missing"),
            "run_count": len(row["problem"].get("run_records", [])),
            "selected_valid_runs": row["selected_run_count"],
            "legal_runs": row["legal_run_count"],
            "package_status": row["package_status"],
            "package_selected": row["selected_for_package"],
        }
        for row in _stage1_problem_rows(state)
    ]


def _apply_sample_problem(problem: dict[str, Any], sample: str) -> None:
    if sample != "identity":
        raise typer.BadParameter("目前仅支持 --sample identity")
    problem.update(
        {
            "title": "Return x.",
            "statement": "Return x.",
            "signature": "def solve(x: int) -> int:",
            "reference_solution": "def solve(x: int) -> int:\n    return x\n",
            "public_tests": [
                _test_json_from_parts(json.dumps({"x": index + 1}), json.dumps(index + 1))
                for index in range(PUBLIC_TESTS_PER_PROBLEM)
            ],
            "author_tests": [
                _test_json_from_parts(json.dumps({"x": index}), json.dumps(index))
                for index in range(AUTHOR_TESTS_PER_PROBLEM)
            ],
            "notes": "",
        }
    )


def _apply_problem_payload(problem: dict[str, Any], payload: dict[str, Any]) -> None:
    field_limits = {
        "statement": "problem_statement",
        "signature": "function_signature",
        "reference_solution": "reference_solution",
        "notes": "notes",
    }
    for key in ["title", "statement", "signature", "reference_solution", "notes"]:
        if key in payload:
            if key in field_limits:
                ensure_max_length(field_limits[key], payload[key])
            problem[key] = str(payload[key])
    if "public_tests" in payload:
        problem["public_tests"] = _normalize_cli_tests(payload["public_tests"])
    if "author_tests" in payload:
        problem["author_tests"] = _normalize_cli_tests(payload["author_tests"])


def _normalize_cli_tests(values: Any) -> list[str]:
    normalized = []
    for item in values:
        if isinstance(item, str):
            normalized.append(item)
        else:
            normalized.append(_test_json_from_parts(json.dumps(item.get("kwargs", {})), json.dumps(item.get("expected"))))
    return normalized


def _require_assigned_anonymous_id(state: dict[str, Any], anonymous_id: str) -> None:
    assignment = state.get("assignment") or {}
    allowed = {item.get("anonymous_id") for item in assignment.get("assigned_problems", [])}
    if anonymous_id not in allowed:
        raise typer.BadParameter("匿名题目不在分配列表中")


def _require_feedback_review_id(state: dict[str, Any], review_id: str) -> None:
    feedback = state.get("feedback") or {}
    allowed = {item.get("review_id") for item in feedback.get("reviews_for_author", [])}
    if review_id not in allowed:
        raise typer.BadParameter("审稿意见不在反馈包中")


def _require_stage3_feedback(state: dict[str, Any]) -> None:
    if not state.get("feedback"):
        raise typer.BadParameter("请先导入助教发放的 Stage 3 修订反馈包")


def _generate_review_assignments(root: Path, state: dict[str, Any], reviews_per_problem: int) -> list[Path]:
    submissions = state.get("submissions", {})
    if not submissions:
        raise typer.BadParameter("至少需要 1 名学生的 Stage 1 包才能生成审稿任务")
    if reviews_per_problem < 1:
        raise typer.BadParameter("每题总审稿份数必须至少为 1，其中 1 份固定由 AI 完成")
    if reviews_per_problem > 99:
        raise typer.BadParameter("每题总审稿份数必须不超过 99")
    human_reviews_per_problem = reviews_per_problem - 1
    if human_reviews_per_problem > 0 and len(submissions) < 2:
        raise typer.BadParameter("需要学生互审时，至少需要 2 名学生的 Stage 1 包")
    if human_reviews_per_problem > len(submissions) - 1:
        raise typer.BadParameter("学生互审份数不能超过可分配的其他学生数量")
    students = sorted(submissions)
    assignments: dict[str, dict[str, Any]] = {}
    assigned_by_reviewer: dict[str, list[dict[str, Any]]] = {student: [] for student in students}
    package_paths = []

    ai_assigned: list[dict[str, Any]] = []
    for author in students:
        for problem_index, problem in enumerate(submissions[author]["problems"]):
            anon_id = f"anon_cli_ai_{author}_{problem_index}"
            ai_assigned.append(
                {
                    "anonymous_id": anon_id,
                    "review_origin": "ai",
                    **_review_assignment_problem(problem),
                }
            )
            assignments.setdefault(AI_REVIEWER_STUDENT_NUMBER, {})[anon_id] = {
                "author_student_number": author,
                "problem_id": problem.get("problem_id", ""),
                "problem_index": problem_index,
                "review_origin": "ai",
            }
    ai_output = root / "stage2-review-assignment/review-packages" / teacher_package_name(
        AI_REVIEWER_STUDENT_NUMBER, STAGE2, KIND_REVIEW_ASSIGNMENT
    )
    write_package(
        ai_output,
        role=ROLE_TEACHER,
        stage=STAGE2,
        kind=KIND_REVIEW_ASSIGNMENT,
        student_number=AI_REVIEWER_STUDENT_NUMBER,
        payload={
            "assignment_id": "asg_cli_ai",
            "student": _ai_reviewer_student(),
            "reviews_per_problem": reviews_per_problem,
            "human_reviews_per_problem": human_reviews_per_problem,
            "ai_reviews_per_problem": 1,
            "review_origin": "ai",
            "assigned_problems": ai_assigned,
        },
    )
    package_paths.append(ai_output)

    for author_index, author in enumerate(students):
        for problem_index, problem in enumerate(submissions[author]["problems"]):
            for offset in range(1, human_reviews_per_problem + 1):
                reviewer = students[(author_index + offset) % len(students)]
                anon_id = f"anon_cli_{reviewer}_{author}_{problem_index}_{offset}"
                assigned_by_reviewer[reviewer].append(
                    {
                        "anonymous_id": anon_id,
                        "review_origin": "human",
                        **_review_assignment_problem(problem),
                    }
                )
                assignments.setdefault(reviewer, {})[anon_id] = {
                    "author_student_number": author,
                    "problem_id": problem.get("problem_id", ""),
                    "problem_index": problem_index,
                    "review_origin": "human",
                }
    for reviewer in students:
        assigned = assigned_by_reviewer[reviewer]
        if human_reviews_per_problem > 0 and not assigned:
            raise typer.BadParameter("审稿分配为空，请检查学生人数和每题总审稿份数")
        if not assigned:
            continue
        output = root / "stage2-review-assignment/review-packages" / teacher_package_name(reviewer, STAGE2, KIND_REVIEW_ASSIGNMENT)
        write_package(
            output,
            role=ROLE_TEACHER,
            stage=STAGE2,
            kind=KIND_REVIEW_ASSIGNMENT,
            student_number=reviewer,
            payload={
                "assignment_id": f"asg_cli_{reviewer}",
                "student": submissions[reviewer]["student"],
                "reviews_per_problem": reviews_per_problem,
                "human_reviews_per_problem": human_reviews_per_problem,
                "ai_reviews_per_problem": 1,
                "review_origin": "human",
                "assigned_problems": assigned,
            },
        )
        package_paths.append(output)
    state["assignments"] = assignments
    return package_paths


def _generate_feedback_packages(root: Path, state: dict[str, Any]) -> list[Path]:
    feedback_by_author: dict[str, list[dict[str, Any]]] = {}
    assignments = state.get("assignments", {})
    for reviewer, review_package in state.get("reviews", {}).items():
        for index, review in enumerate(review_package.get("reviews", []), start=1):
            anon_id = review.get("anonymous_id", "")
            mapping = assignments.get(reviewer, {}).get(anon_id)
            if not mapping:
                continue
            author = mapping["author_student_number"]
            feedback_by_author.setdefault(author, []).append(
                {
                    "review_id": f"rev_cli_{reviewer}_{index}",
                    "reviewer_student_number": reviewer,
                    "problem_id": mapping["problem_id"],
                    "anonymous_id": anon_id,
                    "review": review,
                }
            )
    if not feedback_by_author:
        raise typer.BadParameter("还没有可发放的审稿反馈")
    package_paths = []
    for author, reviews in feedback_by_author.items():
        output = root / "stage3-revisions/feedback-packages" / teacher_package_name(author, STAGE3, KIND_REVIEW_FEEDBACK)
        write_package(
            output,
            role=ROLE_TEACHER,
            stage=STAGE3,
            kind=KIND_REVIEW_FEEDBACK,
            student_number=author,
            payload={"student": state["submissions"][author]["student"], "reviews_for_author": reviews},
        )
        state.setdefault("feedback", {})[author] = {"archive": output.name, "reviews": reviews}
        package_paths.append(output)
    return package_paths
