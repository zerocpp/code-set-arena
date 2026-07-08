import pytest

from codesetarena.model_run_utils import (
    RunRepairError,
    repair_run_record_for_compat,
    response_final_text,
)


def test_response_final_text_reads_provider_variants_without_reasoning_content():
    assert (
        response_final_text({"choices": [{"message": {"content": "def solve():\n    return 1"}}]})
        == "def solve():\n    return 1"
    )
    assert response_final_text({"choices": [{"text": "def solve():\n    return 2"}]}) == (
        "def solve():\n    return 2"
    )
    assert response_final_text({"text": "def solve():\n    return 3"}) == "def solve():\n    return 3"
    assert (
        response_final_text({"output_text": "def solve():\n    return 4"})
        == "def solve():\n    return 4"
    )
    assert response_final_text({"choices": [{"message": {"reasoning_content": "先分析边界"}}]}) == ""


def test_repair_run_record_restores_legacy_top_level_text():
    run = {
        "run_id": "run_1",
        "api_status": "success",
        "raw_response": "",
        "extracted_code": "",
        "api_response_raw": {"text": "def solve(x: int) -> int:\n    return x\n"},
    }

    result = repair_run_record_for_compat(run, "def solve(x: int) -> int:")

    assert result.repaired is True
    assert run["raw_response"] == "def solve(x: int) -> int:\n    return x\n"
    assert run["extracted_code"] == "def solve(x: int) -> int:\n    return x"


def test_repair_run_record_allows_explicit_failed_runs_without_code():
    run = {
        "run_id": "run_failed",
        "api_status": "failed",
        "api_error": "真实模型请求超时",
        "raw_response": "",
        "extracted_code": "",
        "api_response_raw": {"error_type": "timeout", "error": "超过 60 秒未返回"},
    }

    result = repair_run_record_for_compat(run, "def solve(x: int) -> int:")

    assert result.ok is True
    assert result.repaired is False
    assert run["raw_response"] == ""
    assert run["extracted_code"] == ""


def test_repair_run_record_rejects_reasoning_only_success_response():
    run = {
        "run_id": "run_reasoning_only",
        "api_status": "success",
        "raw_response": "",
        "extracted_code": "",
        "api_response_raw": {
            "choices": [{"message": {"reasoning_content": "我先分析一下，然后没有最终答案"}}]
        },
    }

    with pytest.raises(RunRepairError, match="reasoning"):
        repair_run_record_for_compat(run, "def solve(x: int) -> int:")
