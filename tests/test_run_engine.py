import pytest

from codesetarena.constants import EXECUTION_TARGET_SECONDS, EXECUTION_TIMEOUT_SECONDS
from codesetarena.run_engine import DEFAULT_EXECUTION_TIMEOUT_SECONDS, RunEngineError, execute_problem


def _problem(reference_solution: str) -> dict:
    return {
        "statement": "Return x.",
        "signature": "def solve(x: int) -> int:",
        "reference_solution": reference_solution,
        "public_tests": [
            '{"input":{"kwargs":{"x":1}},"expected":1}',
            '{"input":{"kwargs":{"x":2}},"expected":2}',
        ],
        "author_tests": [
            '{"input":{"kwargs":{"x":0}},"expected":0}',
            '{"input":{"kwargs":{"x":3}},"expected":3}',
            '{"input":{"kwargs":{"x":4}},"expected":4}',
            '{"input":{"kwargs":{"x":5}},"expected":5}',
            '{"input":{"kwargs":{"x":6}},"expected":6}',
        ],
    }


def test_execute_problem_reports_python_version_or_syntax_error():
    problem = _problem("def solve(x: int) -> int:\n    return x +\n")

    with pytest.raises(RunEngineError) as exc_info:
        execute_problem(problem)

    assert exc_info.value.error_type == "python_version_error"
    assert "Python 版本" in str(exc_info.value)
    assert "语法" in str(exc_info.value)


def test_execute_problem_reports_case_timeout():
    problem = _problem("def solve(x: int) -> int:\n    while True:\n        pass\n")

    result = execute_problem(problem, timeout_seconds=0.05)
    error = result["test_results"][0]["error"]

    assert result["verdict"] == "failed"
    assert result["test_results"][0]["verdict"] == "error"
    assert result["test_results"][0]["error_type"] == "execution_timeout"
    assert "超时" in error
    assert f"默认单用例超时阈值为 {EXECUTION_TIMEOUT_SECONDS:g} 秒" in error
    assert f"尽量在 {EXECUTION_TARGET_SECONDS:g} 秒内完成" in error
    assert "超时不算 failure mode" in error


def test_default_execution_timeout_is_hardware_cushion():
    assert DEFAULT_EXECUTION_TIMEOUT_SECONDS == EXECUTION_TIMEOUT_SECONDS == 10


def test_execute_problem_reports_memory_limit_error():
    problem = _problem("def solve(x: int) -> int:\n    raise MemoryError('too much')\n")

    result = execute_problem(problem)

    assert result["verdict"] == "failed"
    assert result["test_results"][0]["verdict"] == "error"
    assert result["test_results"][0]["error_type"] == "memory_limit_exceeded"
    assert "内存" in result["test_results"][0]["error"]
