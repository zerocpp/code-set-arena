"""Runtime configuration saved by the local CodeSetArena settings pages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

API_KEY_MIN_LENGTH = 8
MASKED_API_KEY = "******"


@dataclass(frozen=True)
class RuntimeConfig:
    base_url: str
    api_key: str
    models: list[str]
    env_file: Path | None
    api_key_source_label: str | None = None

    @property
    def default_model(self) -> str:
        return self.models[0] if self.models else ""

    @property
    def api_key_set(self) -> bool:
        return bool(self.api_key)

    @property
    def api_key_source(self) -> str:
        if not self.api_key:
            return "未设置"
        if self.api_key_source_label:
            return self.api_key_source_label
        if self.env_file is not None:
            return str(self.env_file)
        return "运行时配置"


def parse_models(raw: str | list[str] | None) -> list[str]:
    if isinstance(raw, list):
        parsed = [model.strip() for model in raw if model and model.strip()]
    else:
        parsed = [model.strip() for model in str(raw or "").replace("\n", "|").split("|")]
        parsed = [model for model in parsed if model]
    return parsed


def validate_api_key(api_key: str) -> None:
    value = api_key.strip()
    if not value:
        return
    if not value.startswith("sk-") or len(value) < API_KEY_MIN_LENGTH:
        raise ValueError("API Key 格式不合法：应以 sk- 开头，且至少 8 个字符")


def validate_base_url(base_url: str) -> None:
    value = base_url.strip()
    if not value:
        raise ValueError("Base URL 不能为空")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Base URL 格式不合法，请填写 http:// 或 https:// 开头的模型服务地址")


def require_models(models: list[str]) -> None:
    if not models:
        raise ValueError("模型列表不能为空，请至少填写一个模型名称")


def update_local_api_key(
    data_dir: Path,
    api_key: str,
    *,
    clear: bool = False,
    empty_clears: bool = False,
) -> str:
    value = api_key.strip()
    if value == MASKED_API_KEY:
        return "unchanged"
    if clear and value:
        raise ValueError("不能同时填写 API Key 并勾选清空 API Key")
    if value:
        validate_api_key(value)
    env_path = data_dir / ".env"
    values = _read_env_file(env_path) if env_path.exists() else {}
    if clear:
        values["API_KEY"] = ""
        _write_env_file(env_path, values)
        return "cleared"
    if value:
        values["API_KEY"] = value
        _write_env_file(env_path, values)
        return "saved"
    if empty_clears:
        values["API_KEY"] = ""
        _write_env_file(env_path, values)
        return "cleared"
    return "unchanged"


def load_runtime_config(data_dir: Path | None = None, env_file: Path | None = None) -> RuntimeConfig:
    del env_file
    selected_env = data_dir / ".env" if data_dir is not None and (data_dir / ".env").exists() else None
    file_values = _read_env_file(selected_env) if selected_env else {}
    base_url = ""
    api_key = file_values.get("API_KEY", "").strip()
    models: list[str] = []
    return RuntimeConfig(
        base_url=base_url,
        api_key=api_key,
        models=models,
        env_file=selected_env,
        api_key_source_label=str(selected_env) if selected_env is not None and api_key else None,
    )


def settings_are_configured(settings: dict[str, object] | None) -> bool:
    if not isinstance(settings, dict):
        return False
    base_url = str(settings.get("base_url") or "").strip()
    models = settings.get("models") or []
    return bool(settings.get("configured")) and bool(base_url) and isinstance(models, list) and bool(models)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{key}={value}" for key, value in values.items()]
    path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")
