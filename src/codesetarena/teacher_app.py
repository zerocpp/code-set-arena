"""Teacher FastAPI application."""

from __future__ import annotations

import json
import threading
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .constants import (
    AI_REVIEWER_CLASS_ID,
    AI_REVIEWER_NAME,
    AI_REVIEWER_STUDENT_NUMBER,
    APP_NAME,
    DEFAULT_RANDOM_SEED,
    DEFAULT_REVIEWS_PER_PROBLEM,
    DISPLAY_VERSION,
    KIND_COURSE_STATS,
    KIND_REVIEWS,
    KIND_REVISION,
    PROBLEMS_PER_STUDENT,
    ROLE_STUDENT,
    STAGE2,
    STAGE3,
    STAGE4,
)
from .config import (
    MASKED_API_KEY,
    load_runtime_config,
    parse_models,
    require_models,
    settings_are_configured,
    update_local_api_key,
    validate_api_key,
    validate_base_url,
)
from .course_validation import (
    validate_reviews_for_assignment,
    validate_responses_for_feedback,
    validate_stage1_problem_package,
)
from .form_limits import FORM_LIMITS, ensure_list_max_length, ensure_max_length
from .package_names import (
    assert_student_archive,
    teacher_bulk_name,
)
from .packages import PackageError, read_package
from .paths import default_teacher_root, ensure_teacher_tree
from .reset_utils import clear_relative_dirs, remove_file
from .storage import append_audit, default_teacher_state, load_teacher_state, save_teacher_state, write_json
from .teacher_eval import (
    add_eval_display_model,
    clear_eval_run_selection,
    create_eval_job,
    eval_display_models,
    eval_executed_models,
    eval_problem_rows,
    eval_result_for_model,
    eval_subjects,
    remove_eval_display_model,
    run_eval_job,
    run_official_eval_for_model,
    set_eval_run_selection,
    write_official_eval_package,
)
from .teacher_assignments import (
    build_review_assignment_packages,
    build_review_feedback_packages,
    import_review_assignment_bundle,
    parse_random_seed,
)
from .teacher_stage1 import (
    import_stage1_archive,
    load_student_roster_xlsx,
    missing_roster_students,
    revalidate_stage1_archives,
    stage1_invalid_statuses,
    stage1_roster_rows,
)
from .teacher_version_gate import (
    allowed_student_versions_from_settings,
    assert_student_package_version_allowed,
    normalize_allowed_student_versions,
)
from .web_common import find_download, redirect, save_upload

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
templates.env.globals["limits"] = FORM_LIMITS
templates.env.globals["display_version"] = DISPLAY_VERSION
templates.env.globals["problems_per_student"] = PROBLEMS_PER_STUDENT
templates.env.globals["default_reviews_per_problem"] = DEFAULT_REVIEWS_PER_PROBLEM
templates.env.globals["default_random_seed"] = DEFAULT_RANDOM_SEED
templates.env.filters["test_io"] = lambda test: _test_io_filter(test)


