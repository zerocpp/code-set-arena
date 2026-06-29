"""OpenAI-compatible model client with mock and guarded real backends."""

from __future__ import annotations

import json
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from .config import RuntimeConfig
from .constants import MODEL_RUN_TEMPERATURE, MODEL_RUN_TOP_P


@dataclass(frozen=True)
class ModelResult:
    request_raw: dict[str, Any]
    response_raw: dict[str, Any]
    content: str


def build_request_raw(config: RuntimeConfig, model: str, prompt: str) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if config.api_key_set:
        headers["Authorization"] = "Bearer [REDACTED]"
    return {
        "schema_version": "codesetarena.api_request_raw.v1",
        "provider_api": "openai_chat_completions",
        "method": "POST",
        "url": f"{config.base_url.rstrip('/')}/chat/completions",
        "headers": headers,
        "body": {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": MODEL_RUN_TEMPERATURE,
            "top_p": MODEL_RUN_TOP_P,
            "stream": False,
        },
    }


def mock_completion(
    *, config: RuntimeConfig, run_id: str, model: str, prompt: str, content: str, created_at: str
) -> ModelResult:
    request_raw = build_request_raw(config, model, prompt)
    response_raw = {
        "schema_version": "codesetarena.api_response_raw.v1",
        "provider_api": "local_mock_openai_chat_completions",
        "id": run_id,
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
        "usage": {
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        },
    }
    return ModelResult(request_raw=request_raw, response_raw=response_raw, content=content)


def real_completion(*, config: RuntimeConfig, model: str, prompt: str, timeout: float = 60.0) -> ModelResult:
    if not config.api_key:
        raise RuntimeError("API_KEY 未设置，无法执行真实模型测试")
    request_raw = build_request_raw(config, model, prompt)
    body = json.dumps(request_raw["body"], ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        request_raw["url"],
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (TimeoutError, socket.timeout) as exc:
        raise RuntimeError(f"真实模型请求超时：超过 {timeout:g} 秒未返回") from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"真实模型请求失败：HTTP {exc.code} {_redact_secrets(detail, config.api_key)[:300]}") from exc
    except urllib.error.URLError as exc:
        reason = _redact_secrets(str(exc.reason), config.api_key)
        raise RuntimeError(f"真实模型请求失败：{reason}") from exc
    payload.setdefault("schema_version", "codesetarena.api_response_raw.v1")
    payload.setdefault("provider_api", "real_openai_chat_completions")
    payload.setdefault("created_at", int(time.time()))
    choices = payload.get("choices") or []
    content = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        content = str(message.get("content", ""))
    return ModelResult(request_raw=request_raw, response_raw=payload, content=content)


def _redact_secrets(text: str, api_key: str) -> str:
    redacted = text.replace(api_key, "[REDACTED]") if api_key else text
    return re.sub(r"sk-[A-Za-z0-9._-]+", "[REDACTED]", redacted)
