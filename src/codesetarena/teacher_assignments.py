"""Teacher review assignment and feedback packaging helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .constants import (
    AI_REVIEWER_CLASS_ID,
    AI_REVIEWER_NAME,
    AI_REVIEWER_STUDENT_NUMBER,
    DEFAULT_RANDOM_SEED,
    KIND_REVIEW_ASSIGNMENT,
    KIND_REVIEW_FEEDBACK,
    ROLE_TEACHER,
    STAGE2,
    STAGE3,
)
from .package_names import teacher_bulk_name, teacher_package_name
from .packages import write_bundle, write_package


def parse_random_seed(value: Any) -> int:
    try:
        seed = int(str(value if value is not None else DEFAULT_RANDOM_SEED).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError("随机种子必须是 0 到 999999999 之间的整数") from exc
    if seed < 0 or seed > 999_999_999:
        raise ValueError("随机种子必须是 0 到 999999999 之间的整数")
    return seed


def settings_random_seed(state: dict[str, Any]) -> int:
    return parse_random_seed(state.get("settings", {}).get("random_seed", DEFAULT_RANDOM_SEED))


def build_review_assignment_packages(
    root: Path, state: dict[str, Any], reviews_per_problem: int
) -> tuple[Path, list[Path], dict[str, Any]]:
    submissions = state.get("submissions", {})
    if not submissions:
        raise ValueError("至少需要 1 名学生的 Stage 1 包才能生成审稿任务")
    if reviews_per_problem < 1:
        raise ValueError("每题总审稿份数必须至少为 1，其中 1 份固定由 AI 完成")
    if reviews_per_problem > 99:
        raise ValueError("每题总审稿份数必须不超过 99")
    human_reviews_per_problem = reviews_per_problem - 1
    students = sorted(submissions)
    if human_reviews_per_problem > 0 and len(students) < 2:
        raise ValueError("需要学生互审时，至少需要 2 名学生的 Stage 1 包")
    if human_reviews_per_problem > len(students) - 1:
        raise ValueError("学生互审份数不能超过可分配的其他学生数量")

    seed = settings_random_seed(state)
    user_map = _anonymous_user_map(seed, submissions)
    problem_map, problem_lookup = _anonymous_problem_map(seed, submissions)
    assignments: dict[str, dict[str, Any]] = {}
    assigned_by_reviewer: dict[str, list[dict[str, Any]]] = {
        student: [] for student in [*students, AI_REVIEWER_STUDENT_NUMBER]
    }
    manifest_assignments: list[dict[str, Any]] = []

    problem_entries = _assignment_problem_entries(submissions)
    balanced_reviewers = _balanced_human_reviewers_for_problems(
        seed, students, problem_entries, human_reviews_per_problem
    )

    for entry in problem_entries:
        author = entry["author"]
        problem = entry["problem"]
        problem_index = entry["problem_index"]
        problem_id = entry["problem_id"]
        problem_info = problem_lookup[(author, problem_id, problem_index)]
        reviewers = balanced_reviewers[(author, problem_id, problem_index)]
        reviewer_specs = [(AI_REVIEWER_STUDENT_NUMBER, "ai"), *[(item, "human") for item in reviewers]]
        for reviewer, review_origin in reviewer_specs:
            review_assignment = {
                "author_student_number": author,
                "problem_id": problem_id,
                "problem_index": problem_index,
                "review_origin": review_origin,
                "anonymous_problem_id": problem_info["anonymous_problem_id"],
                "anonymous_author_id": problem_info["anonymous_author_id"],
                "reviewer_anonymous_user_id": _anon_user_id(seed, reviewer),
            }
            assignments.setdefault(reviewer, {})[problem_info["anonymous_problem_id"]] = review_assignment
            assigned_by_reviewer.setdefault(reviewer, []).append(
                {
                    "anonymous_id": problem_info["anonymous_problem_id"],
                    "anonymous_problem_id": problem_info["anonymous_problem_id"],
                    "anonymous_author_id": problem_info["anonymous_author_id"],
                    "review_origin": review_origin,
                    **_review_assignment_problem(problem),
                }
            )
            manifest_assignments.append(
                {
                    "reviewer_student_number": reviewer,
                    "reviewer_anonymous_user_id": _anon_user_id(seed, reviewer),
                    **review_assignment,
                }
            )

    package_paths: list[Path] = []
    for reviewer in [AI_REVIEWER_STUDENT_NUMBER, *students]:
        assigned = _ordered_assigned_problems(seed, reviewer, assigned_by_reviewer.get(reviewer, []))
        if reviewer != AI_REVIEWER_STUDENT_NUMBER and human_reviews_per_problem > 0 and not assigned:
            raise ValueError("审稿分配为空，请检查学生人数和每题总审稿份数")
        if reviewer != AI_REVIEWER_STUDENT_NUMBER and not assigned:
            continue
        student = _ai_reviewer_student() if reviewer == AI_REVIEWER_STUDENT_NUMBER else submissions[reviewer]["student"]
        payload = {
            "assignment_id": "asg_" + _stable_token(seed, "assignment", reviewer, reviews_per_problem),
            "student": student,
            "reviews_per_problem": reviews_per_problem,
            "human_reviews_per_problem": human_reviews_per_problem,
            "ai_reviews_per_problem": 1,
            "review_origin": "ai" if reviewer == AI_REVIEWER_STUDENT_NUMBER else "human",
            "assigned_problems": assigned,
        }
        output = root / "stage2-review-assignment/review-packages" / teacher_package_name(
            reviewer, STAGE2, KIND_REVIEW_ASSIGNMENT
        )
        write_package(
            output,
            role=ROLE_TEACHER,
            stage=STAGE2,
            kind=KIND_REVIEW_ASSIGNMENT,
            student_number=reviewer,
            payload=payload,
        )
        package_paths.append(output)

    manifest = {
        "schema_version": "codesetarena.teacher-bundle.v1",
        "stage": STAGE2,
        "kind": "review-assignments",
        "random_seed": seed,
        "reviews_per_problem": reviews_per_problem,
        "human_reviews_per_problem": human_reviews_per_problem,
        "ai_reviews_per_problem": 1,
        "package_files": [path.name for path in package_paths],
        "anonymous_user_map": user_map,
        "anonymous_problem_map": problem_map,
        "assignments": sorted(
            manifest_assignments,
            key=lambda item: (
                item["reviewer_student_number"],
                item["author_student_number"],
                item["problem_index"],
                item["review_origin"],
            ),
        ),
    }
    bundle = root / "stage2-review-assignment/review-packages" / teacher_bulk_name(
        STAGE2, "review-assignments"
    )
    write_bundle(bundle, package_paths, manifest)
    state["assignments"] = assignments
    state["stage2_assignment_manifest"] = manifest
    return bundle, package_paths, manifest


def build_review_feedback_packages(root: Path, state: dict[str, Any]) -> tuple[Path, list[Path], dict[str, Any]]:
    seed = settings_random_seed(state)
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
                    "review_id": "rev_" + _stable_token(seed, "review", reviewer, anon_id, index),
                    "reviewer_student_number": reviewer,
                    "reviewer_anonymous_user_id": mapping.get("reviewer_anonymous_user_id", _anon_user_id(seed, reviewer)),
                    "problem_id": mapping["problem_id"],
                    "anonymous_id": anon_id,
                    "anonymous_problem_id": mapping.get("anonymous_problem_id", anon_id),
                    "anonymous_author_id": mapping.get("anonymous_author_id", ""),
                    "review_origin": mapping.get("review_origin", "human"),
                    "review": review,
                }
            )
    if not feedback_by_author:
        raise ValueError("还没有可发放的审稿反馈")

    package_paths: list[Path] = []
    feedback_summary: list[dict[str, Any]] = []
    state["feedback"] = {}
    for author in sorted(feedback_by_author):
        reviews = _ordered_feedback_reviews(seed, author, feedback_by_author[author])
        student = state["submissions"][author]["student"]
        sanitized_reviews = [_sanitize_feedback_for_author(item) for item in reviews]
        output = root / "stage3-revisions/feedback-packages" / teacher_package_name(
            author, STAGE3, KIND_REVIEW_FEEDBACK
        )
        write_package(
            output,
            role=ROLE_TEACHER,
            stage=STAGE3,
            kind=KIND_REVIEW_FEEDBACK,
            student_number=author,
            payload={"student": student, "reviews_for_author": sanitized_reviews},
        )
        package_paths.append(output)
        state["feedback"][author] = {"archive": output.name, "reviews": reviews}
        feedback_summary.append(
            {
                "author_student_number": author,
                "author_anonymous_user_id": _anon_user_id(seed, author),
                "archive": output.name,
                "review_count": len(reviews),
            }
        )

    stage2_manifest = state.get("stage2_assignment_manifest", {})
    manifest = {
        "schema_version": "codesetarena.teacher-bundle.v1",
        "stage": STAGE3,
        "kind": "review-feedbacks",
        "random_seed": seed,
        "package_files": [path.name for path in package_paths],
        "anonymous_user_map": stage2_manifest.get("anonymous_user_map", []),
        "anonymous_problem_map": stage2_manifest.get("anonymous_problem_map", []),
        "feedback_summary": feedback_summary,
    }
    bundle = root / "stage3-revisions/feedback-packages" / teacher_bulk_name(
        STAGE3, "review-feedbacks"
    )
    write_bundle(bundle, package_paths, manifest)
    state["stage3_feedback_manifest"] = manifest
    return bundle, package_paths, manifest


def _assignment_problem_entries(submissions: dict[str, Any]) -> list[dict[str, Any]]:
    entries = []
    for author, submission in sorted(submissions.items()):
        for problem_index, problem in enumerate(submission.get("problems", [])):
            entries.append(
                {
                    "author": author,
                    "problem_id": str(problem.get("problem_id", "")),
                    "problem_index": problem_index,
                    "problem": problem,
                }
            )
    return entries


def _balanced_human_reviewers_for_problems(
    seed: int,
    students: list[str],
    problem_entries: list[dict[str, Any]],
    count: int,
) -> dict[tuple[str, str, int], list[str]]:
    reviewer_plan: dict[tuple[str, str, int], list[str]] = {}
    seeded_students = sorted(students, key=lambda student: _stable_token(seed, "student-order", student))
    student_positions = {student: index for index, student in enumerate(seeded_students)}
    global_offset = int(_stable_token(seed, "reviewer-start"), 16)
    for item in problem_entries:
        author = item["author"]
        problem_id = item["problem_id"]
        problem_index = item["problem_index"]
        candidates = [student for student in seeded_students if student != author]
        start = (problem_index * count + student_positions[author] + global_offset) % len(candidates)
        reviewers = [candidates[(start + offset) % len(candidates)] for offset in range(count)]
        reviewer_plan[(author, problem_id, problem_index)] = reviewers
    _validate_balanced_human_reviewer_plan(students, reviewer_plan, problem_entries, count)
    return reviewer_plan


def _validate_balanced_human_reviewer_plan(
    students: list[str],
    reviewer_plan: dict[tuple[str, str, int], list[str]],
    problem_entries: list[dict[str, Any]],
    count: int,
) -> None:
    if count == 0:
        return
    reviewer_loads = {student: 0 for student in students}
    for item in problem_entries:
        key = (item["author"], item["problem_id"], item["problem_index"])
        reviewers = reviewer_plan.get(key, [])
        if len(reviewers) != count:
            raise ValueError("无法生成均匀审稿分配：某道题的学生审稿人数不足")
        if len(set(reviewers)) != len(reviewers):
            raise ValueError("无法生成均匀审稿分配：同一学生被重复分配到同一道题")
        if item["author"] in reviewers:
            raise ValueError("无法生成均匀审稿分配：学生不能审自己的题")
        for reviewer in reviewers:
            reviewer_loads[reviewer] += 1
    if reviewer_loads and max(reviewer_loads.values()) - min(reviewer_loads.values()) > 1:
        raise ValueError("无法生成均匀审稿分配：学生审稿负载差距超过 1")


def _ordered_assigned_problems(seed: int, reviewer: str, assigned: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        assigned,
        key=lambda item: _stable_token(
            seed,
            "assignment-order",
            reviewer,
            item.get("anonymous_problem_id", ""),
            item.get("review_origin", ""),
        ),
    )


def _ordered_feedback_reviews(seed: int, author: str, reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        reviews,
        key=lambda item: (
            item.get("problem_id", ""),
            _stable_token(
                seed,
                "feedback-order",
                author,
                item.get("problem_id", ""),
                item.get("reviewer_student_number", ""),
                item.get("anonymous_id", ""),
            ),
        ),
    )


def _anonymous_user_map(seed: int, submissions: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [
        {
            "anonymous_user_id": _anon_user_id(seed, student_number),
            "real_user_id": student_number,
            "name": row.get("student", {}).get("name", ""),
            "class_id": row.get("student", {}).get("class_id", ""),
            "role": "student",
        }
        for student_number, row in sorted(submissions.items())
    ]
    rows.append(
        {
            "anonymous_user_id": _anon_user_id(seed, AI_REVIEWER_STUDENT_NUMBER),
            "real_user_id": AI_REVIEWER_STUDENT_NUMBER,
            "name": AI_REVIEWER_NAME,
            "class_id": AI_REVIEWER_CLASS_ID,
            "role": "ai",
        }
    )
    return rows


def _anonymous_problem_map(
    seed: int, submissions: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[tuple[str, str, int], dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    lookup: dict[tuple[str, str, int], dict[str, str]] = {}
    for author, submission in sorted(submissions.items()):
        for problem_index, problem in enumerate(submission.get("problems", [])):
            problem_id = str(problem.get("problem_id", ""))
            row = {
                "anonymous_problem_id": _anon_problem_id(seed, author, problem_id, problem_index),
                "real_problem_id": problem_id,
                "author_student_number": author,
                "anonymous_author_id": _anon_user_id(seed, author),
                "title": problem.get("title") or problem_id,
            }
            rows.append(row)
            lookup[(author, problem_id, problem_index)] = row
    return rows, lookup


def _review_assignment_problem(problem: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": problem.get("title", ""),
        "statement": problem.get("statement", ""),
        "signature": problem.get("signature", ""),
        "reference_solution": problem.get("reference_solution", ""),
        "public_tests": problem.get("public_tests", []),
        "author_tests": problem.get("author_tests", []),
        "notes": problem.get("notes", ""),
        "run_records": problem.get("run_records", []),
    }


def _sanitize_feedback_for_author(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "review_id": item.get("review_id", ""),
        "reviewer_anonymous_user_id": item.get("reviewer_anonymous_user_id", ""),
        "anonymous_problem_id": item.get("anonymous_problem_id", ""),
        "anonymous_id": item.get("anonymous_id", ""),
        "problem_id": item.get("problem_id", ""),
        "review_origin": item.get("review_origin", ""),
        "review": item.get("review", {}),
    }


def _ai_reviewer_student() -> dict[str, str]:
    return {
        "student_number": AI_REVIEWER_STUDENT_NUMBER,
        "name": AI_REVIEWER_NAME,
        "class_id": AI_REVIEWER_CLASS_ID,
    }


def _anon_user_id(seed: int, user_id: str) -> str:
    return "anon_user_" + _stable_token(seed, "user", user_id)


def _anon_problem_id(seed: int, author: str, problem_id: str, problem_index: int) -> str:
    return "anon_problem_" + _stable_token(seed, "problem", author, problem_id, problem_index)


def _stable_token(seed: int, *parts: Any) -> str:
    text = ":".join(str(part) for part in (seed, *parts))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
