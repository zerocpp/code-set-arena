"""Local execution helper for reference-answer validation and self-test runs."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from typing import Any

from .constants import (
    EXECUTION_PYTHON_IMAGE,
    EXECUTION_PYTHON_VERSION,
    EXECUTION_TARGET_SECONDS,
    EXECUTION_TIMEOUT_SECONDS,
)

DEFAULT_EXECUTION_TIMEOUT_SECONDS = EXECUTION_TIMEOUT_SECONDS
DEFAULT_EXECUTION_MEMORY_LIMIT_MB = 512


class RunEngineError(ValueError):
    """Raised when a problem cannot be executed."""

    def __init__(self, message: str, error_type: str = "execution_error") -> None:
        super().__init__(message)
        self.error_type = error_type


def execute_problem(
    problem: dict[str, Any],
    *,
    timeout_seconds: float = DEFAULT_EXECUTION_TIMEOUT_SECONDS,
    memory_limit_mb: int = DEFAULT_EXECUTION_MEMORY_LIMIT_MB,
) -> dict[str, Any]:
    return execute_solution_code(
        problem,
        str(problem.get("reference_solution", "")),
        timeout_seconds=timeout_seconds,
        memory_limit_mb=memory_limit_mb,
    )


def execute_solution_code(
    problem: dict[str, Any],
    solution_code: str,
    *,
    timeout_seconds: float = DEFAULT_EXECUTION_TIMEOUT_SECONDS,
    memory_limit_mb: int = DEFAULT_EXECUTION_MEMORY_LIMIT_MB,
) -> dict[str, Any]:
    ensure_executor_python_version()
    function_name = _function_name(problem.get("signature", ""))
    cases = _test_cases(problem)
    payload = {
        "reference_solution": solution_code,
        "function_name": function_name,
        "cases": cases,
        "timeout_seconds": timeout_seconds,
        "memory_limit_mb": memory_limit_mb,
        "expected_python_version": EXECUTION_PYTHON_VERSION,
        "expected_python_image": EXECUTION_PYTHON_IMAGE,
        "target_seconds": EXECUTION_TARGET_SECONDS,
        "default_timeout_seconds": EXECUTION_TIMEOUT_SECONDS,
    }
    worker_timeout = max(1.0, timeout_seconds * max(1, len(cases)) + 2.0)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", _WORKER_SCRIPT],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            timeout=worker_timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        return _fatal_result(
            "execution_timeout",
            "执行超时："
            f"整体运行超过 {worker_timeout:g} 秒，可能存在死循环、阻塞或复杂度过高。"
            + _timeout_policy_text(),
            cases,
            str(exc),
        )

    if completed.returncode != 0 and not completed.stdout.strip():
        return _fatal_result(
            "memory_limit_exceeded",
            f"执行超出内存限制或子进程异常退出：限制 {memory_limit_mb} MB。",
            cases,
            completed.stderr,
        )

    try:
        output = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return _fatal_result(
            "execution_error",
            "执行器返回结果无法解析，请检查参考答案是否触发了解释器级错误。",
            cases,
            completed.stderr or str(exc),
        )

    if output.get("fatal"):
        error_type = str(output.get("error_type") or "execution_error")
        raise RunEngineError(str(output.get("message") or "执行失败"), error_type=error_type)

    test_results = output.get("test_results", [])
    verdict = "passed" if test_results and all(row["verdict"] == "passed" for row in test_results) else "failed"
    return {"verdict": verdict, "test_results": test_results}


def executor_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def ensure_executor_python_version() -> None:
    current = executor_python_version()
    if current != EXECUTION_PYTHON_VERSION:
        raise RunEngineError(
            "执行器 Python 版本不一致："
            f"提示词要求 Python {EXECUTION_PYTHON_VERSION}，当前执行器 Python {current}。"
            f"请使用官方镜像 {EXECUTION_PYTHON_IMAGE}。",
            "python_version_error",
        )


def _timeout_policy_text() -> str:
    return (
        f"课程默认单用例超时阈值为 {EXECUTION_TIMEOUT_SECONDS:g} 秒，"
        "仅用于弥补不同硬件差异；超时不算 failure mode（失败模式），"
        "也不鼓励作为题目设计目标。请降低算法复杂度和测试规模，"
        f"让参考答案和合理模型解法尽量在 {EXECUTION_TARGET_SECONDS:g} 秒内完成。"
    )


def _function_name(signature: str) -> str:
    signature_source = signature.strip() or "def solve():"
    if signature_source.endswith(":"):
        signature_source += "\n    pass"
    try:
        tree = ast.parse(signature_source)
    except SyntaxError as exc:
        raise RunEngineError("函数签名无法解析，可能存在 Python 版本不兼容或语法错误", "python_version_error") from exc
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            return node.name
    raise RunEngineError("函数签名中没有函数定义")


def _test_cases(problem: dict[str, Any]) -> list[dict[str, Any]]:
    cases = []
    for test_set, lines in [
        ("public", problem.get("public_tests", [])),
        ("author", problem.get("author_tests", [])),
    ]:
        for index, line in enumerate(lines):
            cases.append(
                {
                    "line": _normalize_test_line(line),
                    "test_set": test_set,
                    "index": index,
                    "case_id": ("p" if test_set == "public" else "a") + f"-{index}",
                }
            )
    return cases


def _normalize_test_line(line: Any) -> str:
    if isinstance(line, str):
        return line
    if isinstance(line, dict) and "kwargs" in line:
        return json.dumps({"input": {"kwargs": line.get("kwargs", {})}, "expected": line.get("expected")})
    return json.dumps(line)


def _fatal_result(error_type: str, message: str, cases: list[dict[str, Any]], stderr: str = "") -> dict[str, Any]:
    if not cases:
        cases = [{"case_id": "execution", "test_set": "system", "index": 0}]
    test_results = [
        {
            "case_id": cases[0]["case_id"],
            "test_set": cases[0]["test_set"],
            "index": cases[0]["index"],
            "expected": None,
            "actual": None,
            "verdict": "error",
            "error_type": error_type,
            "error": message,
            "traceback": stderr,
        }
    ]
    return {"verdict": "failed", "test_results": test_results}


_WORKER_SCRIPT = textwrap.dedent(
    r"""
    import json
    import platform
    import resource
    import signal
    import sys
    import traceback


    class CaseTimeout(Exception):
        pass


    def json_safe(value):
        if isinstance(value, tuple):
            return [json_safe(item) for item in value]
        if isinstance(value, list):
            return [json_safe(item) for item in value]
        if isinstance(value, dict):
            return {str(key): json_safe(item) for key, item in value.items()}
        try:
            json.dumps(value)
        except TypeError:
            return repr(value)
        return value


    def set_memory_limit(memory_limit_mb):
        if not memory_limit_mb:
            return
        limit = int(memory_limit_mb) * 1024 * 1024
        for name in ("RLIMIT_AS", "RLIMIT_DATA"):
            if hasattr(resource, name):
                try:
                    resource.setrlimit(getattr(resource, name), (limit, limit))
                except (OSError, ValueError):
                    pass


    def fail_fatal(error_type, message, exc=None):
        payload = {
            "fatal": True,
            "error_type": error_type,
            "message": message,
            "python_version": platform.python_version(),
        }
        if exc is not None:
            payload["traceback"] = traceback.format_exc(limit=6)
        print(json.dumps(payload, ensure_ascii=False))
        raise SystemExit(0)


    def timeout_handler(signum, frame):
        raise CaseTimeout()


    def matches_expected(actual, expected):
        return actual == expected


    payload = json.loads(sys.stdin.read())
    expected_python_version = payload.get("expected_python_version")
    current_python_version = ".".join(platform.python_version_tuple()[:2])
    if expected_python_version and current_python_version != expected_python_version:
        fail_fatal(
            "python_version_error",
            "执行器 Python 版本不一致："
            f"提示词要求 Python {expected_python_version}，当前执行器 Python {current_python_version}。"
            f"请使用官方镜像 {payload.get('expected_python_image') or 'python'}。",
        )
    set_memory_limit(payload.get("memory_limit_mb"))
    reference_solution = payload.get("reference_solution", "")
    function_name = payload.get("function_name", "")
    timeout_seconds = float(payload.get("timeout_seconds") or 10.0)
    target_seconds = payload.get("target_seconds") or 1
    default_timeout_seconds = payload.get("default_timeout_seconds") or 10
    namespace = {}
    try:
        code = compile(reference_solution, "<reference_solution>", "exec")
        exec(code, namespace)  # noqa: S102
    except SyntaxError as exc:
        fail_fatal(
            "python_version_error",
            "Python 版本不兼容或参考答案语法错误："
            f"当前运行环境 Python {platform.python_version()}，请检查是否使用了不兼容语法。{exc.msg}",
            exc,
        )
    except MemoryError as exc:
        fail_fatal(
            "memory_limit_exceeded",
            f"执行超出内存限制：参考答案加载阶段触发 MemoryError，限制 {payload.get('memory_limit_mb')} MB。",
            exc,
        )
    except Exception as exc:
        fail_fatal("runtime_error", "reference_solution 执行失败：" + repr(exc), exc)

    candidate = namespace.get(function_name)
    if not callable(candidate):
        fail_fatal("missing_function", f"reference_solution 中找不到函数 {function_name}")

    signal.signal(signal.SIGALRM, timeout_handler)
    results = []
    for case in payload.get("cases", []):
        result = {"case_id": case["case_id"], "test_set": case["test_set"], "index": case["index"]}
        try:
            test = json.loads(case["line"])
            if isinstance(test, dict) and test.get("__format_error"):
                raise ValueError(str(test["__format_error"]))
            kwargs = test.get("input", {}).get("kwargs", {})
            expected = test.get("expected")
            if isinstance(expected, dict) and "any_of" in expected:
                raise ValueError("仅支持 EXACT_MATCH：expected.any_of 多答案格式不允许使用")
            signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
            actual = candidate(**kwargs)
            signal.setitimer(signal.ITIMER_REAL, 0)
            result.update(
                {
                    "kwargs": kwargs,
                    "expected": expected,
                    "actual": json_safe(actual),
                    "verdict": "passed" if matches_expected(actual, expected) else "failed",
                }
            )
        except CaseTimeout:
            signal.setitimer(signal.ITIMER_REAL, 0)
            result.update(
                {
                    "expected": None,
                    "actual": None,
                    "verdict": "error",
                    "error_type": "execution_timeout",
                    "error": (
                        f"执行超时：单个测试用例超过 {timeout_seconds:g} 秒，"
                        "可能存在死循环或复杂度过高。"
                        f"课程默认单用例超时阈值为 {float(default_timeout_seconds):g} 秒，"
                        "仅用于弥补不同硬件差异；超时不算 failure mode（失败模式），"
                        "也不鼓励作为题目设计目标。请降低算法复杂度和测试规模，"
                        f"让参考答案和合理模型解法尽量在 {float(target_seconds):g} 秒内完成。"
                    ),
                    "traceback": "",
                }
            )
        except MemoryError:
            signal.setitimer(signal.ITIMER_REAL, 0)
            result.update(
                {
                    "expected": None,
                    "actual": None,
                    "verdict": "error",
                    "error_type": "memory_limit_exceeded",
                    "error": f"执行超出内存限制：限制 {payload.get('memory_limit_mb')} MB，或代码触发 MemoryError。",
                    "traceback": traceback.format_exc(limit=6),
                }
            )
        except Exception as exc:
            signal.setitimer(signal.ITIMER_REAL, 0)
            result.update(
                {
                    "expected": None,
                    "actual": None,
                    "verdict": "error",
                    "error_type": "runtime_error",
                    "error": repr(exc),
                    "traceback": traceback.format_exc(limit=6),
                }
            )
        results.append(result)

    print(json.dumps({"fatal": False, "test_results": results}, ensure_ascii=False))
    """
)