def create_teacher_app(data_root: Path | None = None) -> FastAPI:
    root = ensure_teacher_tree(data_root or default_teacher_root())
    app = FastAPI(title=f"{APP_NAME} Teacher")
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")

    def state() -> dict[str, Any]:
        return load_teacher_state(root)

    def save(state_obj: dict[str, Any]) -> None:
        save_teacher_state(root, state_obj)

    def view_state() -> dict[str, Any]:
        return _state_with_runtime_settings(state(), root)

    @app.get("/", response_class=HTMLResponse)
    def home() -> Any:
        return redirect("/stage1")

    @app.get("/students", response_class=HTMLResponse)
    def students_page(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "teacher/students.html",
            _context(request, "students", view_state()),
        )

    @app.post("/students/upload")
    async def upload_students(file: UploadFile = File(...)) -> Any:
        state_obj = state()
        try:
            archive = save_upload(file, root / "students")
            students = load_student_roster_xlsx(archive)
            state_obj["students"] = students
            append_audit(state_obj, "students.uploaded", archive.name)
            save(state_obj)
        except Exception as exc:
            return redirect("/students", error="导入学生名单失败：" + str(exc))
        return redirect("/students", notice=f"已导入 {len(students)} 名学生")

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "teacher/settings.html",
            _context(request, "settings", view_state()),
        )

    @app.post("/settings")
    async def save_settings(request: Request) -> Any:
        form = await request.form()
        state_obj = state()
        try:
            course_name = str(form.get("course_name", "")).strip() or "CodeSetArena v7"
            api_key = str(form.get("api_key", MASKED_API_KEY))
            base_url = str(form.get("base_url", "")).strip()
            models = _parse_models_from_form(form)
            random_seed = parse_random_seed(form.get("random_seed", DEFAULT_RANDOM_SEED))
            if "allowed_student_versions" in form:
                allowed_student_versions = normalize_allowed_student_versions(
                    [str(value) for value in form.getlist("allowed_student_versions")]
                    if hasattr(form, "getlist")
                    else str(form.get("allowed_student_versions", ""))
                )
            else:
                allowed_student_versions = allowed_student_versions_from_settings(
                    state_obj.get("settings", {})
                )
            runtime = load_runtime_config(root)
            validate_base_url(base_url)
            if api_key == MASKED_API_KEY:
                if not runtime.api_key_set:
                    raise ValueError("API Key 不能为空")
            elif not api_key.strip():
                raise ValueError("API Key 不能为空")
            else:
                validate_api_key(api_key)
            require_models(models)
            ensure_max_length("course_name", course_name)
            ensure_max_length("base_url", base_url)
            ensure_max_length("random_seed", random_seed)
            ensure_list_max_length("model_name", models)
            update_local_api_key(root, api_key, empty_clears=True)
            runtime = load_runtime_config(root)
        except ValueError as exc:
            return redirect("/settings", error=str(exc))
        state_obj["settings"] = {
            "configured": True,
            "course_name": course_name,
            "base_url": base_url,
            "api_key_set": runtime.api_key_set,
            "api_key_source": runtime.api_key_source,
            "api_key_display": MASKED_API_KEY if runtime.api_key_set else "",
            "models": models,
            "random_seed": random_seed,
            "allowed_student_versions": allowed_student_versions,
        }
        append_audit(state_obj, "settings.saved", "teacher settings updated")
        save(state_obj)
        return redirect("/settings", notice="设置已保存")

    @app.post("/settings/reset")
    async def reset_settings() -> Any:
        state_obj = state()
        defaults = default_teacher_state()
        state_obj["settings"] = defaults["settings"]
        remove_file(root / ".env")
        clear_relative_dirs(root, ["settings"])
        append_audit(state_obj, "settings.reset", "teacher settings reset")
        save(state_obj)
        return redirect("/settings", notice="设置已重置")

    @app.get("/stage1", response_class=HTMLResponse)
    def stage1_page(request: Request) -> Any:
        state_obj = state()
        context = _context(request, "stage1", state_obj)
        context["stage1_rows"] = stage1_roster_rows(state_obj)
        return templates.TemplateResponse(
            request, "teacher/stage1.html", context
        )

    @app.post("/stage1/upload")
    async def upload_stage1(file: UploadFile = File(...)) -> Any:
        state_obj = state()
        temp_archive: Path | None = None
        try:
            temp_archive = save_upload(file, root / "stage1-submissions/upload-check")
            result = import_stage1_archive(root, state_obj, temp_archive)
            _clear_teacher_downstream_from_stage2(state_obj, root)
            append_audit(state_obj, "stage1.uploaded", result.archive_name)
            save(state_obj)
        except Exception as exc:
            return redirect("/stage1", error="上传 Stage 1 包失败：" + str(exc))
        finally:
            if temp_archive:
                remove_file(temp_archive)
        return redirect("/stage1", notice=f"已导入 {result.student_number} 的 Stage 1 原始题目包")

    @app.post("/stage1/validate-all")
    async def validate_all_stage1() -> Any:
        state_obj = state()
        results = revalidate_stage1_archives(root, state_obj)
        _clear_teacher_downstream_from_stage2(state_obj, root)
        append_audit(state_obj, "stage1.validate_all", f"validated {len(results)} archives")
        save(state_obj)
        failures = {name: detail for name, detail in results.items() if detail != "ok"}
        if failures:
            return redirect("/stage1", error=f"一键校验完成，发现 {len(failures)} 个异常包")
        return redirect("/stage1", notice=f"一键校验完成，{len(results)} 个包通过")

    @app.post("/stage1/export-status")
    async def export_stage1_status() -> Any:
        state_obj = state()
        output = root / "stage1-submissions/exports/阶段1导出表.xlsx"
        _write_stage1_status_xlsx(output, stage1_roster_rows(state_obj))
        state_obj.setdefault("downloads", []).append(output.name)
        append_audit(state_obj, "stage1.status.exported", output.name)
        save(state_obj)
        return redirect("/stage1", notice="学生导入状态表已导出", download=output.name)

    @app.post("/stage1/reset")
    async def reset_stage1() -> Any:
        state_obj = state()
        state_obj["submissions"] = {}
        state_obj["stage1_package_status"] = {}
        _clear_teacher_downstream_from_stage2(state_obj, root)
        clear_relative_dirs(
            root,
            [
                "stage1-submissions/uploads",
                "stage1-submissions/imports",
                "stage1-submissions/validation-reports",
                "stage1-submissions/exports",
            ],
        )
        append_audit(state_obj, "stage1.reset", "stage1 submissions and downstream data reset")
        save(state_obj)
        return redirect("/stage1", notice="Stage 1 已重置")

    @app.get("/stage1/submissions/{student_number}", response_class=HTMLResponse)
    def stage1_submission_detail(request: Request, student_number: str) -> Any:
        state_obj = state()
        row = state_obj.get("submissions", {}).get(student_number)
        if not row:
            return redirect("/stage1", error="未找到该学生的 Stage 1 包")
        return templates.TemplateResponse(
            request,
            "teacher/package_detail.html",
            _package_detail_context(
                request,
                "stage1",
                "Stage 1 原始题目包详情",
                "/stage1",
                student_number,
                row,
                [("题目数", len(row.get("problems", [])))],
                state_obj,
            ),
        )

    @app.post("/stage1/submissions/{student_number}/delete")
    async def delete_stage1_submission(student_number: str) -> Any:
        state_obj = state()
        status = state_obj.setdefault("stage1_package_status", {}).get(student_number, {})
        row = state_obj.setdefault("submissions", {}).pop(student_number, None)
        archive = row.get("archive", "") if row else str(status.get("archive", ""))
        if not archive:
            return redirect("/stage1", error="未找到该学生的 Stage 1 包")
        _remove_received_archive(
            root,
            archive,
            upload_dir="stage1-submissions/uploads",
            import_dir="stage1-submissions/imports",
        )
        state_obj.setdefault("stage1_package_status", {}).pop(student_number, None)
        _clear_teacher_downstream_from_stage2(state_obj, root)
        append_audit(state_obj, "stage1.submission.deleted", student_number)
        save(state_obj)
        return redirect("/stage1", notice=f"已删除 {student_number} 的 Stage 1 包")

    @app.get("/stage2/assign", response_class=HTMLResponse)
    def stage2_assign_page(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "teacher/stage2_assign.html",
            _context(request, "stage2_assign", state()),
        )

    @app.post("/stage2/assign")
    async def generate_assignments(
        reviews_per_problem: int = Form(DEFAULT_REVIEWS_PER_PROBLEM),
        confirm_missing: str = Form(""),
    ) -> Any:
        state_obj = state()
        try:
            invalid = stage1_invalid_statuses(state_obj)
            if invalid:
                raise ValueError("Stage 1 存在异常包，不能生成审稿任务：" + "；".join(
                    f"{student}: {detail}" for student, detail in sorted(invalid.items())
                ))
            missing = missing_roster_students(state_obj)
            if missing and confirm_missing != "1":
                names = "、".join(
                    f"{student['student_number']} {student.get('name', '')}".strip()
                    for student in missing
                )
                raise ValueError(f"当前学生名单有 {len(missing)} 人缺席 Stage 1 包，请确认后再生成：{names}")
            _clear_teacher_downstream_from_stage2(state_obj, root)
            bundle, _, _ = build_review_assignment_packages(root, state_obj, reviews_per_problem)
            append_audit(state_obj, "stage2.assignments.generated", bundle.name)
            save(state_obj)
        except Exception as exc:
            return redirect("/stage2/assign", error="生成审稿任务包失败：" + str(exc))
        return redirect("/stage2/assign", notice="审稿任务包已生成", download=bundle.name)

    @app.post("/stage2/assign/reset")
    async def reset_stage2_assign() -> Any:
        state_obj = state()
        _clear_teacher_downstream_from_stage2(state_obj, root)
        append_audit(state_obj, "stage2.assign.reset", "stage2 assignments and downstream data reset")
        save(state_obj)
        return redirect("/stage2/assign", notice="Stage 2 审稿分配已重置")

    @app.post("/stage2/assign/import")
    async def import_stage2_assignments(file: UploadFile = File(...)) -> Any:
        state_obj = state()
        temp_archive: Path | None = None
        try:
            temp_archive = save_upload(file, root / "stage2-review-assignment/import-check")
            manifest = import_review_assignment_bundle(root, state_obj, temp_archive)
            _clear_teacher_downstream_from_reviews(state_obj, root)
            clear_relative_dirs(
                root,
                [
                    "stage2-review-assignment/anonymous-corpus",
                    "stage2-review-assignment/assignments",
                ],
            )
            append_audit(state_obj, "stage2.assign.imported", temp_archive.name)
            save(state_obj)
        except Exception as exc:
            return redirect("/stage2/assign", error="导入审稿任务包失败：" + str(exc))
        finally:
            if temp_archive:
                remove_file(temp_archive)
        return redirect(
            "/stage2/assign",
            notice=f"已导入审稿任务包，每题总审稿份数 {manifest.get('reviews_per_problem')}",
        )

    @app.get("/stage2/reviews", response_class=HTMLResponse)
    def stage2_reviews_page(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "teacher/stage2_reviews.html",
            _context(request, "stage2_reviews", state()),
        )

    @app.post("/stage2/reviews/upload")
    async def upload_reviews(file: UploadFile = File(...)) -> Any:
        state_obj = state()
        try:
            archive = save_upload(file, root / "stage2-review-assignment/imported-reviews")
            manifest, payload = read_package(archive)
            _assert_manifest(manifest, ROLE_STUDENT, STAGE2, KIND_REVIEWS)
            assert_student_package_version_allowed(manifest, state_obj.get("settings", {}))
            student = payload.get("student", {})
            reviewer = student.get("student_number", "")
            assert_student_archive(archive, reviewer, STAGE2, KIND_REVIEWS)
            allowed = set(state_obj.get("assignments", {}).get(reviewer, {}))
            validate_reviews_for_assignment(allowed, payload.get("reviews", []))
            state_obj.setdefault("reviews", {})[reviewer] = {
                "student": student,
                "reviews": payload.get("reviews", []),
                "archive": archive.name,
                "received_at": datetime.now(UTC).isoformat(),
            }
            append_audit(state_obj, "stage2.reviews.uploaded", archive.name)
            save(state_obj)
        except Exception as exc:
            return redirect("/stage2/reviews", error="上传审稿包失败：" + str(exc))
        return redirect("/stage2/reviews", notice=f"已导入 {reviewer} 的审稿提交包")

    @app.post("/stage2/reviews/reset")
    async def reset_stage2_reviews() -> Any:
        state_obj = state()
        _clear_teacher_downstream_from_reviews(state_obj, root)
        append_audit(state_obj, "stage2.reviews.reset", "stage2 reviews and downstream data reset")
        save(state_obj)
        return redirect("/stage2/reviews", notice="Stage 2 收审稿包已重置")

    @app.get("/stage2/reviews/{student_number}", response_class=HTMLResponse)
    def stage2_review_detail(request: Request, student_number: str) -> Any:
        state_obj = state()
        row = state_obj.get("reviews", {}).get(student_number)
        if not row:
            return redirect("/stage2/reviews", error="未找到该学生的 Stage 2 审稿包")
        return templates.TemplateResponse(
            request,
            "teacher/package_detail.html",
            _package_detail_context(
                request,
                "stage2_reviews",
                "Stage 2 审稿包详情",
                "/stage2/reviews",
                student_number,
                row,
                [("审稿数", len(row.get("reviews", [])))],
                state_obj,
            ),
        )

    @app.post("/stage2/reviews/{student_number}/delete")
    async def delete_stage2_review(student_number: str) -> Any:
        state_obj = state()
        row = state_obj.setdefault("reviews", {}).pop(student_number, None)
        if not row:
            return redirect("/stage2/reviews", error="未找到该学生的 Stage 2 审稿包")
        _remove_received_archive(
            root,
            row.get("archive", ""),
            upload_dir="stage2-review-assignment/imported-reviews",
        )
        _clear_teacher_downstream_from_feedback(state_obj, root)
        append_audit(state_obj, "stage2.review.deleted", student_number)
        save(state_obj)
        return redirect("/stage2/reviews", notice=f"已删除 {student_number} 的 Stage 2 审稿包")

    @app.get("/stage3/feedback", response_class=HTMLResponse)
    def stage3_feedback_page(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "teacher/stage3_feedback.html",
            _context(request, "stage3_feedback", state()),
        )

    @app.post("/stage3/feedback")
    async def generate_feedback() -> Any:
        state_obj = state()
        try:
            _clear_teacher_downstream_from_feedback(state_obj, root)
            bundle, _, _ = build_review_feedback_packages(root, state_obj)
            append_audit(state_obj, "stage3.feedback.generated", bundle.name)
            save(state_obj)
        except Exception as exc:
            return redirect("/stage3/feedback", error="生成修订反馈包失败：" + str(exc))
        return redirect("/stage3/feedback", notice="修订反馈包已生成", download=bundle.name)

    @app.post("/stage3/feedback/reset")
    async def reset_stage3_feedback() -> Any:
        state_obj = state()
        _clear_teacher_downstream_from_feedback(state_obj, root)
        append_audit(state_obj, "stage3.feedback.reset", "stage3 feedback and downstream data reset")
        save(state_obj)
        return redirect("/stage3/feedback", notice="Stage 3 发修订反馈已重置")

    @app.get("/stage3/revisions", response_class=HTMLResponse)
    def stage3_revisions_page(request: Request) -> Any:
        return templates.TemplateResponse(
            request,
            "teacher/stage3_revisions.html",
            _context(request, "stage3_revisions", state()),
        )

    @app.post("/stage3/revisions/upload")
    async def upload_revision(file: UploadFile = File(...)) -> Any:
        state_obj = state()
        try:
            archive = save_upload(file, root / "stage3-revisions/uploads")
            manifest, payload = read_package(archive, root / "stage3-revisions/imports" / archive.stem)
            _assert_manifest(manifest, ROLE_STUDENT, STAGE3, KIND_REVISION)
            assert_student_package_version_allowed(manifest, state_obj.get("settings", {}))
            student = payload.get("student", {})
            student_number = student.get("student_number", "")
            assert_student_archive(archive, student_number, STAGE3, KIND_REVISION)
            feedback = state_obj.get("feedback", {}).get(student_number)
            if not feedback:
                raise PackageError("student has no Stage 3 feedback package")
            validate_stage1_problem_package(payload.get("problems", []))
            validate_responses_for_feedback(
                {item.get("review_id", "") for item in feedback.get("reviews", [])},
                payload.get("responses", []),
            )
            state_obj.setdefault("revisions", {})[student_number] = {
                "student": student,
                "problems": payload.get("problems", []),
                "responses": payload.get("responses", []),
                "archive": archive.name,
                "received_at": datetime.now(UTC).isoformat(),
            }
            append_audit(state_obj, "stage3.revision.uploaded", archive.name)
            save(state_obj)
        except Exception as exc:
            return redirect("/stage3/revisions", error="上传修订包失败：" + str(exc))
        return redirect("/stage3/revisions", notice=f"已导入 {student_number} 的修订提交包")

    @app.post("/stage3/revisions/reset")
    async def reset_stage3_revisions() -> Any:
        state_obj = state()
        _clear_teacher_downstream_from_revisions(state_obj, root)
        append_audit(state_obj, "stage3.revisions.reset", "stage3 revisions and downstream data reset")
        save(state_obj)
        return redirect("/stage3/revisions", notice="Stage 3 收修订包已重置")

    @app.get("/stage3/revisions/{student_number}", response_class=HTMLResponse)
    def stage3_revision_detail(request: Request, student_number: str) -> Any:
        state_obj = state()
        row = state_obj.get("revisions", {}).get(student_number)
        if not row:
            return redirect("/stage3/revisions", error="未找到该学生的 Stage 3 修订包")
        return templates.TemplateResponse(
            request,
            "teacher/package_detail.html",
            _package_detail_context(
                request,
                "stage3_revisions",
                "Stage 3 修订包详情",
                "/stage3/revisions",
                student_number,
                row,
                [
                    ("题目数", len(row.get("problems", []))),
                    ("回应数", len(row.get("responses", []))),
                ],
                state_obj,
            ),
        )

    @app.post("/stage3/revisions/{student_number}/delete")
    async def delete_stage3_revision(student_number: str) -> Any:
        state_obj = state()
        row = state_obj.setdefault("revisions", {}).pop(student_number, None)
        if not row:
            return redirect("/stage3/revisions", error="未找到该学生的 Stage 3 修订包")
        _remove_received_archive(
            root,
            row.get("archive", ""),
            upload_dir="stage3-revisions/uploads",
            import_dir="stage3-revisions/imports",
        )
        _clear_teacher_eval_outputs(state_obj, root)
        append_audit(state_obj, "stage3.revision.deleted", student_number)
        save(state_obj)
        return redirect("/stage3/revisions", notice=f"已删除 {student_number} 的 Stage 3 修订包")

    @app.get("/eval", response_class=HTMLResponse)
    def eval_page(request: Request) -> Any:
        state_obj = state()
        page_state = _state_with_runtime_settings(state_obj, root)
        settings_models = list(page_state.get("settings", {}).get("models") or [])
        display_models = eval_display_models(state_obj)
        save(state_obj)
        return templates.TemplateResponse(
            request,
            "teacher/eval.html",
            {
                **_context(request, "eval", page_state),
                "settings_models": settings_models,
                "executed_models": eval_executed_models(state_obj),
                "display_models": display_models,
                "eval_rows": eval_problem_rows(state_obj),
                "eval_results": _eval_result_map(state_obj, display_models),
                "active_job": _latest_eval_job(state_obj),
            },
        )

    @app.post("/eval/run")
    async def run_official_eval(
        model: str = Form(""),
        mode: str = Form("cache_first"),
    ) -> Any:
        state_obj = state()
        try:
            selected_model = model.strip() or _effective_settings(state_obj, root)["models"][0]
            summary = run_official_eval_for_model(state_obj, root, selected_model, mode=mode)
            output = write_official_eval_package(root, state_obj)
            append_audit(state_obj, "stage4.official_eval.run", output.name)
            save(state_obj)
        except Exception as exc:
            return redirect("/eval", error="正式评测失败：" + str(exc))
        return redirect(
            "/eval",
            notice=f"助教正式评测已完成：新增 {summary['completed']}，跳过 {summary['skipped']}，失败 {summary['failed']}",
            download=output.name,
        )

    @app.post("/eval/jobs")
    async def start_eval_job(model: str = Form(...), mode: str = Form("cache_first")) -> Any:
        state_obj = state()
        try:
            job = create_eval_job(state_obj, model.strip(), mode, root)
            save(state_obj)
        except Exception as exc:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)

        def worker() -> None:
            worker_state = state()
            run_eval_job(worker_state, root, job["job_id"])
            append_audit(worker_state, "stage4.official_eval.job", job["job_id"])
            save(worker_state)

        threading.Thread(target=worker, daemon=True).start()
        return JSONResponse({"ok": True, "job_id": job["job_id"], "status": job["status"]})

    @app.get("/eval/jobs/{job_id}")
    async def eval_job_progress(job_id: str) -> Any:
        job = state().get("eval_jobs", {}).get(job_id)
        if not job:
            return JSONResponse({"ok": False, "message": "正式评测任务不存在"}, status_code=404)
        return JSONResponse({"ok": True, **job})

    @app.post("/eval/display-models/add")
    async def add_display_model(model: str = Form(...)) -> Any:
        state_obj = state()
        try:
            display_models = add_eval_display_model(state_obj, model)
            save(state_obj)
        except Exception as exc:
            return JSONResponse({"ok": False, "message": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "display_models": display_models})

    @app.post("/eval/display-models/remove")
    async def remove_display_model(model: str = Form(...)) -> Any:
        state_obj = state()
        display_models = remove_eval_display_model(state_obj, model)
        save(state_obj)
        return JSONResponse({"ok": True, "display_models": display_models})

    @app.get("/eval/problems/{student_number}/{problem_id}", response_class=HTMLResponse)
    def eval_problem_detail(request: Request, student_number: str, problem_id: str) -> Any:
        state_obj = state()
        model = request.query_params.get("model", "")
        return templates.TemplateResponse(
            request,
            "teacher/eval_detail.html",
            {
                **_context(request, "eval", state_obj),
                "detail": _eval_detail_context(state_obj, student_number, problem_id, model),
            },
        )

    @app.post("/eval/problems/{student_number}/{problem_id}/select-run")
    async def select_eval_run(
        student_number: str,
        problem_id: str,
        model: str = Form(...),
        run_id: str = Form(""),
    ) -> Any:
        state_obj = state()
        try:
            if run_id:
                set_eval_run_selection(state_obj, student_number, problem_id, model, run_id)
            else:
                clear_eval_run_selection(state_obj, student_number, problem_id, model)
            save(state_obj)
        except Exception as exc:
            return redirect(
                f"/eval/problems/{student_number}/{problem_id}?model={model}",
                error="选择正式评测记录失败：" + str(exc),
            )
        return redirect(
            f"/eval/problems/{student_number}/{problem_id}?model={model}",
            notice="正式评测展示记录已更新",
        )

    @app.post("/eval/reset")
    async def reset_eval() -> Any:
        state_obj = state()
        state_obj["eval_runs"] = []
        state_obj["eval_display_models"] = []
        state_obj["eval_run_selections"] = {}
        state_obj["eval_jobs"] = {}
        clear_relative_dirs(root, ["ta-eval/runs"])
        append_audit(state_obj, "stage4.eval.reset", "official eval reset")
        save(state_obj)
        return redirect("/eval", notice="正式评测已重置")

    @app.get("/stats", response_class=HTMLResponse)
    def stats_page(request: Request) -> Any:
        state_obj = state()
        return templates.TemplateResponse(
            request,
            "teacher/stats.html",
            {
                **_context(request, "stats", state_obj),
                "stats": _stats(state_obj),
            },
        )

    @app.post("/stats/export")
    async def export_stats() -> Any:
        state_obj = state()
        output = root / "stats/exports" / teacher_bulk_name(STAGE4, KIND_COURSE_STATS)
        write_json(output, _stats(state_obj))
        state_obj.setdefault("downloads", []).append(output.name)
        append_audit(state_obj, "stage4.stats.exported", output.name)
        save(state_obj)
        return redirect("/stats", notice="课程统计已导出", download=output.name)

    @app.post("/stats/reset")
    async def reset_stats() -> Any:
        state_obj = state()
        clear_relative_dirs(root, ["stats/exports"])
        append_audit(state_obj, "stage4.stats.reset", "stats exports reset")
        save(state_obj)
        return redirect("/stats", notice="课程统计导出已重置")

    @app.get("/audit", response_class=HTMLResponse)
    def audit_page(request: Request) -> Any:
        return templates.TemplateResponse(
            request, "teacher/audit.html", _context(request, "audit", state())
        )

    @app.post("/audit/reset")
    async def reset_audit() -> Any:
        state_obj = state()
        state_obj["audit"] = []
        clear_relative_dirs(root, ["audit"])
        save(state_obj)
        return redirect("/audit", notice="审计记录已重置")

    @app.get("/downloads/{filename}")
    def download(filename: str) -> Any:
        path = find_download(
            root,
            filename,
            [
                "stage2-review-assignment/review-packages",
                "stage3-revisions/feedback-packages",
                "ta-eval/runs",
                "stats/exports",
                "stage1-submissions/exports",
            ],
        )
        if path is None:
            return redirect("/stage1", error="下载文件不存在")
        return FileResponse(path, filename=path.name)

    return app


