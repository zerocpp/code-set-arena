"""Utilities for turning model responses into executable run records."""

from __future__ import annotations

import ast
from dataclasses import dataclass
import re
from typing import Any

from .run_engine import RunEngineError, execute_solution_code


class RunRepairError(ValueError):
    """Raised when a persisted model run cannot be made compatible."""


@dataclass(frozen=True)
class RunRepairResult:
    ok: bool
    repaired: bool = False
    message: str = ""


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


def response_final_text(response_raw: Any) -> str:
    """Extract the provider's final answer text without using reasoning-only fields."""
    if not isinstance(response_raw, dict):
        return ""
    choices = response_raw.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if isinstance(message, dict):
                content = _text_from_content(message.get("content"))
                if content:
                    return content
            text = _text_from_content(choice.get("text"))
            if text:
                return text
    for key in ("output_text", "text"):
        text = _text_from_content(response_raw.get(key))
        if text:
            return text
    return ""


def repair_run_record_for_compat(run: dict[str, Any], signature: str) -> RunRepairResult:
    """Repair legacy run records whose final text was stored in a provider-specific field."""
    if run.get("raw_response") or run.get("extracted_code"):
        return RunRepairResult(ok=True)
    if _run_is_explicit_failure(run):
        return RunRepairResult(ok=True, message="explicit failed run")
    final_text = response_final_text(run.get("api_response_raw"))
    if final_text:
        run["raw_response"] = final_text
        run["extracted_code"] = extract_function_code(final_text, signature)
        return RunRepairResult(ok=True, repaired=True, message="restored final text")
    if _has_reasoning_content(run.get("api_response_raw")):
        raise RunRepairError("reasoning-only response missing final answer")
    raise RunRepairError("successful response missing final answer")


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


def _text_from_content(value: Any) -> str:
    if isinstance(value, str):
        return value if value.strip() else ""
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        combined = "".join(parts)
        return combined if combined.strip() else ""
    return ""


def _run_is_explicit_failure(run: dict[str, Any]) -> bool:
    api_status = str(run.get("api_status") or "").strip().lower()
    if api_status in {"failed", "failure", "timeout", "parse_failed", "error"}:
        return True
    response_raw = run.get("api_response_raw")
    if isinstance(response_raw, dict) and (response_raw.get("error_type") or response_raw.get("error")):
        return True
    return bool(run.get("api_error")) and api_status not in {"success", "succeeded", "ok"}


def _has_reasoning_content(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "reasoning_content" and str(child or "").strip():
                return True
            if _has_reasoning_content(child):
                return True
    elif isinstance(value, list):
        return any(_has_reasoning_content(item) for item in value)
    return False


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
