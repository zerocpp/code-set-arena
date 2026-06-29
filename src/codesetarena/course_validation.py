"""Course workflow validation helpers."""

from __future__ import annotations

from typing import Any

from .constants import (
    AUTHOR_TESTS_PER_PROBLEM,
    MAX_SELECTED_RUNS_PER_PROBLEM,
    MIN_SELECTED_RUNS_PER_PROBLEM,
    PROBLEMS_PER_STUDENT,
    PUBLIC_TESTS_PER_PROBLEM,
    RUN_ORIGIN_STUDENT_SELF_TEST,
)
from .form_limits import ensure_max_length


ALLOWED_REVIEW_CONCLUSIONS = {"accept", "minor", "major", "reject"}


def validate_problem_draft(problem: dict[str, Any]) -> None:
    problem_id = problem.get("problem_id") or "unknown"
    for field in ["statement", "signature", "reference_solution"]:
        if not str(problem.get(field, "")).strip():
            raise ValueError(f"{problem_id} missing {field}")
    if len(problem.get("public_tests", [])) != PUBLIC_TESTS_PER_PROBLEM:
        raise ValueError(f"{problem_id} must contain exactly {PUBLIC_TESTS_PER_PROBLEM} public tests")
    if len(problem.get("author_tests", [])) != AUTHOR_TESTS_PER_PROBLEM:
        raise ValueError(f"{problem_id} must contain exactly {AUTHOR_TESTS_PER_PROBLEM} author tests")


def validate_stage1_problem_package(problems: list[dict[str, Any]]) -> None:
    if len(problems) != PROBLEMS_PER_STUDENT:
        raise ValueError(f"Stage 1 package must contain exactly {PROBLEMS_PER_STUDENT} problems")
    for problem in problems:
        validate_problem_draft(problem)
        problem_id = problem.get("problem_id") or "unknown"
        selected_runs = [
            run for run in problem.get("run_records", []) if run.get("package_selected")
        ]
        if not MIN_SELECTED_RUNS_PER_PROBLEM <= len(selected_runs) <= MAX_SELECTED_RUNS_PER_PROBLEM:
            raise ValueError(
                f"{problem_id} must contain {MIN_SELECTED_RUNS_PER_PROBLEM}-"
                f"{MAX_SELECTED_RUNS_PER_PROBLEM} selected run records"
            )
        for run in selected_runs:
            if run.get("run_origin") != RUN_ORIGIN_STUDENT_SELF_TEST:
                raise ValueError(f"{problem_id} selected run must be student_self_test")
            if not (run.get("prompt") and run.get("api_request_raw") and run.get("api_response_raw")):
                raise ValueError(f"{problem_id} selected run missing raw evidence")


def validate_review_assignment_payload(payload: dict[str, Any]) -> None:
    assigned = payload.get("assigned_problems", [])
    if not assigned:
        raise ValueError("review assignment must contain assigned_problems")
    seen: set[str] = set()
    for problem in assigned:
        anon_id = str(problem.get("anonymous_id", "")).strip()
        if not anon_id:
            raise ValueError("review assignment problem missing anonymous_id")
        if anon_id in seen:
            raise ValueError(f"{anon_id} duplicated in review assignment")
        seen.add(anon_id)
        validate_problem_draft(problem)
        run_records = problem.get("run_records", [])
        if not run_records:
            raise ValueError(f"{anon_id} missing submitted self-test run records")
        for run in run_records:
            if run.get("run_origin") != RUN_ORIGIN_STUDENT_SELF_TEST:
                raise ValueError(f"{anon_id} run must be student_self_test")
            if not (run.get("prompt") and run.get("api_request_raw") and run.get("api_response_raw")):
                raise ValueError(f"{anon_id} run missing raw evidence")
            if not (run.get("extracted_code") or run.get("raw_response")):
                raise ValueError(f"{anon_id} run missing returned code")


def validate_reviews_for_assignment(
    assigned_anonymous_ids: set[str], reviews: list[dict[str, Any]]
) -> None:
    received_ids = [str(review.get("anonymous_id", "")) for review in reviews]
    if len(received_ids) != len(set(received_ids)):
        raise ValueError("review package contains duplicate anonymous_id")
    received = set(received_ids)
    if received != assigned_anonymous_ids:
        missing = sorted(assigned_anonymous_ids - received)
        extra = sorted(received - assigned_anonymous_ids)
        raise ValueError(f"review package must contain exactly assigned reviews; missing={missing}, extra={extra}")
    for review in reviews:
        validate_review(review)


def validate_review(review: dict[str, Any]) -> None:
    anon_id = str(review.get("anonymous_id", ""))
    conclusion = str(review.get("conclusion", "")).strip()
    ensure_max_length("review_conclusion", conclusion)
    if not conclusion:
        raise ValueError(f"{anon_id} 请选择结论")
    if conclusion not in ALLOWED_REVIEW_CONCLUSIONS:
        raise ValueError(f"{anon_id} conclusion must be one of {sorted(ALLOWED_REVIEW_CONCLUSIONS)}")
    ensure_max_length("review_explanation", review.get("explanation", ""))
    if not str(review.get("explanation", "")).strip():
        raise ValueError(f"{anon_id} review suggestion is required")
    try:
        quality_score = int(str(review.get("quality_score", "")).strip())
    except ValueError as exc:
        raise ValueError(f"{anon_id} quality score must be an integer from 1 to 5") from exc
    if not 1 <= quality_score <= 5:
        raise ValueError(f"{anon_id} quality score must be an integer from 1 to 5")


def validate_responses_for_feedback(expected_review_ids: set[str], responses: list[dict[str, Any]]) -> None:
    received_ids = [str(response.get("review_id", "")) for response in responses]
    if len(received_ids) != len(set(received_ids)):
        raise ValueError("revision package contains duplicate review_id")
    received = set(received_ids)
    if received != expected_review_ids:
        missing = sorted(expected_review_ids - received)
        extra = sorted(received - expected_review_ids)
        raise ValueError(f"revision package must contain exactly assigned responses; missing={missing}, extra={extra}")
    for response in responses:
        validate_author_response(response)


def validate_author_response(response: dict[str, Any]) -> None:
    review_id = str(response.get("review_id", ""))
    ensure_max_length("response_rating", response.get("rating", ""))
    try:
        rating = int(str(response.get("rating", "")).strip())
    except ValueError as exc:
        raise ValueError(f"{review_id} rating must be an integer from 1 to 5") from exc
    if not 1 <= rating <= 5:
        raise ValueError(f"{review_id} rating must be an integer from 1 to 5")
    ensure_max_length("author_response", response.get("response", ""))
    if not str(response.get("response", "")).strip():
        raise ValueError(f"{review_id} response is required")
