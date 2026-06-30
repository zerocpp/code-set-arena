"""Utilities for turning model responses into executable run records."""

from __future__ import annotations

import ast
import re
from typing import Any

from .run_engine import RunEngineError, execute_solution_code


def execute_model_code(problem: dict[str, Any], extracted_code: str) -> dict[str, Any]:
    try:
        return execute_solution_code(problem, extracted_code)
    except RunEngineError as exc:
        return {
            "verdict": "failed",
            "test_results": [
                {
                    "case_id": "execution",
                    "test_set": "system",
                    "index": 0,
                    "expected": None,
                    "actual": None,
                    "verdict": "error",
                    "error_type": exc.error_type,
                    "error": str(exc),
                    "traceback": "",
                }
            ],
        }


def extract_function_code(raw_response: str, signature: str) -> str:
    content = raw_response.strip()
    fenced = re.search(r"```(?:python)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        content = fenced.group(1).strip()
    expected_name = _function_name_from_signature(signature)
    match = re.search(rf"(^|\n)(def\s+{re.escape(expected_name)}\s*\()", content)
    if match:
        content = content[match.start(2) :].strip()
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return content
    lines = content.splitlines()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == expected_name and node.end_lineno:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno]).strip()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.end_lineno:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno]).strip()
    return content


def _function_name_from_signature(signature: str) -> str:
    source = signature.strip()
    if source.endswith(":"):
        source += "\n    pass"
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return "solve"
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            return node.name
    return "solve"
