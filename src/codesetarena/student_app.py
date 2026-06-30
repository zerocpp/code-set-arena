"""Student FastAPI application."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .constants import (
    APP_NAME,
    AUTHOR_REVIEW_RATING_OPTIONS,
    AUTHOR_TESTS_PER_PROBLEM,
    DEFAULT_BASE_URL,
    DEFAULT_MODELS,
    DISPLAY_VERSION,
    EXECUTION_PYTHON_IMAGE,
    EXECUTION_PYTHON_VERSION,
    EXECUTION_TARGET_SECONDS,
    EXECUTION_TIMEOUT_SECONDS,
    KIND_PROBLEMS,
    KIND_REVIEW_ASSIGNMENT,
    KIND_REVIEW_FEEDBACK,
    KIND_REVIEWS,
    KIND_REVISION,
    MAX_SELECTED_RUNS_PER_PROBLEM,
    MIN_SELECTED_RUNS_PER_PROBLEM,
    MODEL_RUN_TEMPERATURE,
    MODEL_RUN_TOP_P,
    PROBLEMS_PER_STUDENT,
    PUBLIC_TESTS_PER_PROBLEM,
    ROLE_STUDENT,
    ROLE_TEACHER,
    RUN_ORIGIN_STUDENT_SELF_TEST,
    STAGE1,
    STAGE2,
    STAGE3,
)
from .config import (
    MASKED_API_KEY,
    RuntimeConfig,
    load_runtime_config,
    parse_models,
    settings_are_configured,
    update_local_api_key,
)
from .course_validation import (
    ALLOWED_REVIEW_CONCLUSIONS,
    validate_author_response,
    validate_problem_draft,
    validate_review,
    validate_review_assignment_payload,
    validate_reviews_for_assignment,
    validate_responses_for_feedback,
)
from .form_limits import FORM_LIMITS, ensure_list_max_length, ensure_max_length
from .package_names import assert_student_archive, assert_teacher_archive, student_package_name
from .packages import PackageError, read_package, write_package
from .paths import default_student_root, ensure_student_tree
from .prompting import prompt_template_id, render_official_prompt, render_official_prompt_parts
from .model_client import real_completion
from .model_run_utils import execute_model_code, extract_function_code
from .reset_utils import clear_relative_dirs, remove_file
from .run_engine import RunEngineError, execute_problem
from .storage import default_student_state, load_student_state, save_student_state
from .versioning import snapshot_version
from .web_common import find_download, redirect, save_upload, split_lines

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
templates.env.globals["limits"] = FORM_LIMITS
templates.env.globals["display_version"] = DISPLAY_VERSION
templates.env.globals["problems_per_student"] = PROBLEMS_PER_STUDENT
templates.env.globals["public_tests_per_problem"] = PUBLIC_TESTS_PER_PROBLEM
templates.env.globals["author_tests_per_problem"] = AUTHOR_TESTS_PER_PROBLEM
templates.env.globals["min_selected_runs_per_problem"] = MIN_SELECTED_RUNS_PER_PROBLEM
templates.env.globals["max_selected_runs_per_problem"] = MAX_SELECTED_RUNS_PER_PROBLEM
DISPLAY_TZ = timezone(timedelta(hours=8))


def create_student_app(data_root: Path | None = None) -> FastAPI:
    root = ensure_student_tree(data_root or default_student_root())
    app = FastAPI(title=f"{APP_NAME} Student")
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    def state() -> dict[str, Any]:
        state_obj = load_student_state(root)
        if _normalize_state_for_form(state_obj) or _discard_invalid_stage2_assignment(state_obj):
            save_student_state(root, state_obj)
        return state_obj

    def save(state_obj: dict[str, Any]) -> None:
        save_student_state(root, state_obj)

    def view_state() -> dict[str, Any]:
        return _state_with_runtime_settings(state(), root)

    def wants_json(request: Request, form: Any | None = None) -> bool:
        requested_with = request.headers.get("x-requested-with", "").strip().lower()
        accept = request.headers.get("accept", "").strip().lower()
        if requested_with in {"fetch", "xmlhttprequest"} or "application/json" in accept:
            return True
        if form is not None:
            return str(form.get("_response_format", "")).strip().lower() == "json"
        return False

    @app.get("/", response_class=HTMLResponse)
    def home() -> Any:
        return redirect("/stage1")

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "student/settings.html",
            {
                "request": request,
                "active": "settings",
                "state": view_state(),
                "notice": request.query_params.get("notice", ""),
                "error": request.query_params.get("error", ""),
            },
        )

    @app.post("/settings")
    async def save_settings(request: Request) -> Any:
        form = await request.form()
        state_obj = state()
        runtime = load_runtime_config(root)
        try:
            api_key = str(form.get("api_key", MASKED_API_KEY))
            base_url = str(form.get("base_url", "")).strip() or runtime.base_url
            models = _parse_models_from_form(form)
            ensure_max_length("base_url", base_url)
            ensure_list_max_length("model_name", models)
            update_local_api_key(root, api_key, empty_clears=True)
            runtime = load_runtime_config(root)
            if {"student_number", "name", "class_id"} & set(form.keys()):
                state_obj["student"] = _student_from_form(form)
        except ValueError as exc:
            return redirect("/settings", error=str(exc))
        state_obj["settings"] = {
            "configured": True,
            "base_url": base_url,
            "api_key_set": runtime.api_key_set,
            "api_key_source": runtime.api_key_source,
            "api_key_display": MASKED_API_KEY if runtime.api_key_set else "",
            "models": models,
        }
        save(state_obj)
        return redirect("/settings", notice="设置已保存")

    @app.post("/settings/reset")
    async def reset_settings() -> Any:
        state_obj = state()
        defaults = default_student_state()
        state_obj["settings"] = defaults["settings"]
        remove_file(root / ".env")
        clear_relative_dirs(root, ["settings"])
        save(state_obj)
        return redirect("/settings", notice="设置已重置")

    @app.post("/student-info")
    async def save_student_info(request: Request) -> Any:
        form = await request.form()
        state_obj = state()
        try:
            state_obj["student"] = _student_from_form(form)
        except ValueError as exc:
            if wants_json(request, form):
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
            return redirect(_safe_next_path(form), error=str(exc))
        save(state_obj)
        if wants_json(request, form):
            return JSONResponse({"ok": True, "student": state_obj["student"]})
        return redirect(_safe_next_path(form), notice="学生信息已保存")

    @app.get("/stage1", response_class=HTMLResponse)
    def stage1_page(request: Request) -> Any:
        state_obj = state()
        stage1_rows = _stage1_problem_rows(state_obj)
        return templates.TemplateResponse(
            request,
            "student/stage1.html",
            {
                "request": request,
                "active": "stage1",
                "state": _state_with_runtime_settings(state_obj, root),
                "stage1_rows": stage1_rows,
                "selected_stage1_problem_count": sum(
                    1 for row in stage1_rows if row["selected_for_package"] and row["ready_for_package"]
                ),
                "notice": request.query_params.get("notice", ""),
                "error": request.query_params.get("error", ""),
                "download": request.query_params.get("download", ""),
            },
        )

    @app.post("/stage1/problems")
    async def create_problem() -> Any:
        state_obj = state()
        problem_id = "pb_" + uuid.uuid4().hex[:12]
        state_obj.setdefault("problems", []).append(_default_problem(problem_id))
        save(state_obj)
        return redirect(f"/stage1/problems/{problem_id}", notice="题目已创建")

    @app.get("/stage1/problems/{problem_id}", response_class=HTMLResponse)
    def problem_detail_page(request: Request, problem_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage1", error="题目不存在")
        validation_view = _validation_view(problem)
        selected_run_id = request.query_params.get("run_id", "")
        run_records_view, selected_run = _run_records_view(problem, selected_run_id)
        problem_summary = _problem_status_summary(problem, validation_view, run_records_view)
        return templates.TemplateResponse(
            request,
            "student/problem_detail.html",
            {
                "request": request,
                "active": "stage1",
                "state": _state_with_runtime_settings(state_obj, root),
                "problem": problem,
                "validation_view": validation_view,
                "problem_summary": problem_summary,
                "public_test_rows": _test_edit_rows(problem.get("public_tests", []), PUBLIC_TESTS_PER_PROBLEM),
                "author_test_rows": _test_edit_rows(problem.get("author_tests", []), AUTHOR_TESTS_PER_PROBLEM),
                "official_prompt": _official_prompt_for_problem(problem),
                "official_prompt_parts": _official_prompt_parts_for_problem(problem),
                "run_records_view": run_records_view,
                "selected_run": selected_run,
                "model_run_temperature": MODEL_RUN_TEMPERATURE,
                "model_run_top_p": MODEL_RUN_TOP_P,
                "execution_python_version": EXECUTION_PYTHON_VERSION,
                "execution_python_image": EXECUTION_PYTHON_IMAGE,
                "execution_target_seconds": EXECUTION_TARGET_SECONDS,
                "execution_timeout_seconds": EXECUTION_TIMEOUT_SECONDS,
                "model_options": _effective_settings(state_obj, root)["models"],
                "notice": request.query_params.get("notice", ""),
                "error": request.query_params.get("error", ""),
                "download": request.query_params.get("download", ""),
            },
        )

    @app.post("/stage1/problems/{problem_id}/save")
    async def save_problem(request: Request, problem_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage1", error="题目不存在")
        form = await request.form()
        try:
            _update_problem_from_form(problem, form)
        except ValueError as exc:
            return redirect(f"/stage1/problems/{problem_id}", error=str(exc))
        validation_stale = _invalidate_validation_if_changed(problem)
        save(state_obj)
        notice = "题目草稿已保存，校验已失效" if validation_stale else "题目草稿已保存"
        return redirect(f"/stage1/problems/{problem_id}", notice=notice)

    @app.post("/stage1/problems/{problem_id}/validate")
    async def validate_problem(request: Request, problem_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage1", error="题目不存在")
        form = await request.form()
        try:
            _update_problem_from_form(problem, form)
        except ValueError as exc:
            return redirect(f"/stage1/problems/{problem_id}#validation-panel", error=str(exc))
        try:
            validation = _validate_problem(problem)
        except RunEngineError as exc:
            validation = _validation_error(problem, str(exc), exc.error_type)
        problem["validation"] = validation
        _auto_select_recent_valid_runs(problem)
        save(state_obj)
        if validation["status"] == "passed":
            return redirect(f"/stage1/problems/{problem_id}#validation-panel", notice="校验通过")
        return redirect(f"/stage1/problems/{problem_id}#validation-panel", error=validation["message"])

    @app.post("/stage1/problems/{problem_id}/run")
    async def run_problem(request: Request, problem_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage1", error="题目不存在")
        form = await request.form()
        try:
            _update_problem_from_form(problem, form)
        except ValueError as exc:
            return redirect(f"/stage1/problems/{problem_id}", error=str(exc))
        if not _validation_view(problem)["ok"]:
            _invalidate_validation_if_changed(problem)
            save(state_obj)
            return redirect(
                f"/stage1/problems/{problem_id}",
                error="题目发生变更或尚未校验，请先点击“保存题目并校验参考答案”完成校验",
            )
        try:
            run_record = _build_run_record(problem, state_obj, str(form.get("model", "")), root)
            problem.setdefault("run_records", []).insert(0, run_record)
            _auto_select_recent_valid_runs(problem)
        except RunEngineError as exc:
            save(state_obj)
            return redirect(f"/stage1/problems/{problem_id}", error=str(exc))
        save(state_obj)
        return redirect(
            f"/stage1/problems/{problem_id}",
            notice=f"执行模型运行完成，结果：{run_record['verdict']}",
        )

    @app.post("/stage1/problems/{problem_id}/runs/package-selection")
    async def update_run_package_selection(request: Request, problem_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage1", error="题目不存在")
        form = await request.form()
        selected_run_ids = {str(run_id) for run_id in form.getlist("package_run_ids")}
        json_response = wants_json(request, form)
        try:
            if json_response:
                selected_count = _set_package_run_selection_draft(problem, selected_run_ids)
            else:
                selected_count = _set_package_run_selection(problem, selected_run_ids)
        except ValueError as exc:
            save(state_obj)
            if json_response:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
            return redirect(f"/stage1/problems/{problem_id}", error=str(exc))
        save(state_obj)
        if json_response:
            return JSONResponse({"ok": True, "selected": selected_count})
        return redirect(
            f"/stage1/problems/{problem_id}",
            notice=f"已选择 {selected_count} 条模型运行记录用于打包",
        )

    @app.post("/stage1/problems/package-selection")
    async def update_problem_package_selection(request: Request) -> Any:
        state_obj = state()
        form = await request.form()
        selected_problem_ids = {str(problem_id) for problem_id in form.getlist("package_problem_ids")}
        json_response = wants_json(request, form)
        try:
            if json_response:
                selected_count = _set_stage1_problem_selection_draft(state_obj, selected_problem_ids)
            else:
                selected_count = _set_stage1_problem_selection(state_obj, selected_problem_ids)
        except ValueError as exc:
            save(state_obj)
            if json_response:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
            return redirect("/stage1", error=str(exc))
        save(state_obj)
        if json_response:
            return JSONResponse({"ok": True, "selected": selected_count})
        return redirect("/stage1", notice=f"已选择 {selected_count} 道题目用于 Stage 1 打包")

    @app.post("/stage1/reset")
    async def reset_stage1() -> Any:
        state_obj = state()
        state_obj["problems"] = []
        clear_relative_dirs(
            root,
            [
                "stage1-original/workspace/problems",
                "stage1-original/uploads",
                "stage1-original/exports",
            ],
        )
        save(state_obj)
        return redirect("/stage1", notice="Stage 1 已重置")

    @app.post("/stage1/problems/{problem_id}/runs/{run_id}/delete")
    async def delete_run_record(problem_id: str, run_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage1", error="题目不存在")
        before = len(problem.get("run_records", []))
        problem["run_records"] = [
            run for run in problem.get("run_records", []) if run.get("run_id") != run_id
        ]
        _auto_select_recent_valid_runs(problem)
        save(state_obj)
        if len(problem["run_records"]) == before:
            return redirect(f"/stage1/problems/{problem_id}", error="模型运行记录不存在")
        return redirect(f"/stage1/problems/{problem_id}", notice="模型运行记录已删除")

    @app.post("/stage1/problems/{problem_id}/self-test")
    async def record_self_test(problem_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage1", error="题目不存在")
        if not _validation_view(problem)["ok"]:
            return redirect(
                f"/stage1/problems/{problem_id}",
                error="题目发生变更或尚未校验，请先点击“保存题目并校验参考答案”完成校验",
            )
        try:
            problem.setdefault("run_records", []).insert(0, _build_run_record(problem, state_obj, "", root))
            _auto_select_recent_valid_runs(problem)
        except RunEngineError as exc:
            return redirect(f"/stage1/problems/{problem_id}", error=str(exc))
        save(state_obj)
        return redirect(f"/stage1/problems/{problem_id}", notice="已记录一次学生自测")

    @app.post("/stage1/problems/{problem_id}/delete")
    async def delete_problem(problem_id: str) -> Any:
        state_obj = state()
        state_obj["problems"] = [
            problem for problem in state_obj.get("problems", []) if problem["problem_id"] != problem_id
        ]
        save(state_obj)
        return redirect("/stage1", notice="题目已删除")

    @app.post("/stage1/package")
    async def export_stage1() -> Any:
        state_obj = state()
        try:
            student = _require_student(state_obj)
            output = root / "stage1-original/exports" / student_package_name(
                student["student_number"], STAGE1, KIND_PROBLEMS
            )
            write_package(
                output,
                role=ROLE_STUDENT,
                stage=STAGE1,
                kind=KIND_PROBLEMS,
                student_number=student["student_number"],
                payload={"student": student, "problems": _problems_for_export(state_obj)},
            )
        except (PackageError, ValueError) as exc:
            return redirect("/stage1", error=str(exc))
        return redirect("/stage1", notice="Stage 1 原始题目包已导出", download=output.name)

    @app.post("/stage1/import")
    async def import_stage1(file: UploadFile = File(...)) -> Any:
        state_obj = state()
        try:
            archive = save_upload(file, root / "stage1-original/imports")
            manifest, payload = read_package(archive)
            _assert_manifest(manifest, ROLE_STUDENT, STAGE1, KIND_PROBLEMS)
            student = _student_from_payload(payload)
            assert_student_archive(archive, student["student_number"], STAGE1, KIND_PROBLEMS)
            problems = payload.get("problems")
            if not isinstance(problems, list):
                raise ValueError("payload problems must be a list")
            state_obj["student"] = student
            state_obj["problems"] = problems
            save(state_obj)
        except Exception as exc:
            return redirect("/stage1", error="导入 Stage 1 原始题目包失败：" + str(exc))
        return redirect("/stage1", notice="Stage 1 原始题目包已导入，学生信息已同步")

    @app.get("/stage2", response_class=HTMLResponse)
    def stage2_page(request: Request) -> Any:
        page_error = request.query_params.get("error", "")
        package_error = request.query_params.get("package_error", "")
        if page_error.startswith("导出审稿包失败"):
            package_error = package_error or _friendly_stage2_review_error(page_error)
            page_error = ""
        return templates.TemplateResponse(
            request,
            "student/stage2.html",
            {
                "request": request,
                "active": "stage2",
                "state": view_state(),
                "notice": request.query_params.get("notice", ""),
                "error": page_error,
                "package_error": package_error,
                "download": request.query_params.get("download", ""),
            },
        )

    @app.post("/stage2/import")
    async def import_assignment(file: UploadFile = File(...)) -> Any:
        state_obj = state()
        try:
            archive = save_upload(file, root / "stage2-review/imports")
            manifest, payload = read_package(archive)
            _assert_manifest(manifest, ROLE_TEACHER, STAGE2, KIND_REVIEW_ASSIGNMENT)
            validate_review_assignment_payload(payload)
            student = _student_from_payload(payload)
            assert_teacher_archive(archive, student["student_number"], STAGE2, KIND_REVIEW_ASSIGNMENT)
            state_obj["student"] = student
            state_obj["assignment"] = payload
            state_obj["reviews"] = {}
            state_obj.pop("stage2_assignment_error", None)
            save(state_obj)
        except Exception as exc:
            return redirect("/stage2", error="导入审稿任务包失败：" + str(exc))
        return redirect("/stage2", notice="审稿任务包已导入")

    @app.post("/stage2/reset")
    async def reset_stage2() -> Any:
        state_obj = state()
        state_obj["assignment"] = None
        state_obj["reviews"] = {}
        state_obj.pop("stage2_assignment_error", None)
        clear_relative_dirs(
            root,
            [
                "stage2-review/imports",
                "stage2-review/workspace/reviews",
                "stage2-review/exports",
            ],
        )
        save(state_obj)
        return redirect("/stage2", notice="Stage 2 已重置")

    @app.post("/stage2/reviews/draft")
    async def save_stage2_review_draft(request: Request) -> Any:
        state_obj = state()
        form = await request.form()
        anon_id = str(form.get("anonymous_id", "")).strip()
        try:
            assignment = state_obj.get("assignment")
            if not assignment:
                raise ValueError("请先导入助教发放的 Stage 2 审稿任务包")
            assigned_ids = {
                str(item.get("anonymous_id", ""))
                for item in assignment.get("assigned_problems", [])
                if item.get("anonymous_id")
            }
            if anon_id not in assigned_ids:
                raise ValueError("审稿任务不存在，请重新导入助教发放的审稿任务包")
            review = _stage2_review_from_form(form, anon_id)
            _validate_stage2_review_draft(review)
            state_obj.setdefault("reviews", {})[anon_id] = review
            save(state_obj)
        except Exception as exc:
            if wants_json(request, form):
                return JSONResponse(
                    {"ok": False, "message": _friendly_stage2_review_error(str(exc))},
                    status_code=400,
                )
            return redirect("/stage2", package_error=_friendly_stage2_review_error(str(exc)))
        if wants_json(request, form):
            return JSONResponse({"ok": True, "anonymous_id": anon_id})
        return redirect("/stage2", notice="审稿草稿已保存")

    @app.post("/stage2/package")
    async def export_reviews(request: Request) -> Any:
        state_obj = state()
        try:
            student = _require_student(state_obj)
            assignment = state_obj.get("assignment")
            if not assignment:
                raise ValueError("请先导入助教发放的 Stage 2 审稿任务包")
            form = await request.form()
            reviews = []
            for item in assignment.get("assigned_problems", []):
                anon_id = item["anonymous_id"]
                review = _stage2_review_from_form(form, anon_id)
                validate_review(review)
                reviews.append(review)
            validate_reviews_for_assignment(
                {item["anonymous_id"] for item in assignment.get("assigned_problems", [])},
                reviews,
            )
            state_obj["reviews"] = {item["anonymous_id"]: item for item in reviews}
            output = root / "stage2-review/exports" / student_package_name(
                student["student_number"], STAGE2, KIND_REVIEWS
            )
            write_package(
                output,
                role=ROLE_STUDENT,
                stage=STAGE2,
                kind=KIND_REVIEWS,
                student_number=student["student_number"],
                payload={
                    "student": student,
                    "assignment_id": assignment.get("assignment_id", ""),
                    "reviews": reviews,
                },
            )
            save(state_obj)
        except Exception as exc:
            return redirect("/stage2", package_error=_friendly_stage2_review_error(str(exc)))
        return redirect("/stage2", notice="Stage 2 审稿提交包已导出", download=output.name)

    @app.get("/stage3", response_class=HTMLResponse)
    def stage3_page(request: Request) -> Any:
        state_obj = state()
        display_state = _state_with_runtime_settings(state_obj, root)
        return templates.TemplateResponse(
            request,
            "student/stage3.html",
            {
                "request": request,
                "active": "stage3",
                "state": display_state,
                "stage3_review_groups": _stage3_review_groups(display_state),
                "rating_options": AUTHOR_REVIEW_RATING_OPTIONS,
                "model_options": _effective_settings(state_obj, root)["models"],
                "model_run_temperature": MODEL_RUN_TEMPERATURE,
                "model_run_top_p": MODEL_RUN_TOP_P,
                "notice": request.query_params.get("notice", ""),
                "error": request.query_params.get("error", ""),
                "download": request.query_params.get("download", ""),
            },
        )

    @app.post("/stage3/import")
    async def import_feedback(file: UploadFile = File(...)) -> Any:
        state_obj = state()
        try:
            archive = save_upload(file, root / "stage3-revision/imports")
            manifest, payload = read_package(archive)
            _assert_manifest(manifest, ROLE_TEACHER, STAGE3, KIND_REVIEW_FEEDBACK)
            student = _student_from_payload(payload)
            assert_teacher_archive(archive, student["student_number"], STAGE3, KIND_REVIEW_FEEDBACK)
            state_obj["student"] = student
            state_obj["feedback"] = payload
            state_obj["revision_responses"] = {}
            save(state_obj)
        except Exception as exc:
            return redirect("/stage3", error="导入修订反馈包失败：" + str(exc))
        return redirect("/stage3", notice="修订反馈包已导入")

    @app.post("/stage3/problems/{problem_id}/validate")
    async def validate_stage3_problem(request: Request, problem_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage3", error="题目不存在")
        form = await request.form()
        try:
            _update_problem_from_form(problem, form)
        except ValueError as exc:
            return _stage3_problem_redirect(problem_id, error=str(exc))
        try:
            validation = _validate_problem(problem)
        except RunEngineError as exc:
            validation = _validation_error(problem, str(exc), exc.error_type)
        problem["validation"] = validation
        _auto_select_recent_valid_runs(problem)
        save(state_obj)
        if validation["status"] == "passed":
            return _stage3_problem_redirect(problem_id, notice="修订题目已保存，参考答案校验通过")
        return _stage3_problem_redirect(problem_id, error=validation["message"])

    @app.post("/stage3/problems/{problem_id}/run")
    async def run_stage3_problem(request: Request, problem_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage3", error="题目不存在")
        form = await request.form()
        try:
            _update_problem_from_form(problem, form)
        except ValueError as exc:
            return _stage3_problem_redirect(problem_id, error=str(exc))
        if not _validation_view(problem)["ok"]:
            _invalidate_validation_if_changed(problem)
            save(state_obj)
            return _stage3_problem_redirect(
                problem_id,
                error="题目发生变更或尚未校验，请先保存并校验参考答案",
            )
        try:
            run_record = _build_run_record(problem, state_obj, str(form.get("model", "")), root)
            problem.setdefault("run_records", []).insert(0, run_record)
            _auto_select_recent_valid_runs(problem)
        except RunEngineError as exc:
            save(state_obj)
            return _stage3_problem_redirect(problem_id, error=str(exc))
        save(state_obj)
        return _stage3_problem_redirect(
            problem_id,
            notice=f"修订题目模型运行完成，结果：{run_record['verdict']}",
        )

    @app.post("/stage3/problems/{problem_id}/runs/package-selection")
    async def update_stage3_run_package_selection(request: Request, problem_id: str) -> Any:
        state_obj = state()
        problem = _find_problem(state_obj, problem_id)
        if problem is None:
            return redirect("/stage3", error="题目不存在")
        form = await request.form()
        selected_run_ids = {str(run_id) for run_id in form.getlist("package_run_ids")}
        try:
            if wants_json(request):
                selected_count = _set_package_run_selection_draft(problem, selected_run_ids)
            else:
                selected_count = _set_package_run_selection(problem, selected_run_ids)
        except ValueError as exc:
            save(state_obj)
            return _stage3_problem_redirect(problem_id, error=str(exc))
        save(state_obj)
        return _stage3_problem_redirect(problem_id, notice=f"已选择 {selected_count} 条修订后运行记录用于打包")

    @app.post("/stage3/reset")
    async def reset_stage3() -> Any:
        state_obj = state()
        state_obj["feedback"] = None
        state_obj["revision_responses"] = {}
        clear_relative_dirs(
            root,
            [
                "stage3-revision/imports",
                "stage3-revision/workspace/problems",
                "stage3-revision/workspace/responses",
                "stage3-revision/exports",
            ],
        )
        save(state_obj)
        return redirect("/stage3", notice="Stage 3 已重置")

    @app.post("/stage3/package")
    async def export_revision(request: Request) -> Any:
        state_obj = state()
        form = await request.form()
        is_fetch = request.headers.get("X-Requested-With") == "fetch" or form.get("_response_format") == "json"
        output: Path | None = None
        try:
            student = _require_student(state_obj)
            feedback = state_obj.get("feedback")
            if not feedback:
                raise ValueError("请先导入助教发放的 Stage 3 修订反馈包")
            responses = []
            for item in feedback.get("reviews_for_author", []):
                key = item["review_id"]
                response = {
                    "review_id": key,
                    "rating": str(form.get(f"rating_{key}", "")).strip(),
                    "response": str(form.get(f"response_{key}", "")).strip(),
                }
                validate_author_response(response)
                responses.append(response)
            validate_responses_for_feedback(
                {item["review_id"] for item in feedback.get("reviews_for_author", [])},
                responses,
            )
            state_obj["revision_responses"] = {item["review_id"]: item for item in responses}
            output = root / "stage3-revision/exports" / student_package_name(
                student["student_number"], STAGE3, KIND_REVISION
            )
            write_package(
                output,
                role=ROLE_STUDENT,
                stage=STAGE3,
                kind=KIND_REVISION,
                student_number=student["student_number"],
                payload={
                    "student": student,
                    "problems": _problems_for_export(state_obj),
                    "responses": responses,
                },
            )
            save(state_obj)
        except Exception as exc:
            if is_fetch:
                return JSONResponse(
                    {"ok": False, "message": "导出修订包失败：" + str(exc)},
                    status_code=400,
                )
            return redirect("/stage3", error="导出修订包失败：" + str(exc))
        if is_fetch:
            return JSONResponse(
                {
                    "ok": True,
                    "message": "Stage 3 修订提交包已导出",
                    "download": output.name if output else "",
                }
            )
        return redirect("/stage3", notice="Stage 3 修订提交包已导出", download=output.name)

    @app.get("/downloads/{filename}")
    def download(filename: str) -> Any:
        path = find_download(
            root,
            filename,
            [
                "stage1-original/exports",
                "stage2-review/exports",
                "stage3-revision/exports",
            ],
        )
        if path is None:
            return redirect("/stage1", error="下载文件不存在")
        return FileResponse(path, filename=path.name)

    return app


def _default_problem(problem_id: str) -> dict[str, Any]:
    return {
        "problem_id": problem_id,
        "title": "未命名题目",
        "statement": "",
        "signature": "def solve(x: int) -> int:",
        "reference_solution": "def solve(x: int) -> int:\n    return x\n",
        "public_tests": [_identity_test_json(index + 1) for index in range(PUBLIC_TESTS_PER_PROBLEM)],
        "author_tests": [_identity_test_json(index) for index in range(AUTHOR_TESTS_PER_PROBLEM)],
        "failure_hypothesis": "",
        "notes": "",
        "run_analysis": "",
        "run_records": [],
        "validation": None,
    }


def _identity_test_json(value: int) -> str:
    return json.dumps(
        {"input": {"kwargs": {"x": value}}, "expected": value},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _find_problem(state: dict[str, Any], problem_id: str) -> dict[str, Any] | None:
    for problem in state.get("problems", []):
        if problem.get("problem_id") == problem_id:
            return problem
    return None


def _update_problem_from_form(problem: dict[str, Any], form: Any) -> None:
    statement = _normalize_text_field(form.get("statement", ""))
    signature = _normalize_text_field(form.get("signature", ""))
    reference_solution = _normalize_text_field(form.get("reference_solution", ""))
    notes = _normalize_text_field(form.get("notes", ""))
    ensure_max_length("problem_statement", statement)
    ensure_max_length("function_signature", signature)
    ensure_max_length("reference_solution", reference_solution)
    ensure_max_length("notes", notes)
    problem.update(
        {
            "title": _derived_title(problem, statement),
            "statement": statement,
            "signature": signature,
            "reference_solution": reference_solution,
            "public_tests": _tests_from_form(form, "public_test", PUBLIC_TESTS_PER_PROBLEM, "public_tests"),
            "author_tests": _tests_from_form(form, "author_test", AUTHOR_TESTS_PER_PROBLEM, "author_tests"),
            "failure_hypothesis": "",
            "notes": notes,
            "run_analysis": "",
        }
    )


def _tests_from_form(form: Any, prefix: str, count: int, legacy_name: str) -> list[str]:
    structured_prefix = prefix.removesuffix("_test")
    if any(
        f"{structured_prefix}_kwargs_{index}" in form or f"{structured_prefix}_expected_{index}" in form
        for index in range(count)
    ):
        return [
            _test_json_from_parts(
                str(form.get(f"{structured_prefix}_kwargs_{index}", "")).strip(),
                str(form.get(f"{structured_prefix}_expected_{index}", "")).strip(),
            )
            for index in range(count)
        ]
    values = [str(form.get(f"{prefix}_{index}", "")).strip() for index in range(count)]
    if any(values):
        return values
    return split_lines(str(form.get(legacy_name, "")))


def _test_json_from_parts(raw_kwargs: str, raw_expected: str) -> str:
    error = ""
    kwargs: Any = {}
    expected: Any = None
    ensure_max_length("test_kwargs", raw_kwargs)
    ensure_max_length("test_expected", raw_expected)
    try:
        kwargs = json.loads(raw_kwargs)
        if not isinstance(kwargs, dict):
            error = "输入参数必须是 JSON 对象，例如 {\"x\":-1}"
    except json.JSONDecodeError as exc:
        error = f"输入参数 JSON 格式错误：{exc.msg}"
    try:
        expected = json.loads(raw_expected)
        if isinstance(expected, dict) and "any_of" in expected:
            error = error or "期望输出不允许 expected.any_of，多答案格式不属于 EXACT_MATCH"
    except json.JSONDecodeError as exc:
        error = error or f"期望输出 JSON 格式错误：{exc.msg}"

    payload = {"input": {"kwargs": kwargs if isinstance(kwargs, dict) else {}}, "expected": expected}
    if error:
        payload.update({"__format_error": error, "__raw_kwargs": raw_kwargs, "__raw_expected": raw_expected})
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _test_edit_rows(tests: list[Any], count: int) -> list[dict[str, str | int]]:
    rows = []
    padded = list(tests)[:count] + [""] * max(0, count - len(tests))
    for index, line in enumerate(padded[:count]):
        parsed = _parse_test_line(line)
        if parsed.get("__raw_kwargs") is not None:
            kwargs_json = str(parsed.get("__raw_kwargs", ""))
            expected_json = str(parsed.get("__raw_expected", ""))
        else:
            kwargs_json = _compact_json(parsed.get("input", {}).get("kwargs", {}))
            expected_json = _compact_json(parsed.get("expected", None))
        rows.append({"index": index, "kwargs_json": kwargs_json, "expected_json": expected_json})
    return rows


def _parse_test_line(line: Any) -> dict[str, Any]:
    if isinstance(line, dict):
        return line
    if not isinstance(line, str) or not line.strip():
        return {"input": {"kwargs": {}}, "expected": None}
    try:
        parsed = json.loads(line)
    except json.JSONDecodeError:
        return {"__raw_kwargs": "", "__raw_expected": "", "__format_error": "测试用例 JSON 格式错误"}
    return parsed if isinstance(parsed, dict) else {"input": {"kwargs": {}}, "expected": parsed}


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _test_io_filter(test: Any) -> dict[str, str]:
    parsed = _parse_test_line(test)
    if parsed.get("__format_error"):
        raw = test if isinstance(test, str) else json.dumps(test, ensure_ascii=False, separators=(",", ":"))
        return {"input": raw, "output": str(parsed.get("__format_error", ""))}
    kwargs = parsed.get("input", {}).get("kwargs", {})
    return {"input": _compact_json(kwargs), "output": _compact_json(parsed.get("expected", None))}


templates.env.filters["test_io"] = _test_io_filter


def _stage3_problem_redirect(problem_id: str, **query: str) -> Any:
    return redirect(f"/stage3#stage3-problem-{problem_id}", **query)


def _stage3_review_groups(state: dict[str, Any]) -> list[dict[str, Any]]:
    feedback = state.get("feedback") or {}
    responses = state.get("revision_responses") or {}
    problems_by_id = {
        str(problem.get("problem_id", "")): problem
        for problem in state.get("problems", [])
        if problem.get("problem_id")
    }
    review_items_by_problem: dict[str, list[dict[str, Any]]] = {}
    for item in feedback.get("reviews_for_author", []):
        problem_id = str(item.get("problem_id", "")).strip() or "未记录题目 ID"
        review_id = str(item.get("review_id", ""))
        review_items_by_problem.setdefault(problem_id, []).append(
            {**item, "saved_response": responses.get(review_id, {})}
        )

    ordered_problem_ids = [
        str(problem.get("problem_id", ""))
        for problem in state.get("problems", [])
        if problem.get("problem_id") and problem.get("stage1_package_selected")
    ]
    for problem_id in review_items_by_problem:
        if problem_id not in ordered_problem_ids:
            ordered_problem_ids.append(problem_id)
    if not ordered_problem_ids:
        ordered_problem_ids = list(review_items_by_problem)

    groups = []
    for problem_id in ordered_problem_ids:
        problem = problems_by_id.get(problem_id)
        group: dict[str, Any] = {
            "problem_id": problem_id,
            "problem": problem,
            "reviews": review_items_by_problem.get(problem_id, []),
        }
        if problem:
            validation_view = _validation_view(problem)
            run_records_view, selected_run = _run_records_view(problem)
            group.update(
                {
                    "validation_view": validation_view,
                    "problem_summary": _problem_status_summary(
                        problem, validation_view, run_records_view, group["reviews"]
                    ),
                    "public_test_rows": _test_edit_rows(problem.get("public_tests", []), PUBLIC_TESTS_PER_PROBLEM),
                    "author_test_rows": _test_edit_rows(problem.get("author_tests", []), AUTHOR_TESTS_PER_PROBLEM),
                    "official_prompt_parts": _official_prompt_parts_for_problem(problem),
                    "run_records_view": run_records_view,
                    "selected_run": selected_run,
                }
            )
        groups.append(group)
    return groups


def _normalize_state_for_form(state: dict[str, Any]) -> bool:
    changed = False
    for problem in state.get("problems", []):
        changed = _normalize_problem_for_form(problem) or changed
        before_selection = [bool(run.get("package_selected")) for run in problem.get("run_records", [])]
        _auto_select_recent_valid_runs(problem)
        after_selection = [bool(run.get("package_selected")) for run in problem.get("run_records", [])]
        changed = before_selection != after_selection or changed
    return changed


def _discard_invalid_stage2_assignment(state: dict[str, Any]) -> bool:
    assignment = state.get("assignment")
    if not assignment:
        return False
    try:
        validate_review_assignment_payload(assignment)
    except ValueError as exc:
        state["assignment"] = None
        state["reviews"] = {}
        state["stage2_assignment_error"] = (
            "已移除旧审稿任务包：包内题目缺少参考答案、测试数据或作者自测记录。"
            f"请重新导入助教最新生成的审稿任务包。详情：{exc}"
        )
        return True
    return state.pop("stage2_assignment_error", None) is not None


def _normalize_problem_for_form(problem: dict[str, Any]) -> bool:
    """Keep stored problems stable under an unchanged detail-page submit."""

    before_hash = _problem_signature_hash(problem)
    changed = False
    for field in ["statement", "signature", "reference_solution", "notes"]:
        value = _normalize_text_field(problem.get(field, ""))
        if problem.get(field, "") != value:
            problem[field] = value
            changed = True

    for field in ["public_tests", "author_tests"]:
        normalized_tests = [_normalize_test_for_form(line) for line in problem.get(field, [])]
        if problem.get(field, []) != normalized_tests:
            problem[field] = normalized_tests
            changed = True

    if not changed:
        return _repair_form_equivalent_validation_hash(problem)

    after_hash = _problem_signature_hash(problem)
    validation = problem.get("validation")
    if isinstance(validation, dict) and validation.get("content_hash") == before_hash:
        validation["content_hash"] = after_hash
    for run in problem.get("run_records", []):
        if isinstance(run, dict) and run.get("content_hash") == before_hash:
            run["content_hash"] = after_hash
    return _repair_form_equivalent_validation_hash(problem) or True


def _normalize_text_field(value: Any) -> str:
    return str(value).replace("\r\n", "\n").replace("\r", "\n").strip()


def _repair_form_equivalent_validation_hash(problem: dict[str, Any]) -> bool:
    validation = problem.get("validation")
    if not isinstance(validation, dict):
        return False
    current_hash = _problem_signature_hash(problem)
    if validation.get("content_hash") == current_hash:
        return False
    equivalent_hashes = _legacy_form_equivalent_hashes(problem)
    if validation.get("content_hash") not in equivalent_hashes:
        return False

    validation["content_hash"] = current_hash
    if validation.get("status") == "stale" and _validation_tests_all_passed(validation):
        validation["status"] = "passed"
        validation["message"] = "校验通过"
    for run in problem.get("run_records", []):
        if isinstance(run, dict) and run.get("content_hash") in equivalent_hashes:
            run["content_hash"] = current_hash
    return True


def _legacy_form_equivalent_hashes(problem: dict[str, Any]) -> set[str]:
    variants = []
    reference_solution = str(problem.get("reference_solution", ""))
    if reference_solution and not reference_solution.endswith("\n"):
        variants.append({**problem, "reference_solution": reference_solution + "\n"})
    return {_problem_signature_hash(variant) for variant in variants}


def _validation_tests_all_passed(validation: dict[str, Any]) -> bool:
    test_results = validation.get("test_results", [])
    return bool(test_results) and all(case.get("verdict") == "passed" for case in test_results)


def _normalize_test_for_form(line: Any) -> str:
    parsed = _parse_test_line(line)
    if parsed.get("__format_error"):
        return line if isinstance(line, str) else json.dumps(line, ensure_ascii=False, separators=(",", ":"))
    kwargs = parsed.get("input", {}).get("kwargs", {})
    if not isinstance(kwargs, dict):
        kwargs = {}
    payload = {"input": {"kwargs": kwargs}, "expected": parsed.get("expected", None)}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _derived_title(problem: dict[str, Any], statement: str) -> str:
    for line in statement.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:60]
    return str(problem.get("title") or problem.get("problem_id") or "未命名题目")


def _problem_signature_hash(problem: dict[str, Any]) -> str:
    payload = {
        "statement": problem.get("statement", ""),
        "signature": problem.get("signature", ""),
        "reference_solution": problem.get("reference_solution", ""),
        "public_tests": problem.get("public_tests", []),
        "author_tests": problem.get("author_tests", []),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _official_prompt_for_problem(problem: dict[str, Any]) -> str:
    return render_official_prompt(
        str(problem.get("statement", "")),
        str(problem.get("signature", "")),
        problem.get("public_tests", []),
    )


def _official_prompt_parts_for_problem(problem: dict[str, Any]) -> list[dict[str, str]]:
    return render_official_prompt_parts(
        str(problem.get("statement", "")),
        str(problem.get("signature", "")),
        problem.get("public_tests", []),
    )


def _validation_view(problem: dict[str, Any]) -> dict[str, Any]:
    validation = problem.get("validation") or {}
    current_hash = _problem_signature_hash(problem)
    stored_hash = validation.get("content_hash", "")
    current_snapshot_version = snapshot_version()
    stored_snapshot_version = validation.get("snapshot_version", "")
    snapshot_mismatch = bool(validation) and stored_snapshot_version != current_snapshot_version
    ok = (
        validation.get("status") == "passed"
        and stored_hash == current_hash
        and stored_snapshot_version == current_snapshot_version
    )
    message = validation.get("message", "尚未校验")
    if snapshot_mismatch:
        message = "系统版本已变更，题目快照已失效，需要重新校验并运行"
    return {
        "ok": ok,
        "stale": bool(validation) and (stored_hash != current_hash or snapshot_mismatch),
        "snapshot_mismatch": snapshot_mismatch,
        "snapshot_version": stored_snapshot_version,
        "current_snapshot_version": current_snapshot_version,
        "current_hash": current_hash,
        "status": validation.get("status", "missing"),
        "message": message,
        "validated_at": validation.get("validated_at", ""),
        "test_results": validation.get("test_results", []),
    }


def _run_records_view(
    problem: dict[str, Any], selected_run_id: str = ""
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    rows = []
    selected: dict[str, Any] | None = None
    latest_matching: dict[str, Any] | None = None
    records = problem.get("run_records", [])
    for run in records:
        matches, validity_reason = _run_record_matches_current_prompt(problem, run)
        has_raw_evidence = _run_record_has_raw_evidence(run)
        selectable_for_package = matches and has_raw_evidence
        selected_for_package = bool(run.get("package_selected")) and selectable_for_package
        display_run = {
            **run,
            "created_at_display": _format_display_time(run.get("created_at", "")),
            "run_origin_display": _run_origin_label(str(run.get("run_origin", ""))),
        }
        row = {
            "run": display_run,
            "matches_current": matches,
            "validity_status": "有效" if matches else "无效",
            "validity_reason": validity_reason,
            "selectable_for_package": selectable_for_package,
            "selected_for_package": selected_for_package,
            "package_status": "已选打包"
            if selected_for_package
            else ("可选" if selectable_for_package else ("记录不完整" if matches else "已失效")),
        }
        rows.append(row)
        if matches and latest_matching is None:
            latest_matching = display_run
        if selected_run_id and run.get("run_id") == selected_run_id:
            selected = display_run
    if selected is None:
        selected = latest_matching or (
            {**records[0], "created_at_display": _format_display_time(records[0].get("created_at", ""))}
            if records
            else None
        )
    if selected is not None:
        matches, validity_reason = _run_record_matches_current_prompt(problem, selected)
        selected["matches_current"] = matches
        selected["validity_status"] = "有效" if matches else "无效"
        selected["validity_reason"] = validity_reason
    return rows, selected


def _problem_status_summary(
    problem: dict[str, Any],
    validation_view: dict[str, Any],
    run_records_view: list[dict[str, Any]],
    review_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    legal_runs = [row for row in run_records_view if row["selectable_for_package"]]
    selected_runs = [row for row in run_records_view if row["selected_for_package"]]
    non_pass_runs = [row for row in legal_runs if row["run"].get("verdict") != "passed"]
    reference_failed = [
        case for case in validation_view.get("test_results", []) if case.get("verdict") != "passed"
    ]
    selected_run_count = len(selected_runs)
    selected_runs_ok = MIN_SELECTED_RUNS_PER_PROBLEM <= selected_run_count <= MAX_SELECTED_RUNS_PER_PROBLEM
    review_required = review_items is not None
    review_complete = _review_items_have_author_responses(review_items or []) if review_required else False

    base_completed_steps = 1
    if validation_view["ok"]:
        base_completed_steps = 2
    if validation_view["ok"] and selected_runs_ok:
        base_completed_steps = 3
    completed_steps = base_completed_steps
    if review_required and base_completed_steps == 3 and review_complete:
        completed_steps = 4

    progress_steps = [
        {"key": "draft", "label": "草稿已创建"},
        {"key": "validation", "label": "参考答案校验"},
        {"key": "runs", "label": "运行记录已选择"},
    ]
    if review_required:
        progress_steps.append({"key": "review_response", "label": "审稿回应完成"})
    for index, step in enumerate(progress_steps, start=1):
        step["complete"] = index <= completed_steps

    progress_message = _problem_progress_message(
        problem,
        validation_view,
        legal_run_count=len(legal_runs),
        selected_run_count=selected_run_count,
        selected_runs_ok=selected_runs_ok,
        review_required=review_required,
        review_complete=review_complete,
    )
    return {
        "status_label": progress_message,
        "status_class": "ok" if completed_steps == len(progress_steps) else "warn",
        "progress_message": progress_message,
        "progress_steps": progress_steps,
        "completed_steps": completed_steps,
        "base_completed_steps": base_completed_steps,
        "review_required": review_required,
        "review_complete": review_complete,
        "total_runs": len(run_records_view),
        "legal_runs": len(legal_runs),
        "selected_runs": len(selected_runs),
        "non_pass_runs": len(non_pass_runs),
        "reference_failed": len(reference_failed),
    }


def _problem_progress_message(
    problem: dict[str, Any],
    validation_view: dict[str, Any],
    *,
    legal_run_count: int,
    selected_run_count: int,
    selected_runs_ok: bool,
    review_required: bool,
    review_complete: bool,
) -> str:
    if _problem_has_test_format_error(problem):
        return "用例格式有误，请修正输入或期望输出 JSON 后重新校验。"
    if validation_view.get("snapshot_mismatch"):
        return "系统版本已变更，题目快照已失效，请重新校验并运行。"
    if validation_view["stale"]:
        return "题目已修改，请重新保存并校验参考答案。"
    if validation_view["status"] in {"failed", "error"}:
        return _validation_failure_message(validation_view)
    if not validation_view["ok"]:
        return "请先保存题目并校验参考答案。"
    if not selected_runs_ok:
        if legal_run_count == 0:
            return (
                f"请执行模型运行，并选择 {MIN_SELECTED_RUNS_PER_PROBLEM}-"
                f"{MAX_SELECTED_RUNS_PER_PROBLEM} 条有效运行记录。"
            )
        if selected_run_count == 0:
            return "请选择至少 1 条有效运行记录。"
        return f"最多选择 {MAX_SELECTED_RUNS_PER_PROBLEM} 条有效运行记录。"
    if review_required and not review_complete:
        return "请完成审稿意见评分和回应。"
    return "题目已满足当前 Stage 提交要求。"


def _validation_failure_message(validation_view: dict[str, Any]) -> str:
    test_results = validation_view.get("test_results", [])
    errors = [str(case.get("error", "")) for case in test_results]
    error_types = {str(case.get("error_type", "")) for case in test_results}
    message = str(validation_view.get("message", ""))
    combined = " ".join([message, *errors])
    if "JSON" in combined or "any_of" in combined or "格式" in combined:
        return "用例格式有误，请修正输入或期望输出 JSON 后重新校验。"
    if "execution_timeout" in error_types or "执行超时" in combined:
        return "参考答案执行超时，请降低算法复杂度或缩小测试数据规模。"
    if "memory_limit_exceeded" in error_types or "内存" in combined:
        return "参考答案超出内存限制，请降低内存占用或缩小测试数据规模。"
    if "python_version_error" in error_types or "Python" in combined or "函数签名" in combined:
        return "Python 版本或函数签名不兼容，请检查函数签名与参考答案。"
    if "missing" in combined or "must contain exactly" in combined:
        return "题目信息不完整，请补全题面、函数签名、参考答案和固定数量的测试用例。"
    if any(case.get("verdict") == "error" for case in test_results):
        return "参考答案执行出错，请查看参考答案执行结果。"
    return "参考答案未通过校验，请检查参考答案、期望输出和测试数据。"


def _problem_has_test_format_error(problem: dict[str, Any]) -> bool:
    return any(
        bool(_parse_test_line(test).get("__format_error"))
        for field in ["public_tests", "author_tests"]
        for test in problem.get(field, [])
    )


def _review_items_have_author_responses(review_items: list[dict[str, Any]]) -> bool:
    if not review_items:
        return True
    for item in review_items:
        saved_response = item.get("saved_response") or {}
        try:
            rating = int(str(saved_response.get("rating", "")).strip())
        except ValueError:
            return False
        if not 1 <= rating <= 5:
            return False
        if not str(saved_response.get("response", "")).strip():
            return False
    return True


def _stage1_problem_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for problem in state.get("problems", []):
        selected_run_count, legal_run_count = _stage1_run_counts(problem)
        ready = _problem_ready_for_stage1_package(problem)
        selected = bool(problem.get("stage1_package_selected"))
        if selected and ready:
            status = "已选"
            status_class = "ok"
        elif selected and not ready:
            status = "已失效"
            status_class = "warn"
        elif ready:
            status = "可选"
            status_class = ""
        else:
            status = "不可打包"
            status_class = "warn"
        rows.append(
            {
                "problem": problem,
                "selected_run_count": selected_run_count,
                "legal_run_count": legal_run_count,
                "ready_for_package": ready,
                "selected_for_package": selected,
                "package_status": status,
                "package_status_class": status_class,
            }
        )
    return rows


def _stage1_run_counts(problem: dict[str, Any]) -> tuple[int, int]:
    run_records_view, _ = _run_records_view(problem)
    legal_runs = [row for row in run_records_view if row["selectable_for_package"]]
    selected_runs = [row for row in run_records_view if row["selected_for_package"]]
    return len(selected_runs), len(legal_runs)


def _problem_ready_for_stage1_package(problem: dict[str, Any]) -> bool:
    selected_run_count, _ = _stage1_run_counts(problem)
    return (
        _validation_view(problem)["ok"]
        and MIN_SELECTED_RUNS_PER_PROBLEM <= selected_run_count <= MAX_SELECTED_RUNS_PER_PROBLEM
    )


def _set_stage1_problem_selection(state: dict[str, Any], selected_problem_ids: set[str]) -> int:
    selectable_problem_ids = {
        str(problem.get("problem_id", ""))
        for problem in state.get("problems", [])
        if problem.get("problem_id") and _problem_ready_for_stage1_package(problem)
    }
    invalid_ids = selected_problem_ids - selectable_problem_ids
    if invalid_ids:
        raise ValueError("只能选择参考答案校验通过且已选择有效运行记录的题目")
    if len(selected_problem_ids) != PROBLEMS_PER_STUDENT:
        raise ValueError(f"必须选择 {PROBLEMS_PER_STUDENT} 道有效题目进行打包")
    for problem in state.get("problems", []):
        problem["stage1_package_selected"] = problem.get("problem_id") in selected_problem_ids
    return len(selected_problem_ids)


def _set_stage1_problem_selection_draft(state: dict[str, Any], selected_problem_ids: set[str]) -> int:
    selectable_problem_ids = {
        str(problem.get("problem_id", ""))
        for problem in state.get("problems", [])
        if problem.get("problem_id") and _problem_ready_for_stage1_package(problem)
    }
    invalid_ids = selected_problem_ids - selectable_problem_ids
    if invalid_ids:
        raise ValueError("只能选择参考答案校验通过且已选择有效运行记录的题目")
    if len(selected_problem_ids) > PROBLEMS_PER_STUDENT:
        raise ValueError(f"最多选择 {PROBLEMS_PER_STUDENT} 道有效题目进行打包")
    for problem in state.get("problems", []):
        problem["stage1_package_selected"] = problem.get("problem_id") in selected_problem_ids
    return len(selected_problem_ids)


def _set_package_run_selection(problem: dict[str, Any], selected_run_ids: set[str]) -> int:
    records = problem.get("run_records", [])
    selectable_run_ids = {
        str(run.get("run_id", ""))
        for run in records
        if _run_record_matches_current_prompt(problem, run)[0]
        and _run_record_has_raw_evidence(run)
        and run.get("run_id")
    }
    invalid_ids = selected_run_ids - selectable_run_ids
    if invalid_ids:
        raise ValueError("只能选择当前有效且记录完整的模型运行记录")
    if not MIN_SELECTED_RUNS_PER_PROBLEM <= len(selected_run_ids) <= MAX_SELECTED_RUNS_PER_PROBLEM:
        raise ValueError(
            f"每道题必须选择 {MIN_SELECTED_RUNS_PER_PROBLEM}-"
            f"{MAX_SELECTED_RUNS_PER_PROBLEM} 条模型运行记录用于打包"
        )
    for run in records:
        run["package_selected"] = (
            _run_record_matches_current_prompt(problem, run)[0]
            and _run_record_has_raw_evidence(run)
            and run.get("run_id") in selected_run_ids
        )
    return len(selected_run_ids)


def _set_package_run_selection_draft(problem: dict[str, Any], selected_run_ids: set[str]) -> int:
    records = problem.get("run_records", [])
    selectable_run_ids = {
        str(run.get("run_id", ""))
        for run in records
        if _run_record_matches_current_prompt(problem, run)[0]
        and _run_record_has_raw_evidence(run)
        and run.get("run_id")
    }
    invalid_ids = selected_run_ids - selectable_run_ids
    if invalid_ids:
        raise ValueError("只能选择当前有效且记录完整的模型运行记录")
    if len(selected_run_ids) > MAX_SELECTED_RUNS_PER_PROBLEM:
        raise ValueError(f"每道题最多选择 {MAX_SELECTED_RUNS_PER_PROBLEM} 条模型运行记录用于打包")
    for run in records:
        run["package_selected"] = (
            _run_record_matches_current_prompt(problem, run)[0]
            and _run_record_has_raw_evidence(run)
            and run.get("run_id") in selected_run_ids
        )
    return len(selected_run_ids)


def _auto_select_recent_valid_runs(problem: dict[str, Any]) -> int:
    selected_count = 0
    for run in problem.get("run_records", []):
        selectable = (
            _run_record_matches_current_prompt(problem, run)[0]
            and _run_record_has_raw_evidence(run)
            and bool(run.get("run_id"))
        )
        should_select = selectable and selected_count < MAX_SELECTED_RUNS_PER_PROBLEM
        run["package_selected"] = should_select
        if should_select:
            selected_count += 1
    return selected_count


def _selected_package_run_records(problem: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {**run, "package_selected": True}
        for run in problem.get("run_records", [])
        if run.get("package_selected")
        and _run_record_matches_current_prompt(problem, run)[0]
        and _run_record_has_raw_evidence(run)
    ]


def _run_record_has_raw_evidence(run: dict[str, Any]) -> bool:
    return bool(run.get("prompt") and run.get("api_request_raw") and run.get("api_response_raw"))


def _run_origin_label(run_origin: str) -> str:
    if run_origin == RUN_ORIGIN_STUDENT_SELF_TEST:
        return "学生自测"
    return run_origin or "未记录"


def _run_record_matches_current_prompt(problem: dict[str, Any], run: dict[str, Any]) -> tuple[bool, str]:
    if run.get("snapshot_version", "") != snapshot_version():
        return False, "系统版本不兼容，需要重新校验并运行"
    expected_prompt = _official_prompt_for_problem(problem)
    if run.get("prompt") != expected_prompt:
        return False, "提示词不同"
    if run.get("prompt_template_id") != prompt_template_id():
        return False, "提示词版本不同"
    if not _number_equal(run.get("temperature"), MODEL_RUN_TEMPERATURE):
        return False, "运行参数不同"
    if not _number_equal(run.get("top_p"), MODEL_RUN_TOP_P):
        return False, "运行参数不同"

    api_request_raw = run.get("api_request_raw")
    request_body = api_request_raw.get("body", {}) if isinstance(api_request_raw, dict) else {}
    if request_body:
        messages = request_body.get("messages") or []
        request_prompt = messages[0].get("content") if messages and isinstance(messages[0], dict) else None
        if request_prompt != expected_prompt:
            return False, "保存的请求内容与当前题目不同"
        if not _number_equal(request_body.get("temperature"), MODEL_RUN_TEMPERATURE):
            return False, "保存的运行参数与当前设置不同"
        if not _number_equal(request_body.get("top_p"), MODEL_RUN_TOP_P):
            return False, "保存的运行参数与当前设置不同"
        if request_body.get("stream") is not False:
            return False, "保存的运行参数与当前设置不同"
    return True, "提示词和固定参数一致"


def _number_equal(value: Any, expected: float) -> bool:
    try:
        return float(value) == expected
    except (TypeError, ValueError):
        return False


def _format_display_time(value: Any) -> str:
    if not value:
        return "未记录"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M:%S +0800")


def _problems_for_export(state: dict[str, Any]) -> list[dict[str, Any]]:
    exported = []
    selected_problems = [
        problem for problem in state.get("problems", []) if problem.get("stage1_package_selected")
    ]
    if len(selected_problems) != PROBLEMS_PER_STUDENT:
        raise ValueError(f"必须选择 {PROBLEMS_PER_STUDENT} 道有效题目进行打包")
    for problem in selected_problems:
        if not _validation_view(problem)["ok"]:
            problem_id = problem.get("problem_id") or problem.get("title") or "未命名题目"
            raise ValueError(f"{problem_id} 必须先完成当前版本题目的参考答案校验")
        selected_runs = _selected_package_run_records(problem)
        if not MIN_SELECTED_RUNS_PER_PROBLEM <= len(selected_runs) <= MAX_SELECTED_RUNS_PER_PROBLEM:
            problem_id = problem.get("problem_id") or problem.get("title") or "未命名题目"
            raise ValueError(
                f"{problem_id} 必须选择 {MIN_SELECTED_RUNS_PER_PROBLEM}-"
                f"{MAX_SELECTED_RUNS_PER_PROBLEM} 条当前有效且记录完整的模型运行记录"
            )
        exported.append({**problem, "run_records": selected_runs})
    return exported


def _validate_problem(problem: dict[str, Any]) -> dict[str, Any]:
    try:
        validate_problem_draft(problem)
    except ValueError as exc:
        raise RunEngineError(str(exc)) from exc
    result = execute_problem(problem)
    passed = result["verdict"] == "passed"
    return {
        "status": "passed" if passed else "failed",
        "content_hash": _problem_signature_hash(problem),
        "snapshot_version": snapshot_version(),
        "validated_at": datetime.now(UTC).isoformat(),
        "message": "校验通过" if passed else "题目校验未通过，请检查测试用例结果",
        "test_results": result["test_results"],
    }


def _validation_error(problem: dict[str, Any], message: str, error_type: str = "execution_error") -> dict[str, Any]:
    return {
        "status": "error",
        "error_type": error_type,
        "content_hash": _problem_signature_hash(problem),
        "snapshot_version": snapshot_version(),
        "validated_at": datetime.now(UTC).isoformat(),
        "message": f"题目校验失败（{error_type}）：" + message,
        "test_results": [],
    }


def _invalidate_validation_if_changed(problem: dict[str, Any]) -> bool:
    validation = problem.get("validation")
    if not validation:
        _auto_select_recent_valid_runs(problem)
        return False
    if validation.get("content_hash") == _problem_signature_hash(problem):
        _auto_select_recent_valid_runs(problem)
        return False
    problem["validation"] = {
        **validation,
        "status": "stale",
        "message": "题目已变更，校验已失效，需要重新校验",
    }
    _auto_select_recent_valid_runs(problem)
    return True


def _build_run_record(
    problem: dict[str, Any],
    state: dict[str, Any],
    requested_model: str,
    root: Path | None = None,
) -> dict[str, Any]:
    settings = _effective_settings(state, root)
    models = settings.get("models", DEFAULT_MODELS) or DEFAULT_MODELS
    model = requested_model.strip() or models[0]
    prompt = _official_prompt_for_problem(problem)
    prompt_parts = _official_prompt_parts_for_problem(problem)
    run_id = "run_" + uuid.uuid4().hex[:12]
    created_at = datetime.now(UTC).isoformat()
    base_url = _api_base_url(settings)
    runtime = load_runtime_config(root)
    model_config = RuntimeConfig(
        base_url=base_url,
        api_key=runtime.api_key,
        models=list(settings.get("models", DEFAULT_MODELS)),
        env_file=runtime.env_file,
    )
    try:
        completion = real_completion(config=model_config, model=model, prompt=prompt)
    except RuntimeError as exc:
        raise RunEngineError(str(exc), "model_api_error") from exc
    raw_response = completion.content
    extracted_code = extract_function_code(raw_response, str(problem.get("signature", "")))
    result = execute_model_code(problem, extracted_code)
    return {
        "run_id": run_id,
        "run_origin": RUN_ORIGIN_STUDENT_SELF_TEST,
        "model": model,
        "base_url": base_url,
        "prompt_template_id": prompt_template_id(),
        "prompt": prompt,
        "prompt_parts": prompt_parts,
        "content_hash": _problem_signature_hash(problem),
        "snapshot_version": snapshot_version(),
        "temperature": MODEL_RUN_TEMPERATURE,
        "top_p": MODEL_RUN_TOP_P,
        "verdict": result["verdict"],
        "created_at": created_at,
        "package_selected": False,
        "api_request_raw": completion.request_raw,
        "api_response_raw": completion.response_raw,
        "raw_response": raw_response,
        "extracted_code": extracted_code,
        "test_results": result["test_results"],
    }


def _api_base_url(settings: dict[str, Any]) -> str:
    return str(settings.get("base_url") or DEFAULT_BASE_URL).rstrip("/")


def _stage2_review_from_form(form: Any, anon_id: str) -> dict[str, str]:
    quality_key = f"quality_score_{anon_id}"
    quality_score = form.get(quality_key) if quality_key in form else "3"
    return {
        "anonymous_id": anon_id,
        "conclusion": str(form.get(f"conclusion_{anon_id}", "")).strip(),
        "quality_score": str(quality_score or "").strip(),
        "explanation": str(form.get(f"explanation_{anon_id}", "")).strip(),
    }


def _validate_stage2_review_draft(review: dict[str, str]) -> None:
    conclusion = review.get("conclusion", "")
    ensure_max_length("review_conclusion", conclusion)
    ensure_max_length("review_explanation", review.get("explanation", ""))
    if conclusion and conclusion not in ALLOWED_REVIEW_CONCLUSIONS:
        raise ValueError("请选择有效的审稿结论")
    quality_score = str(review.get("quality_score", "")).strip()
    if quality_score and quality_score not in {"1", "2", "3", "4", "5"}:
        raise ValueError("请选择有效的题目质量评分")


def _friendly_stage2_review_error(message: str) -> str:
    if "请先导入" in message or "审稿任务不存在" in message:
        return message
    if "请选择结论" in message or "conclusion" in message:
        return "请为每道题选择审稿结论。"
    if "review suggestion is required" in message or "suggestion is required" in message:
        return "请填写每道题的审稿建议。"
    if "quality score" in message or "题目质量评分" in message:
        return "请为每道题选择题目质量评分。"
    if "建议超过长度上限" in message or "review_explanation" in message:
        return "审稿建议过长，请缩短后再导出。"
    if "结论超过长度上限" in message or "review_conclusion" in message:
        return "审稿结论过长，请重新选择结论。"
    if "review package must contain exactly assigned reviews" in message:
        return "审稿内容与当前任务不匹配，请重新导入助教发放的审稿任务包。"
    return "导出审稿包失败，请检查每道题是否都选择了结论并填写了建议。"


def _student_from_form(form: Any) -> dict[str, str]:
    student = {
        "student_number": str(form.get("student_number", "")).strip(),
        "name": str(form.get("name", "")).strip(),
        "class_id": str(form.get("class_id", "")).strip(),
    }
    _validate_student_info(student)
    return student


def _student_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    raw_student = payload.get("student")
    if not isinstance(raw_student, dict):
        raise ValueError("导入包缺少学生信息")
    student = {
        "student_number": str(raw_student.get("student_number", "")).strip(),
        "name": str(raw_student.get("name", "")).strip(),
        "class_id": str(raw_student.get("class_id", "")).strip(),
    }
    _validate_student_info(student)
    return student


def _validate_student_info(student: dict[str, str]) -> None:
    ensure_max_length("student_number", student["student_number"])
    ensure_max_length("person_name", student["name"])
    ensure_max_length("class_id", student["class_id"])
    if not student["student_number"]:
        raise ValueError("学号不能为空")
    if not student["name"]:
        raise ValueError("姓名不能为空")
    student_package_name(student["student_number"], STAGE1, KIND_PROBLEMS)


def _safe_next_path(form: Any) -> str:
    next_path = str(form.get("next", "") or "/stage1")
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/stage1"
    return next_path.split("?", 1)[0]


def _require_student(state: dict[str, Any]) -> dict[str, str]:
    student = state.get("student", {})
    try:
        _validate_student_info(student)
    except (KeyError, ValueError) as exc:
        raise ValueError("请先填写并保存学生信息") from exc
    return student


def _assert_manifest(manifest: dict[str, Any], role: str, stage: str, kind: str) -> None:
    if manifest.get("package_role") != role:
        raise PackageError("manifest package_role 不匹配")
    if manifest.get("package_stage") != stage:
        raise PackageError("manifest package_stage 不匹配")
    if manifest.get("package_kind") != kind:
        raise PackageError("manifest package_kind 不匹配")


def _effective_settings(state: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    runtime = load_runtime_config(root)
    settings = state.get("settings", {})
    if settings_are_configured(settings):
        base_url = str(settings.get("base_url") or runtime.base_url or DEFAULT_BASE_URL)
        models = settings.get("models") or runtime.models or list(DEFAULT_MODELS)
    else:
        base_url = runtime.base_url or DEFAULT_BASE_URL
        models = runtime.models or list(DEFAULT_MODELS)
    return {
        "configured": settings_are_configured(settings),
        "base_url": base_url or DEFAULT_BASE_URL,
        "api_key_set": runtime.api_key_set,
        "api_key_source": runtime.api_key_source,
        "api_key_display": MASKED_API_KEY if runtime.api_key_set else "",
        "models": models or list(DEFAULT_MODELS),
    }


def _state_with_runtime_settings(state: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    return {**state, "settings": _effective_settings(state, root)}


def _parse_models(models: str) -> list[str]:
    return parse_models(models)


def _parse_models_from_form(form: Any) -> list[str]:
    if hasattr(form, "getlist"):
        values = [str(value) for value in form.getlist("models")]
        if len(values) > 1:
            parsed = [value.strip() for value in values if value.strip()]
            return parsed or list(DEFAULT_MODELS)
    return _parse_models(str(form.get("models", "")))
