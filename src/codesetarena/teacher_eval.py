"""Teacher-side official evaluation workflow helpers."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from .config import RuntimeConfig, load_runtime_config, settings_are_configured
from .constants import (
    KIND_OFFICIAL_EVAL,
    MODEL_RUN_TEMPERATURE,
    MODEL_RUN_TOP_P,
    ROLE_TEACHER,
    RUN_ORIGIN_STUDENT_SELF_TEST,
    RUN_ORIGIN_TA_OFFICIAL_EVAL,
    STAGE4,
)
from .model_client import real_completion
from .model_run_utils import execute_model_code, extract_function_code
from .package_names import teacher_bulk_name
from .packages import write_package
from .prompting import prompt_template_id
from .student_app import (
    _official_prompt_for_problem,
    _official_prompt_parts_for_problem,
    _problem_signature_hash,
    _run_record_has_raw_evidence,
    _run_record_matches_current_prompt,
)
from .versioning import snapshot_version


EVAL_MODE_CACHE_FIRST = "cache_first"
EVAL_MODE_FORCE = "force"
EVAL_MODES = {EVAL_MODE_CACHE_FIRST, EVAL_MODE_FORCE}


def eval_executed_models(state: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(run.get("model", "")).strip()
            for run in state.get("eval_runs", [])
            if run.get("run_origin") == RUN_ORIGIN_TA_OFFICIAL_EVAL and str(run.get("model", "")).strip()
        }
    )


def normalize_eval_mode(mode: str) -> str:
    normalized = (mode or EVAL_MODE_CACHE_FIRST).strip().replace("-", "_")
    if normalized not in EVAL_MODES:
        raise ValueError("执行模式必须是 cache_first 或 force")
    return normalized


def add_eval_display_model(state: dict[str, Any], model: str) -> list[str]:
    model = model.strip()
    if model not in eval_executed_models(state):
        raise ValueError(f"{model} 尚未执行正式评测，不能加入展示列表")
    display_models = [
        item for item in state.setdefault("eval_display_models", []) if item in eval_executed_models(state)
    ]
    if model not in display_models:
        display_models.append(model)
    state["eval_display_models"] = display_models
    return display_models


def remove_eval_display_model(state: dict[str, Any], model: str) -> list[str]:
    model = model.strip()
    state["eval_display_models"] = [
        item for item in state.setdefault("eval_display_models", []) if item != model
    ]
    return state["eval_display_models"]


def eval_display_models(state: dict[str, Any]) -> list[str]:
    executed = set(eval_executed_models(state))
    selected = [model for model in state.get("eval_display_models", []) if model in executed]
    if selected:
        state["eval_display_models"] = selected
        return selected
    defaults = eval_executed_models(state)[:2]
    state["eval_display_models"] = defaults
    return defaults


def eval_problem_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    subjects = eval_subjects(state)
    counts_by_student = _student_row_counts(subjects)
    seen_students: set[str] = set()
    for subject in subjects:
        student_number = subject["student_number"]
        problem_id = subject["problem_id"]
        quality_scores = _quality_scores_for_problem(state, student_number, problem_id)
        author_ratings = _author_ratings_for_problem(state, student_number, problem_id)
        self_nonpass, self_legal = _self_test_counts(subject["problem"])
        missing_reasons = []
        if not subject["has_revision"]:
            missing_reasons.append("缺少修订题")
        if not quality_scores:
            missing_reasons.append("审稿质量评分缺失")
        if not author_ratings:
            missing_reasons.append("作者评分缺失")
        row = {
            **subject,
            "student_rowspan": counts_by_student[student_number] if student_number not in seen_students else 0,
            "self_test_summary": f"{self_nonpass}/{self_legal}",
            "self_test_nonpass": self_nonpass,
            "self_test_legal": self_legal,
            "quality_scores": quality_scores,
            "quality_scores_text": _score_text(quality_scores),
            "quality_average": _average(quality_scores),
            "author_ratings": author_ratings,
            "author_rating_average": _average(author_ratings),
            "author_rating_text": _score_text(author_ratings),
            "missing_reasons": missing_reasons,
            "has_missing": bool(missing_reasons),
        }
        rows.append(row)
        seen_students.add(student_number)
    return rows


def eval_subjects(state: dict[str, Any]) -> list[dict[str, Any]]:
    subjects = []
    submissions = state.get("submissions", {})
    revisions = state.get("revisions", {})
    for student_number in sorted(submissions):
        submission = submissions[student_number]
        student = submission.get("student", {})
        original_by_id = {problem.get("problem_id", ""): problem for problem in submission.get("problems", [])}
        revised = revisions.get(student_number, {})
        source_problems = revised.get("problems") or submission.get("problems", [])
        for index, problem in enumerate(source_problems):
            problem_id = str(problem.get("problem_id", ""))
            subjects.append(
                {
                    "student_number": student_number,
                    "student": student,
                    "name": student.get("name", ""),
                    "class_id": student.get("class_id", ""),
                    "problem_id": problem_id,
                    "problem_index": index,
                    "title": problem.get("title") or _title_from_statement(problem),
                    "problem": problem,
                    "original_problem": original_by_id.get(problem_id),
                    "has_revision": bool(revised.get("problems")),
                }
            )
    return subjects


def eval_result_for_model(
    state: dict[str, Any], student_number: str, problem_id: str, model: str
) -> dict[str, Any]:
    subject = _require_subject(state, student_number, problem_id)
    legal_runs = _legal_eval_runs_for_model(state, subject["problem"], student_number, problem_id, model)
    selected_run_id = (
        state.get("eval_run_selections", {}).get(_problem_key(student_number, problem_id), {}).get(model)
    )
    selected_run = next((run for run in legal_runs if run.get("run_id") == selected_run_id), None)
    if selected_run is not None:
        return {"run": selected_run, "selection_source": "manual", "missing": False, "invalid_manual_selection": False}
    latest = legal_runs[0] if legal_runs else None
    return {
        "run": latest,
        "selection_source": "latest" if latest else "missing",
        "missing": latest is None,
        "invalid_manual_selection": bool(selected_run_id and latest),
    }


def set_eval_run_selection(
    state: dict[str, Any], student_number: str, problem_id: str, model: str, run_id: str
) -> None:
    subject = _require_subject(state, student_number, problem_id)
    legal_run_ids = {
        run.get("run_id")
        for run in _legal_eval_runs_for_model(state, subject["problem"], student_number, problem_id, model)
    }
    if run_id not in legal_run_ids:
        raise ValueError("只能选择该题该模型的合法正式评测记录")
    state.setdefault("eval_run_selections", {}).setdefault(_problem_key(student_number, problem_id), {})[
        model
    ] = run_id


def clear_eval_run_selection(state: dict[str, Any], student_number: str, problem_id: str, model: str) -> None:
    selections = state.setdefault("eval_run_selections", {}).get(_problem_key(student_number, problem_id), {})
    selections.pop(model, None)


def create_eval_job(state: dict[str, Any], model: str, mode: str, root: Path | None = None) -> dict[str, Any]:
    mode = normalize_eval_mode(mode)
    _validate_model_from_settings(state, model, root)
    if _active_eval_job(state):
        raise ValueError("已有正式评测任务正在执行，请等待完成后再启动")
    job = {
        "job_id": "eval_job_" + uuid.uuid4().hex[:12],
        "status": "pending",
        "model": model,
        "mode": mode,
        "total": len(eval_subjects(state)),
        "completed": 0,
        "skipped": 0,
        "failed": 0,
        "current_student_number": "",
        "current_problem_id": "",
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": "",
        "elapsed_seconds": 0.0,
        "eta_seconds": None,
        "last_error": "",
    }
    state.setdefault("eval_jobs", {})[job["job_id"]] = job
    return job


def run_eval_job(state: dict[str, Any], root: Path, job_id: str) -> dict[str, Any]:
    job = state.setdefault("eval_jobs", {}).get(job_id)
    if not job:
        raise ValueError("正式评测任务不存在")
    try:
        summary = run_official_eval_for_model(
            state,
            root,
            job["model"],
            mode=job["mode"],
            job=job,
        )
        job.update(summary)
        job["status"] = "completed"
    except Exception as exc:
        job["status"] = "failed"
        job["last_error"] = str(exc)
    finally:
        job["finished_at"] = datetime.now(UTC).isoformat()
        _update_job_timing(job, monotonic())
    return job


def run_official_eval_for_model(
    state: dict[str, Any],
    root: Path,
    model: str,
    *,
    mode: str = EVAL_MODE_CACHE_FIRST,
    job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mode = normalize_eval_mode(mode)
    _validate_model_from_settings(state, model, root)
    subjects = eval_subjects(state)
    if not subjects:
        raise ValueError("没有可评测的题目包")
    started = monotonic()
    completed = skipped = failed = 0
    if job is not None:
        job["status"] = "running"
        job["total"] = len(subjects)
    for index, subject in enumerate(subjects, start=1):
        if job is not None:
            job["current_student_number"] = subject["student_number"]
            job["current_problem_id"] = subject["problem_id"]
        if mode == EVAL_MODE_CACHE_FIRST and eval_result_for_model(
            state, subject["student_number"], subject["problem_id"], model
        )["run"]:
            skipped += 1
        else:
            try:
                state.setdefault("eval_runs", []).append(
                    _build_official_eval_run(state, root, subject, model)
                )
                completed += 1
            except Exception as exc:
                failed += 1
                if job is not None:
                    job["last_error"] = f"{subject['student_number']} {subject['problem_id']}: {exc}"
        if job is not None:
            job.update({"completed": completed, "skipped": skipped, "failed": failed})
            _update_job_timing(job, started, processed=index)
    if model not in state.setdefault("eval_display_models", []):
        state["eval_display_models"].append(model)
    summary = {
        "status": "completed" if failed == 0 else "failed",
        "model": model,
        "mode": mode,
        "total": len(subjects),
        "completed": completed,
        "skipped": skipped,
        "failed": failed,
        "elapsed_seconds": round(monotonic() - started, 3),
    }
    write_official_eval_package(root, state)
    return summary


def write_official_eval_package(root: Path, state: dict[str, Any]) -> Path:
    output = root / "ta-eval/runs" / teacher_bulk_name(STAGE4, KIND_OFFICIAL_EVAL)
    write_package(
        output,
        role=ROLE_TEACHER,
        stage=STAGE4,
        kind=KIND_OFFICIAL_EVAL,
        payload={
            "eval_runs": state.get("eval_runs", []),
            "eval_display_models": state.get("eval_display_models", []),
            "eval_run_selections": state.get("eval_run_selections", {}),
        },
    )
    return output


def _build_official_eval_run(
    state: dict[str, Any], root: Path, subject: dict[str, Any], model: str
) -> dict[str, Any]:
    problem = subject["problem"]
    prompt = _official_prompt_for_problem(problem)
    prompt_parts = _official_prompt_parts_for_problem(problem)
    run_id = "ta_" + uuid.uuid4().hex[:12]
    created_at = datetime.now(UTC).isoformat()
    runtime = load_runtime_config(root)
    models = _effective_models(state, root)
    model_config = RuntimeConfig(
        base_url=_effective_base_url(state, root),
        api_key=runtime.api_key,
        models=models,
        env_file=runtime.env_file,
    )
    completion = real_completion(config=model_config, model=model, prompt=prompt)
    raw_response = completion.content
    extracted_code = extract_function_code(raw_response, str(problem.get("signature", "")))
    result = execute_model_code(problem, extracted_code)
    return {
        "run_id": run_id,
        "run_origin": RUN_ORIGIN_TA_OFFICIAL_EVAL,
        "student_number": subject["student_number"],
        "problem_id": subject["problem_id"],
        "model": model,
        "base_url": model_config.base_url,
        "prompt_template_id": prompt_template_id(),
        "prompt": prompt,
        "prompt_parts": prompt_parts,
        "content_hash": _problem_signature_hash(problem),
        "snapshot_version": snapshot_version(),
        "temperature": MODEL_RUN_TEMPERATURE,
        "top_p": MODEL_RUN_TOP_P,
        "verdict": result["verdict"],
        "created_at": created_at,
        "api_request_raw": completion.request_raw,
        "api_response_raw": completion.response_raw,
        "raw_response": raw_response,
        "extracted_code": extracted_code,
        "test_results": result["test_results"],
    }


def _legal_eval_runs_for_model(
    state: dict[str, Any],
    problem: dict[str, Any],
    student_number: str,
    problem_id: str,
    model: str,
) -> list[dict[str, Any]]:
    runs = [
        run
        for run in state.get("eval_runs", [])
        if run.get("run_origin") == RUN_ORIGIN_TA_OFFICIAL_EVAL
        and run.get("student_number") == student_number
        and run.get("problem_id") == problem_id
        and run.get("model") == model
        and _eval_run_is_legal(problem, run)
    ]
    return sorted(runs, key=lambda item: str(item.get("created_at", "")), reverse=True)


def _eval_run_is_legal(problem: dict[str, Any], run: dict[str, Any]) -> bool:
    return (
        run.get("content_hash") == _problem_signature_hash(problem)
        and run.get("snapshot_version") == snapshot_version()
        and run.get("prompt") == _official_prompt_for_problem(problem)
        and run.get("prompt_template_id") == prompt_template_id()
        and _float_equal(run.get("temperature"), MODEL_RUN_TEMPERATURE)
        and _float_equal(run.get("top_p"), MODEL_RUN_TOP_P)
        and bool(run.get("api_request_raw"))
        and bool(run.get("api_response_raw"))
        and bool(run.get("extracted_code") or run.get("raw_response"))
        and isinstance(run.get("test_results"), list)
    )


def _self_test_counts(problem: dict[str, Any]) -> tuple[int, int]:
    legal_runs = []
    for run in problem.get("run_records", []):
        if run.get("run_origin") != RUN_ORIGIN_STUDENT_SELF_TEST or not run.get("package_selected"):
            continue
        if _run_record_has_raw_evidence(run) and _run_record_matches_current_prompt(problem, run)[0]:
            legal_runs.append(run)
    nonpass = sum(1 for run in legal_runs if run.get("verdict") != "passed")
    return nonpass, len(legal_runs)


def _quality_scores_for_problem(state: dict[str, Any], student_number: str, problem_id: str) -> list[int]:
    scores = []
    for item in state.get("feedback", {}).get(student_number, {}).get("reviews", []):
        if item.get("problem_id") != problem_id:
            continue
        score = (item.get("review") or {}).get("quality_score")
        try:
            parsed = int(str(score))
        except (TypeError, ValueError):
            continue
        if 1 <= parsed <= 5:
            scores.append(parsed)
    return scores


def _author_ratings_for_problem(state: dict[str, Any], student_number: str, problem_id: str) -> list[int]:
    feedback_reviews = [
        item
        for item in state.get("feedback", {}).get(student_number, {}).get("reviews", [])
        if item.get("problem_id") == problem_id
    ]
    responses = {
        response.get("review_id"): response
        for response in state.get("revisions", {}).get(student_number, {}).get("responses", [])
    }
    ratings = []
    for item in feedback_reviews:
        review_id = item.get("review_id")
        try:
            parsed = int(str((responses.get(review_id) or {}).get("rating", "")))
        except (TypeError, ValueError):
            continue
        if 1 <= parsed <= 5:
            ratings.append(parsed)
    return ratings


def _score_text(scores: list[int]) -> str:
    if not scores:
        return "缺失"
    return "/".join(str(score) for score in scores) + f" = {_average(scores):.1f}"


def _average(scores: list[int]) -> float:
    return round(sum(scores) / len(scores), 1) if scores else 0.0


def _student_row_counts(subjects: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for subject in subjects:
        counts[subject["student_number"]] = counts.get(subject["student_number"], 0) + 1
    return counts


def _require_subject(state: dict[str, Any], student_number: str, problem_id: str) -> dict[str, Any]:
    for subject in eval_subjects(state):
        if subject["student_number"] == student_number and subject["problem_id"] == problem_id:
            return subject
    raise ValueError("题目不存在")


def _validate_model_from_settings(state: dict[str, Any], model: str, root: Path | None = None) -> None:
    models = _effective_models(state, root)
    if model not in models:
        raise ValueError("正式评测模型必须来自设置页模型列表")


def _effective_models(state: dict[str, Any], root: Path | None = None) -> list[str]:
    del root
    settings = state.get("settings", {})
    if settings_are_configured(settings):
        return list(settings.get("models") or [])
    return []


def _effective_base_url(state: dict[str, Any], root: Path | None = None) -> str:
    del root
    settings = state.get("settings", {})
    if settings_are_configured(settings):
        return str(settings.get("base_url") or "").rstrip("/")
    return ""


def _active_eval_job(state: dict[str, Any]) -> dict[str, Any] | None:
    for job in state.get("eval_jobs", {}).values():
        if job.get("status") in {"pending", "running"}:
            return job
    return None


def _update_job_timing(job: dict[str, Any], started: float, processed: int | None = None) -> None:
    elapsed = max(0.0, monotonic() - started)
    job["elapsed_seconds"] = round(elapsed, 1)
    if processed and processed > 0:
        remaining = max(0, int(job.get("total", 0)) - processed)
        job["eta_seconds"] = round((elapsed / processed) * remaining, 1)


def _float_equal(value: Any, expected: float) -> bool:
    try:
        return float(value) == expected
    except (TypeError, ValueError):
        return False


def _problem_key(student_number: str, problem_id: str) -> str:
    return f"{student_number}:{problem_id}"


def _title_from_statement(problem: dict[str, Any]) -> str:
    for line in str(problem.get("statement", "")).splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean[:60]
    return str(problem.get("problem_id", "未命名题目"))
