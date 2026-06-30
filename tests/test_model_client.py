import io
import json
import socket
import urllib.error
import urllib.request

import pytest

from codesetarena.config import RuntimeConfig, validate_api_key
from codesetarena.model_client import real_completion


def test_api_key_shape_validation():
    validate_api_key("")
    validate_api_key("sk-valid-local-key")

    with pytest.raises(ValueError, match="API Key 格式不合法"):
        validate_api_key("not-a-key")


def test_real_completion_redacts_invalid_api_key(monkeypatch):
    secret = "sk-invalid-secret"

    def fake_urlopen(*args, **kwargs):
        payload = json.dumps({"error": {"message": f"invalid api key {secret}"}}).encode()
        raise urllib.error.HTTPError(
            url="https://api.example.test/chat/completions",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(payload),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    config = RuntimeConfig(
        base_url="https://api.example.test",
        api_key=secret,
        models=["deepseek-v4-flash"],
        env_file=None,
    )
    with pytest.raises(RuntimeError) as exc_info:
        real_completion(config=config, model="deepseek-v4-flash", prompt="hello", timeout=1.0)

    message = str(exc_info.value)
    assert "HTTP 401" in message
    assert secret not in message
    assert "[REDACTED]" in message


def test_real_completion_reports_timeout(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise socket.timeout("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    config = RuntimeConfig(
        base_url="https://api.example.test",
        api_key="sk-valid-local-key",
        models=["deepseek-v4-flash"],
        env_file=None,
    )
    with pytest.raises(RuntimeError, match="真实模型请求超时"):
        real_completion(config=config, model="deepseek-v4-flash", prompt="hello", timeout=0.01)


def test_real_completion_sends_custom_model_name_to_provider(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "def solve(x: int) -> int:\n    return x\n",
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers.get("Authorization")
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    config = RuntimeConfig(
        base_url="https://api.example.test",
        api_key="sk-valid-local-key",
        models=["kfcvivo50"],
        env_file=None,
    )

    result = real_completion(config=config, model="kfcvivo50", prompt="hello", timeout=1.0)

    assert captured["body"]["model"] == "kfcvivo50"
    assert captured["authorization"] == "Bearer sk-valid-local-key"
    assert result.request_raw["body"]["model"] == "kfcvivo50"
    assert result.request_raw["headers"]["Authorization"] == "Bearer [REDACTED]"
    assert result.response_raw["provider_api"] == "real_openai_chat_completions"
