import re
from datetime import UTC, datetime

import pytest

from codesetarena.model_client import ModelResult, build_request_raw


@pytest.fixture(autouse=True)
def fake_real_model_completion(monkeypatch):
    def completion(*, config, model, prompt, timeout=60.0):
        content = _solution_for_prompt(prompt)
        created_at = datetime.now(UTC).isoformat()
        return ModelResult(
            request_raw=build_request_raw(config, model, prompt),
            response_raw={
                "schema_version": "codesetarena.api_response_raw.v1",
                "provider_api": "test_real_openai_chat_completions",
                "id": "chatcmpl_test",
                "object": "chat.completion",
                "created_at": created_at,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            },
            content=content,
        )

    monkeypatch.setattr("codesetarena.student_app.real_completion", completion, raising=False)
    monkeypatch.setattr("codesetarena.teacher_eval.real_completion", completion, raising=False)


def _solution_for_prompt(prompt: str) -> str:
    signature = _signature_from_prompt(prompt)
    if "Return x" in prompt:
        return f"{signature}\n    return x\n"
    delta_match = re.search(r"返回 x 加 (\d+)", prompt)
    if delta_match:
        return f"{signature}\n    return x + {delta_match.group(1)}\n"
    return f"{signature}\n    return x\n"


def _signature_from_prompt(prompt: str) -> str:
    match = re.search(r"函数签名：\s*\n([^\n]+)", prompt)
    signature = match.group(1).strip() if match else "def solve(x: int) -> int:"
    return signature if signature.endswith(":") else signature + ":"
