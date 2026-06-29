from pathlib import Path

import pytest

import codesetarena.run_engine as run_engine
from codesetarena.constants import (
    EXECUTION_PYTHON_IMAGE,
    EXECUTION_PYTHON_VERSION,
    PROMPT_TEMPLATE_ID,
)
from codesetarena.prompting import prompt_template_id, render_official_prompt
from codesetarena.run_engine import RunEngineError, ensure_executor_python_version, executor_python_version


def test_prompt_declares_executor_python_contract():
    prompt = render_official_prompt(
        "Return x.",
        "def solve(x: int) -> int:",
        ['{"input":{"kwargs":{"x":1}},"expected":1}'],
    )

    assert f"Python {EXECUTION_PYTHON_VERSION}" in prompt
    assert EXECUTION_PYTHON_IMAGE in prompt
    assert "复杂度要求" not in prompt
    assert "超时不算 failure mode" not in prompt
    assert "超时阈值" not in prompt
    assert prompt_template_id() == PROMPT_TEMPLATE_ID == "official_func_zh_v6"


def test_executor_python_version_matches_declared_contract():
    assert executor_python_version() == EXECUTION_PYTHON_VERSION
    ensure_executor_python_version()


def test_executor_python_version_mismatch_reports_clear_error(monkeypatch):
    monkeypatch.setattr(run_engine, "EXECUTION_PYTHON_VERSION", "9.99")

    with pytest.raises(RunEngineError) as exc_info:
        ensure_executor_python_version()

    assert exc_info.value.error_type == "python_version_error"
    assert "执行器 Python 版本不一致" in str(exc_info.value)
    assert EXECUTION_PYTHON_IMAGE in str(exc_info.value)


def test_dockerfiles_use_official_python_executor_image():
    root = Path(__file__).resolve().parents[1]
    for dockerfile in [
        root / "docker/runtime/Dockerfile",
        root / "docker/student/Dockerfile",
        root / "docker/teacher/Dockerfile",
    ]:
        first_line = dockerfile.read_text(encoding="utf-8").splitlines()[0]
        assert first_line == f"FROM {EXECUTION_PYTHON_IMAGE}"
        assert EXECUTION_PYTHON_IMAGE.startswith("python:")
        assert EXECUTION_PYTHON_VERSION in EXECUTION_PYTHON_IMAGE