def _context(request: Request, active: str, state: dict[str, Any]) -> dict[str, Any]:
    return {
        "request": request,
        "active": active,
        "state": state,
        "notice": request.query_params.get("notice", ""),
        "error": request.query_params.get("error", ""),
        "download": request.query_params.get("download", ""),
    }


def _package_detail_context(
    request: Request,
    active: str,
    title: str,
    back_url: str,
    student_number: str,
    row: dict[str, Any],
    counts: list[tuple[str, int]],
    state: dict[str, Any],
) -> dict[str, Any]:
    student = row.get("student", {})
    anonymous_problems = _anonymous_problem_lookup(state)
    anonymous_users = _anonymous_user_lookup(state)
    return {
        **_context(request, active, {}),
        "detail": {
            "title": title,
            "kind": active,
            "back_url": back_url,
            "student_number": student_number,
            "student": student,
            "archive": row.get("archive", ""),
            "received_at": row.get("received_at", ""),
            "counts": counts,
            "payload": row,
            "problems": row.get("problems", []),
            "reviews": _review_detail_rows(row, state, anonymous_problems, anonymous_users),
            "responses": _response_detail_rows(row, state),
        },
    }


def _anonymous_problem_lookup(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item.get("anonymous_problem_id", ""): item
        for item in state.get("stage2_assignment_manifest", {}).get("anonymous_problem_map", [])
    }


