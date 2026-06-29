"""Deterministic demo course data for teacher-side local testing."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import RuntimeConfig, load_runtime_config
from .constants import (
    AI_REVIEWER_CLASS_ID,
    AI_REVIEWER_NAME,
    AI_REVIEWER_STUDENT_NUMBER,
    AUTHOR_TESTS_PER_PROBLEM,
    DEFAULT_BASE_URL,
    DEFAULT_MODELS,
    KIND_PROBLEMS,
    KIND_REVIEW_ASSIGNMENT,
    KIND_REVIEW_FEEDBACK,
    KIND_REVIEWS,
    KIND_REVISION,
    MODEL_RUN_TEMPERATURE,
    MODEL_RUN_TOP_P,
    PROMPT_TEMPLATE_ID,
    PUBLIC_TESTS_PER_PROBLEM,
    ROLE_STUDENT,
    ROLE_TEACHER,
    RUN_ORIGIN_STUDENT_SELF_TEST,
    STAGE1,
    STAGE2,
    STAGE3,
)
from .model_client import mock_completion
from .package_names import student_package_name, teacher_package_name
from .packages import write_package
from .paths import ensure_teacher_tree
from .prompting import render_official_prompt, render_official_prompt_parts
from .run_engine import execute_problem
from .storage import append_audit, default_teacher_state, save_teacher_state
from .teacher_eval import run_official_eval_for_model, write_official_eval_package
from .versioning import snapshot_version


def seed_demo_course(root: Path, *, force: bool = False) -> dict[str, int]:
    if root.exists() and any(root.iterdir()):
        if not force:
            raise ValueError("目标助教工作目录不为空；如需覆盖请使用 --force")
        shutil.rmtree(root)
    ensure_teacher_tree(root)
    state = default_teacher_state()
    runtime = load_runtime_config(root)
    state["settings"]["models"] = list(runtime.models or DEFAULT_MODELS)
    state["settings"]["base_url"] = runtime.base_url or DEFAULT_BASE_URL
    students = [_student(index) for index in range(1001, 1011)]
    all_problem_refs: list[tuple[str, int, dict[str, Any]]] = []

    for student in students:
        problems = []
        for problem_index in range(5):
            problem = _problem(student["student_number"], problem_index)
            problem["validation"] = _validation(problem)
            problem["run_records"] = [
                _student_run(root, state, problem, student["student_number"], problem_index)
            ]
            problem["stage1_package_selected"] = True
            problems.append(problem)
            all_problem_refs.append((student["student_number"], problem_index, problem))
        archive = student_package_name(student["student_number"], STAGE1, KIND_PROBLEMS)
        state["submissions"][student["student_number"]] = {
            "student": student,
            "problems": problems,
            "archive": archive,
            "received_at": datetime.now(UTC).isoformat(),
        }
        write_package(
            root / "stage1-submissions/uploads" / archive,
            role=ROLE_STUDENT,
            stage=STAGE1,
            kind=KIND_PROBLEMS,
            student_number=student["student_number"],
            payload={"student": student, "problems": problems},
        )

    _seed_assignments_and_reviews(root, state, students, all_problem_refs)
    _seed_feedback_and_revisions(root, state)
    for model in state["settings"]["models"][:2]:
        run_official_eval_for_model(state, root, model, mode="force")
    write_official_eval_package(root, state)
    append_audit(state, "demo.seed_course", "seeded 10 students, 50 problems, 200 reviews")
    save_teacher_state(root, state)
    return {
        "students": len(students),
        "problems": len(all_problem_refs),
        "reviews": sum(len(row["reviews"]) for row in state["reviews"].values()),
        "revision_responses": sum(len(row["responses"]) for row in state["revisions"].values()),
    }


def _seed_assignments_and_reviews(
    root: Path,
    state: dict[str, Any],
    students: list[dict[str, str]],
    all_problem_refs: list[tuple[str, int, dict[str, Any]]],
) -> None:
    ai_reviews = []
    ai_assigned = []
    state["assignments"][AI_REVIEWER_STUDENT_NUMBER] = {}
    student_numbers = [student["student_number"] for student in students]
    for author_index, (author, problem_index, problem) in enumerate(all_problem_refs):
        anon_id = f"anon_demo_AI_{author}_{problem_index}"
        ai_assigned.append(_assignment_problem(anon_id, "ai", problem))
        state["assignments"][AI_REVIEWER_STUDENT_NUMBER][anon_id] = {
            "author_student_number": author,
            "problem_id": problem["problem_id"],
            "problem_index": problem_index,
            "review_origin": "ai",
        }
        ai_reviews.append(_review(anon_id, "accept", 5, "AI 审稿：题目结构完整，建议保留边界样例。"))
        for offset in range(1, 4):
            reviewer = student_numbers[(author_index // 5 + offset) % len(student_numbers)]
            anon_id = f"anon_demo_{reviewer}_{author}_{problem_index}_{offset}"
            state.setdefault("assignments", {}).setdefault(reviewer, {})[anon_id] = {
                "author_student_number": author,
                "problem_id": problem["problem_id"],
                "problem_index": problem_index,
                "review_origin": "human",
            }
            state.setdefault("_assigned_by_reviewer", {}).setdefault(reviewer, []).append(
                _assignment_problem(anon_id, "human", problem)
            )
            state.setdefault("_reviews_by_reviewer", {}).setdefault(reviewer, []).append(
                _review(
                    anon_id,
                    ["minor", "major", "accept"][(problem_index + offset) % 3],
                    3 + ((problem_index + offset) % 3),
                    "建议补充边界说明、检查样例覆盖，并确认函数签名与参考答案一致。",
                )
            )

    _write_assignment_and_review_package(
        root,
        state,
        _ai_student(),
        AI_REVIEWER_STUDENT_NUMBER,
        ai_assigned,
        ai_reviews,
        "ai",
    )
    assigned_by_reviewer = state.pop("_assigned_by_reviewer", {})
    reviews_by_reviewer = state.pop("_reviews_by_reviewer", {})
    for student in students:
        reviewer = student["student_number"]
        _write_assignment_and_review_package(
            root,
            state,
            student,
            reviewer,
            assigned_by_reviewer.get(reviewer, []),
            reviews_by_reviewer.get(reviewer, []),
            "human",
        )


def _write_assignment_and_review_package(
    root: Path,
    state: dict[str, Any],
    student: dict[str, str],
    reviewer: str,
    assigned: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    review_origin: str,
) -> None:
    assignment_archive = teacher_package_name(reviewer, STAGE2, KIND_REVIEW_ASSIGNMENT)
    write_package(
        root / "stage2-review-assignment/review-packages" / assignment_archive,
        role=ROLE_TEACHER,
        stage=STAGE2,
        kind=KIND_REVIEW_ASSIGNMENT,
        student_number=reviewer,
        payload={
            "assignment_id": f"asg_demo_{reviewer}",
            "student": student,
            "reviews_per_problem": 4,
            "human_reviews_per_problem": 3,
            "ai_reviews_per_problem": 1,
            "review_origin": review_origin,
            "assigned_problems": assigned,
        },
    )
    review_archive = student_package_name(reviewer, STAGE2, KIND_REVIEWS)
    write_package(
        root / "stage2-review-assignment/imported-reviews" / review_archive,
        role=ROLE_STUDENT,
        stage=STAGE2,
        kind=KIND_REVIEWS,
        student_number=reviewer,
        payload={"student": student, "assignment_id": f"asg_demo_{reviewer}", "reviews": reviews},
    )
    state["reviews"][reviewer] = {
        "student": student,
        "reviews": reviews,
        "archive": review_archive,
        "received_at": datetime.now(UTC).isoformat(),
    }


def _seed_feedback_and_revisions(root: Path, state: dict[str, Any]) -> None:
    feedback_by_author: dict[str, list[dict[str, Any]]] = {}
    for reviewer, package in state["reviews"].items():
        for index, review in enumerate(package["reviews"], start=1):
            mapping = state["assignments"][reviewer][review["anonymous_id"]]
            author = mapping["author_student_number"]
            feedback_by_author.setdefault(author, []).append(
                {
                    "review_id": f"rev_demo_{reviewer}_{index}",
                    "reviewer_student_number": reviewer,
                    "problem_id": mapping["problem_id"],
                    "anonymous_id": review["anonymous_id"],
                    "review": review,
                }
            )
    for author, reviews in feedback_by_author.items():
        student = state["submissions"][author]["student"]
        feedback_archive = teacher_package_name(author, STAGE3, KIND_REVIEW_FEEDBACK)
        write_package(
            root / "stage3-revisions/feedback-packages" / feedback_archive,
            role=ROLE_TEACHER,
            stage=STAGE3,
            kind=KIND_REVIEW_FEEDBACK,
            student_number=author,
            payload={"student": student, "reviews_for_author": reviews},
        )
        state["feedback"][author] = {"archive": feedback_archive, "reviews": reviews}
        revised_problems = []
        for problem in state["submissions"][author]["problems"]:
            revised = {**problem}
            revised["statement"] = problem["statement"] + "\n\n修订说明：已根据审稿意见补充边界条件。"
            revised["validation"] = _validation(revised)
            revised["run_records"] = [_student_run(root, state, revised, author, int(problem["problem_id"].split("_")[-1]))]
            revised["stage1_package_selected"] = True
            revised_problems.append(revised)
        responses = [
            {
                "review_id": item["review_id"],
                "rating": str(5 if (item["review"] or {}).get("conclusion") in {"accept", "minor"} else 4),
                "response": "已参考该审稿意见修订题面、样例或隐藏测试。",
            }
            for item in reviews
        ]
        revision_archive = student_package_name(author, STAGE3, KIND_REVISION)
        write_package(
            root / "stage3-revisions/uploads" / revision_archive,
            role=ROLE_STUDENT,
            stage=STAGE3,
            kind=KIND_REVISION,
            student_number=author,
            payload={"student": student, "problems": revised_problems, "responses": responses},
        )
        state["revisions"][author] = {
            "student": student,
            "problems": revised_problems,
            "responses": responses,
            "archive": revision_archive,
            "received_at": datetime.now(UTC).isoformat(),
        }


def _student(number: int) -> dict[str, str]:
    return {"student_number": str(number), "name": f"学生{number}", "class_id": "演示班"}


def _ai_student() -> dict[str, str]:
    return {
        "student_number": AI_REVIEWER_STUDENT_NUMBER,
        "name": AI_REVIEWER_NAME,
        "class_id": AI_REVIEWER_CLASS_ID,
    }


def _problem(student_number: str, index: int) -> dict[str, Any]:
    delta = (int(student_number) + index) % 7 + 1
    public_tests = [
        _case({"x": value}, value + delta) for value in range(1, PUBLIC_TESTS_PER_PROBLEM + 1)
    ]
    author_tests = [_case({"x": value}, value + delta) for value in range(AUTHOR_TESTS_PER_PROBLEM)]
    return {
        "problem_id": f"pb_demo_{student_number}_{index}",
        "title": f"整数加 {delta}",
        "statement": f"给定一个整数 x，返回 x 加 {delta} 后的结果。",
        "signature": "def solve(x: int) -> int:",
        "reference_solution": f"def solve(x: int) -> int:\n    return x + {delta}\n",
        "public_tests": public_tests,
        "author_tests": author_tests,
        "notes": "演示数据题目。",
    }


def _validation(problem: dict[str, Any]) -> dict[str, Any]:
    result = execute_problem(problem)
    return {
        "status": result["verdict"],
        "content_hash": _content_hash(problem),
        "snapshot_version": snapshot_version(),
        "validated_at": datetime.now(UTC).isoformat(),
        "message": "校验通过",
        "test_results": result["test_results"],
    }


def _student_run(
    root: Path,
    state: dict[str, Any],
    problem: dict[str, Any],
    student_number: str,
    index: int,
) -> dict[str, Any]:
    result = execute_problem(problem)
    prompt = render_official_prompt(problem["statement"], problem["signature"], problem["public_tests"])
    run_id = f"run_demo_{student_number}_{index}_{datetime.now(UTC).strftime('%H%M%S%f')}"
    created_at = datetime.now(UTC).isoformat()
    runtime = load_runtime_config(root)
    config = RuntimeConfig(
        base_url=state["settings"].get("base_url") or DEFAULT_BASE_URL,
        api_key=runtime.api_key,
        models=state["settings"].get("models") or DEFAULT_MODELS,
        env_file=runtime.env_file,
    )
    completion = mock_completion(
        config=config,
        run_id=run_id,
        model=config.models[0],
        prompt=prompt,
        content=problem["reference_solution"],
        created_at=created_at,
    )
    return {
        "run_id": run_id,
        "run_origin": RUN_ORIGIN_STUDENT_SELF_TEST,
        "model": config.models[0],
        "base_url": config.base_url,
        "prompt_template_id": PROMPT_TEMPLATE_ID,
        "prompt": prompt,
        "prompt_parts": render_official_prompt_parts(problem["statement"], problem["signature"], problem["public_tests"]),
        "content_hash": _content_hash(problem),
        "snapshot_version": snapshot_version(),
        "temperature": MODEL_RUN_TEMPERATURE,
        "top_p": MODEL_RUN_TOP_P,
        "verdict": result["verdict"],
        "created_at": created_at,
        "package_selected": True,
        "api_request_raw": completion.request_raw,
        "api_response_raw": completion.response_raw,
        "raw_response": completion.content,
        "extracted_code": problem["reference_solution"],
        "test_results": result["test_results"],
    }


def _assignment_problem(anon_id: str, origin: str, problem: dict[str, Any]) -> dict[str, Any]:
    return {
        "anonymous_id": anon_id,
        "review_origin": origin,
        **{key: value for key, value in problem.items() if key != "validation"},
    }


def _review(anon_id: str, conclusion: str, quality_score: int, explanation: str) -> dict[str, str]:
    return {
        "anonymous_id": anon_id,
        "conclusion": conclusion,
        "quality_score": str(quality_score),
        "explanation": explanation,
    }


def _case(kwargs: dict[str, Any], expected: Any) -> str:
    return json.dumps(
        {"input": {"kwargs": kwargs}, "expected": expected},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _content_hash(problem: dict[str, Any]) -> str:
    from .student_app import _problem_signature_hash

    return _problem_signature_hash(problem)
