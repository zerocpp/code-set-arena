"""Prompt rendering for model solver runs."""

from __future__ import annotations

import json
from typing import Any, Iterable

from .constants import (
    EXECUTION_PYTHON_IMAGE,
    EXECUTION_PYTHON_VERSION,
    PROMPT_TEMPLATE_ID,
    PUBLIC_TESTS_PER_PROBLEM,
)


def render_official_prompt(statement: str, signature: str, public_tests: Iterable[Any]) -> str:
    return "".join(
        part["text"] for part in render_official_prompt_parts(statement, signature, public_tests)
    )


def render_official_prompt_parts(
    statement: str, signature: str, public_tests: Iterable[Any]
) -> list[dict[str, str]]:
    return [
        {
            "kind": "template",
            "text": f"请根据题目实现下面的 Python {EXECUTION_PYTHON_VERSION} 函数。\n\n题目：\n",
        },
        {"kind": "problem", "text": statement.strip()},
        {"kind": "template", "text": "\n\n公开示例：\n"},
        {"kind": "problem", "text": _format_public_examples(public_tests)},
        {"kind": "template", "text": "\n\n函数签名：\n"},
        {"kind": "problem", "text": signature.strip()},
        {
            "kind": "template",
            "text": (
                f"\n\n运行环境：\nPython {EXECUTION_PYTHON_VERSION}"
                f"（执行器镜像：{EXECUTION_PYTHON_IMAGE}）。\n"
            ),
        },
        {
            "kind": "template",
            "text": "\n\n输出要求：\n只输出完整函数定义，第一行必须是上述函数签名；不要输出 Markdown、解释或测试代码。\n",
        },
    ]


def prompt_template_id() -> str:
    return PROMPT_TEMPLATE_ID


def _format_public_examples(public_tests: Iterable[Any]) -> str:
    lines = []
    for test in list(public_tests)[:PUBLIC_TESTS_PER_PROBLEM]:
        parsed = _parse_test(test)
        kwargs = parsed.get("input", {}).get("kwargs", {})
        expected = parsed.get("expected")
        lines.append(
            "输入："
            + json.dumps(kwargs, ensure_ascii=False, separators=(",", ":"))
            + "；输出："
            + json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
            + "。"
        )
    return "\n".join(lines) if lines else "未提供公开示例。"


def _parse_test(test: Any) -> dict[str, Any]:
    if isinstance(test, str):
        try:
            parsed = json.loads(test)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return test if isinstance(test, dict) else {}
