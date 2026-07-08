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
from .model_run_utils import response_final_text


@dataclass(frozen=True)
class ModelResult:
    request_raw: dict[str, Any]
    response_raw: dict[str, Any]
    content: str


class ModelAPIError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        request_raw: dict[str, Any] | None = None,
        response_raw: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.request_raw = request_raw or {}
        self.response_raw = response_raw or {}


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


def real_completion(*, config: RuntimeConfig, model: str, prompt: str, timeout: float = 60.0) -> ModelResult:
    request_raw = build_request_raw(config, model, prompt)
    if not config.base_url.strip():
        raise ModelAPIError("Base URL 未设置，无法执行真实模型测试", request_raw=request_raw)
    if not config.api_key:
        raise ModelAPIError("API Key 未设置，无法执行真实模型测试", request_raw=request_raw)
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
        response_raw = _error_response_raw("timeout", f"超过 {timeout:g} 秒未返回")
        raise ModelAPIError(
            f"真实模型请求超时：超过 {timeout:g} 秒未返回",
            request_raw=request_raw,
            response_raw=response_raw,
        ) from exc
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        redacted = _redact_secrets(detail, config.api_key)
        response_raw = _error_response_raw("http_error", redacted, status_code=exc.code)
        raise ModelAPIError(
            f"真实模型请求失败：HTTP {exc.code} {redacted[:300]}",
            request_raw=request_raw,
            response_raw=response_raw,
        ) from exc
    except urllib.error.URLError as exc:
        reason = _redact_secrets(str(exc.reason), config.api_key)
        response_raw = _error_response_raw("url_error", reason)
        raise ModelAPIError(
            f"真实模型请求失败：{reason}",
            request_raw=request_raw,
            response_raw=response_raw,
        ) from exc
    payload.setdefault("schema_version", "codesetarena.api_response_raw.v1")
    payload.setdefault("provider_api", "real_openai_chat_completions")
    payload.setdefault("created_at", int(time.time()))
    content = response_final_text(payload)
    return ModelResult(request_raw=request_raw, response_raw=payload, content=content)


def _redact_secrets(text: str, api_key: str) -> str:
    redacted = text.replace(api_key, "[REDACTED]") if api_key else text
    return re.sub(r"sk-[A-Za-z0-9._-]+", "[REDACTED]", redacted)


def _error_response_raw(error_type: str, detail: str, *, status_code: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "codesetarena.api_response_raw.v1",
        "provider_api": "real_openai_chat_completions",
        "error_type": error_type,
        "error": detail,
    }
    if status_code is not None:
        payload["status_code"] = status_code
    return payload
