"""Shared form length limits and validation helpers."""

from __future__ import annotations

from typing import Any

FORM_LIMITS = {
    "student_number": 64,
    "person_name": 80,
    "class_id": 80,
    "course_name": 120,
    "base_url": 300,
    "api_key": 300,
    "model_name": 120,
    "random_seed": 9,
    "problem_statement": 4000,
    "function_signature": 200,
    "reference_solution": 12000,
    "test_kwargs": 2000,
    "test_expected": 2000,
    "notes": 4000,
    "review_conclusion": 16,
    "review_explanation": 3000,
    "review_severity": 16,
    "review_summary": 1000,
    "review_evidence": 2000,
    "review_suggestion": 2000,
    "review_regression": 2000,
    "response_rating": 1,
    "author_response": 2000,
    "reviews_per_problem": 2,
}

FIELD_LABELS = {
    "student_number": "学号",
    "person_name": "姓名",
    "class_id": "班级或课程组",
    "course_name": "课程名称",
    "base_url": "Base URL",
    "api_key": "API Key",
    "model_name": "模型名称",
    "random_seed": "随机种子",
    "problem_statement": "题面",
    "function_signature": "函数签名",
    "reference_solution": "参考答案",
    "test_kwargs": "输入参数",
    "test_expected": "期望输出",
    "notes": "说明",
    "review_conclusion": "结论",
    "review_explanation": "建议",
    "review_severity": "严重程度",
    "review_summary": "摘要",
    "review_evidence": "证据",
    "review_suggestion": "建议修复",
    "review_regression": "Regression test",
    "response_rating": "审稿意见评分",
    "author_response": "回应建议",
    "reviews_per_problem": "每题总审稿份数",
}


def ensure_max_length(field: str, value: Any) -> None:
    text = str(value or "")
    limit = FORM_LIMITS[field]
    if len(text) > limit:
        label = FIELD_LABELS.get(field, field)
        raise ValueError(f"{label}超过长度上限 {limit} 字符")


def ensure_list_max_length(field: str, values: list[Any]) -> None:
    for value in values:
        ensure_max_length(field, value)