def _anonymous_user_lookup(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item.get("anonymous_user_id", ""): item
        for item in state.get("stage2_assignment_manifest", {}).get("anonymous_user_map", [])
    }


def _review_detail_rows(
    row: dict[str, Any],
    state: dict[str, Any],
    anonymous_problems: dict[str, dict[str, Any]],
    anonymous_users: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    reviewer = row.get("student", {}).get("student_number", "")
    assignments = state.get("assignments", {}).get(reviewer, {})
    rows = []
    for review in row.get("reviews", []):
        anon_id = review.get("anonymous_id", "")
        mapping = assignments.get(anon_id, {})
        problem_map = anonymous_problems.get(mapping.get("anonymous_problem_id", anon_id), {})
        author_anon = mapping.get("anonymous_author_id", problem_map.get("anonymous_author_id", ""))
        rows.append(
            {
                "review": review,
                "anonymous_problem_id": mapping.get("anonymous_problem_id", anon_id),
                "real_problem_id": mapping.get("problem_id", problem_map.get("real_problem_id", "")),
                "anonymous_author_id": author_anon,
                "real_author_id": mapping.get(
                    "author_student_number", problem_map.get("author_student_number", "")
                ),
                "anonymous_author": anonymous_users.get(author_anon, {}),
            }
        )
    return rows


def _response_detail_rows(row: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    student_number = row.get("student", {}).get("student_number", "")
    feedback_reviews = {
        item.get("review_id"): item for item in state.get("feedback", {}).get(student_number, {}).get("reviews", [])
    }
    rows = []
    for response in row.get("responses", []):
        review = feedback_reviews.get(response.get("review_id"), {})
        rows.append({"response": response, "review": review})
    return rows


def _eval_result_map(state: dict[str, Any], display_models: list[str]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for row in eval_problem_rows(state):
        key = f"{row['student_number']}:{row['problem_id']}"
        results[key] = {}
        for model in display_models:
            results[key][model] = eval_result_for_model(
                state, row["student_number"], row["problem_id"], model
            )
    return results


def _latest_eval_job(state: dict[str, Any]) -> dict[str, Any] | None:
    jobs = list(state.get("eval_jobs", {}).values())
    if not jobs:
        return None
    return sorted(jobs, key=lambda item: str(item.get("started_at", "")), reverse=True)[0]


def _eval_detail_context(
    state: dict[str, Any], student_number: str, problem_id: str, selected_model: str
) -> dict[str, Any]:
    subject = next(
        (
            item
            for item in eval_subjects(state)
            if item["student_number"] == student_number and item["problem_id"] == problem_id
        ),
        None,
    )
    if subject is None:
        raise ValueError("题目不存在")
    feedback_reviews = [
        item
        for item in state.get("feedback", {}).get(student_number, {}).get("reviews", [])
        if item.get("problem_id") == problem_id
    ]
    responses = {
        item.get("review_id"): item
        for item in state.get("revisions", {}).get(student_number, {}).get("responses", [])
    }
    models = eval_executed_models(state)
    model_runs = {}
    for model in models:
        runs = [
            run
            for run in state.get("eval_runs", [])
            if run.get("student_number") == student_number
            and run.get("problem_id") == problem_id
            and run.get("model") == model
        ]
        model_runs[model] = {
            "runs": sorted(runs, key=lambda item: str(item.get("created_at", "")), reverse=True),
            "selected": eval_result_for_model(state, student_number, problem_id, model),
        }
    return {
        "student_number": student_number,
        "problem_id": problem_id,
        "selected_model": selected_model,
        "subject": subject,
        "original_problem": subject.get("original_problem"),
        "problem": subject["problem"],
        "reviews": feedback_reviews,
        "responses": responses,
        "model_runs": model_runs,
    }


def _clear_teacher_downstream_from_stage2(state: dict[str, Any], root: Path) -> None:
    state["assignments"] = {}
    state["stage2_assignment_manifest"] = {}
    _clear_teacher_downstream_from_reviews(state, root)
    clear_relative_dirs(
        root,
        [
            "stage2-review-assignment/anonymous-corpus",
            "stage2-review-assignment/assignments",
            "stage2-review-assignment/review-packages",
        ],
    )


def _clear_teacher_downstream_from_reviews(state: dict[str, Any], root: Path) -> None:
    state["reviews"] = {}
    _clear_teacher_downstream_from_feedback(state, root)
    clear_relative_dirs(root, ["stage2-review-assignment/imported-reviews"])


def _clear_teacher_downstream_from_feedback(state: dict[str, Any], root: Path) -> None:
    state["feedback"] = {}
    state["stage3_feedback_manifest"] = {}
    _clear_teacher_downstream_from_revisions(state, root)
    clear_relative_dirs(root, ["stage3-revisions/feedback-packages"])


def _clear_teacher_downstream_from_revisions(state: dict[str, Any], root: Path) -> None:
    state["revisions"] = {}
    _clear_teacher_eval_outputs(state, root)
    clear_relative_dirs(
        root,
        [
            "stage3-revisions/uploads",
            "stage3-revisions/imports",
            "stage3-revisions/author-responses",
        ],
    )


def _clear_teacher_eval_outputs(state: dict[str, Any], root: Path) -> None:
    state["eval_runs"] = []
    state["eval_display_models"] = []
    state["eval_run_selections"] = {}
    state["eval_manual_scores"] = {}
    state["eval_jobs"] = {}
    clear_relative_dirs(root, ["ta-eval/runs", "stats/exports"])


def _remove_received_archive(
    root: Path,
    archive_name: str,
    *,
    upload_dir: str,
    import_dir: str | None = None,
) -> None:
    if not archive_name:
        return
    archive_path = Path(archive_name)
    remove_file(root / upload_dir / archive_path.name)
    if import_dir:
        import_name = (
            archive_path.name[: -len(".tar.gz")]
            if archive_path.name.endswith(".tar.gz")
            else archive_path.stem
        )
        shutil.rmtree(root / import_dir / import_name, ignore_errors=True)


def _write_stage1_status_xlsx(output: Path, rows: list[dict[str, Any]]) -> None:
    try:
        from openpyxl import Workbook
    except ImportError as exc:  # pragma: no cover - exercised only in broken environments.
        raise RuntimeError("导出阶段1导出表.xlsx 需要安装 openpyxl") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "学生导入状态"
    sheet.append(["学号", "姓名", "班级", "导入情况", "校验情况", "包名"])
    for row in rows:
        sheet.append(
            [
                row.get("student_number", ""),
                row.get("name", ""),
                row.get("class_id", ""),
                "已导入" if row.get("imported") else "未导入",
                "校验通过" if row.get("validation_ok") else row.get("validation_detail", "未导入"),
                row.get("archive", ""),
            ]
        )
    workbook.save(output)


def _assert_manifest(manifest: dict[str, Any], role: str, stage: str, kind: str) -> None:
    if manifest.get("package_role") != role:
        raise PackageError("manifest package_role 不匹配")
    if manifest.get("package_stage") != stage:
        raise PackageError("manifest package_stage 不匹配")
    if manifest.get("package_kind") != kind:
        raise PackageError("manifest package_kind 不匹配")


def _stats(state: dict[str, Any]) -> dict[str, Any]:
    submissions = state.get("submissions", {})
    reviews = state.get("reviews", {})
    revisions = state.get("revisions", {})
    eval_runs = state.get("eval_runs", [])
    return {
        "schema_version": "codesetarena.course_stats.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "stage1_submissions": len(submissions),
        "stage2_review_packages": len(reviews),
        "stage3_revisions": len(revisions),
        "ta_official_eval_runs": len(eval_runs),
        "review_completion_rate": _safe_rate(len(reviews), len(submissions)),
        "revision_completion_rate": _safe_rate(len(revisions), len(submissions)),
    }


def _ai_reviewer_student() -> dict[str, str]:
    return {
        "student_number": AI_REVIEWER_STUDENT_NUMBER,
        "name": AI_REVIEWER_NAME,
        "class_id": AI_REVIEWER_CLASS_ID,
    }


def _review_assignment_problem(problem: dict[str, Any]) -> dict[str, Any]:
    selected_runs = [run for run in problem.get("run_records", []) if run.get("package_selected")]
    return {
        "title": problem.get("title", ""),
        "statement": problem.get("statement", ""),
        "signature": problem.get("signature", ""),
        "reference_solution": problem.get("reference_solution", ""),
        "public_tests": problem.get("public_tests", []),
        "author_tests": problem.get("author_tests", []),
        "notes": problem.get("notes", ""),
        "failure_hypothesis": problem.get("failure_hypothesis", ""),
        "run_analysis": problem.get("run_analysis", ""),
        "run_records": selected_runs or problem.get("run_records", []),
    }


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _effective_settings(state: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    runtime = load_runtime_config(root)
    settings = state.get("settings", {})
    base_url = str(settings.get("base_url") or "").strip()
    models = list(settings.get("models") or [])
    configured = settings_are_configured(settings) and runtime.api_key_set
    return {
        "configured": configured,
        "course_name": settings.get("course_name") or "CodeSetArena v7",
        "base_url": base_url,
        "api_key_set": runtime.api_key_set,
        "api_key_source": runtime.api_key_source,
        "api_key_display": MASKED_API_KEY if runtime.api_key_set else "",
        "models": models,
        "random_seed": parse_random_seed(settings.get("random_seed", DEFAULT_RANDOM_SEED)),
        "allowed_student_versions": allowed_student_versions_from_settings(settings),
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
            return parsed
    return _parse_models(str(form.get("models", "")))


def _test_io_filter(test: Any) -> dict[str, str]:
    try:
        payload = json.loads(test) if isinstance(test, str) else test
    except (TypeError, ValueError):
        return {"input": str(test), "output": ""}
    if not isinstance(payload, dict):
        return {"input": json.dumps(payload, ensure_ascii=False), "output": ""}
    kwargs = payload.get("input", {}).get("kwargs", payload.get("kwargs", {}))
    expected = payload.get("expected", "")
    return {
        "input": json.dumps(kwargs, ensure_ascii=False, separators=(",", ":")),
        "output": json.dumps(expected, ensure_ascii=False, separators=(",", ":")),
    }
