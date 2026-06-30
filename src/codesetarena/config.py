"""Runtime configuration loaded from environment variables and .env files."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .constants import DEFAULT_BASE_URL, DEFAULT_MODELS

ENV_FILE_ENV = "CODESETARENA_ENV_FILE"
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
        return self.models[0] if self.models else DEFAULT_MODELS[0]

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
        if os.environ.get("API_KEY"):
            return "环境变量 API_KEY"
        return "运行时配置"


def parse_models(raw: str | list[str] | None) -> list[str]:
    if isinstance(raw, list):
        parsed = [model.strip() for model in raw if model and model.strip()]
    else:
        parsed = [model.strip() for model in str(raw or "").replace("\n", "|").split("|")]
        parsed = [model for model in parsed if model]
    return parsed or list(DEFAULT_MODELS)


def validate_api_key(api_key: str) -> None:
    value = api_key.strip()
    if not value:
        return
    if not value.startswith("sk-") or len(value) < API_KEY_MIN_LENGTH:
        raise ValueError("API Key 格式不合法：应以 sk- 开头，且至少 8 个字符")


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
    selected_env = _select_env_file(data_dir, env_file)
    file_values = _read_env_file(selected_env) if selected_env else {}
    file_overrides_environment = _file_overrides_environment(data_dir, env_file, selected_env)
    base_url = (
        _choose_config_value("BASE_URL", file_values, DEFAULT_BASE_URL, file_overrides_environment)
        or DEFAULT_BASE_URL
    ).rstrip("/")
    api_key = _choose_config_value("API_KEY", file_values, "", file_overrides_environment).strip()
    models = parse_models(
        _choose_config_value("MODELS", file_values, DEFAULT_MODELS, file_overrides_environment)
    )
    return RuntimeConfig(
        base_url=base_url,
        api_key=api_key,
        models=models,
        env_file=selected_env,
        api_key_source_label=_config_source_label(
            "API_KEY", file_values, selected_env, file_overrides_environment
        ),
    )


def settings_are_configured(settings: dict[str, object] | None) -> bool:
    if not isinstance(settings, dict):
        return False
    base_url = str(settings.get("base_url") or "")
    models = settings.get("models") or []
    has_non_default_values = base_url not in {"", DEFAULT_BASE_URL} or (
        isinstance(models, list) and models != DEFAULT_MODELS
    )
    if "configured" in settings:
        return bool(settings.get("configured")) or has_non_default_values
    return has_non_default_values


def _choose_config_value(
    name: str,
    file_values: dict[str, str],
    default: str | list[str],
    file_overrides_environment: bool,
) -> str | list[str]:
    if file_overrides_environment and name in file_values:
        return file_values[name]
    env_value = os.environ.get(name)
    if env_value is not None:
        return env_value
    if name in file_values:
        return file_values[name]
    return default


def _config_source_label(
    name: str,
    file_values: dict[str, str],
    selected_env: Path | None,
    file_overrides_environment: bool,
) -> str | None:
    if file_overrides_environment and name in file_values:
        return str(selected_env) if selected_env is not None and file_values[name].strip() else None
    if os.environ.get(name):
        return f"环境变量 {name}"
    if name in file_values:
        return str(selected_env) if selected_env is not None and file_values[name].strip() else None
    return None


def _file_overrides_environment(
    data_dir: Path | None, env_file: Path | None, selected_env: Path | None
) -> bool:
    if selected_env is None:
        return False
    if env_file is not None or os.environ.get(ENV_FILE_ENV):
        return True
    return data_dir is not None and selected_env == data_dir / ".env"


def _select_env_file(data_dir: Path | None, env_file: Path | None) -> Path | None:
    explicit = env_file or (Path(os.environ[ENV_FILE_ENV]).expanduser() if os.environ.get(ENV_FILE_ENV) else None)
    if explicit is not None:
        return explicit if explicit.exists() else None
    if data_dir is not None:
        data_env = data_dir / ".env"
        if data_env.exists():
            return data_env
    for root in [Path.cwd(), *Path.cwd().parents]:
        candidate = root / ".env"
        if candidate.exists():
            return candidate
    return None


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
