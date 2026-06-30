from codesetarena.config import load_runtime_config, update_local_api_key
from codesetarena.constants import DEFAULT_BASE_URL, DEFAULT_MODELS
from codesetarena.storage import default_student_state, default_teacher_state
from codesetarena.student_app import _effective_settings as student_effective_settings
from codesetarena.teacher_app import _effective_settings as teacher_effective_settings
from codesetarena.teacher_eval import _effective_base_url, _effective_models


def test_data_dir_env_overrides_container_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-container-secret")
    monkeypatch.setenv("BASE_URL", "https://container.example.test")
    monkeypatch.setenv("MODELS", "container-model-a|container-model-b")
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "API_KEY=sk-local-secret",
                "BASE_URL=https://local.example.test",
                "MODELS=local-model-a|local-model-b",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    runtime = load_runtime_config(tmp_path)

    assert runtime.api_key == "sk-local-secret"
    assert runtime.base_url == "https://local.example.test"
    assert runtime.models == ["local-model-a", "local-model-b"]


def test_empty_local_api_key_clears_container_environment_key(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-container-secret")

    result = update_local_api_key(tmp_path, "", empty_clears=True)
    runtime = load_runtime_config(tmp_path)

    assert result == "cleared"
    assert runtime.api_key == ""
    assert runtime.api_key_source == "未设置"


def test_saved_student_settings_override_container_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://container.example.test")
    monkeypatch.setenv("MODELS", "container-model-a|container-model-b")
    state = default_student_state()
    state["settings"]["configured"] = True
    state["settings"]["base_url"] = DEFAULT_BASE_URL
    state["settings"]["models"] = list(DEFAULT_MODELS)

    settings = student_effective_settings(state, tmp_path)

    assert settings["base_url"] == DEFAULT_BASE_URL
    assert settings["models"] == DEFAULT_MODELS


def test_saved_teacher_settings_override_container_defaults_for_eval(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://container.example.test")
    monkeypatch.setenv("MODELS", "container-model-a|container-model-b")
    state = default_teacher_state()
    state["settings"]["configured"] = True
    state["settings"]["base_url"] = DEFAULT_BASE_URL
    state["settings"]["models"] = list(DEFAULT_MODELS)

    settings = teacher_effective_settings(state, tmp_path)

    assert settings["base_url"] == DEFAULT_BASE_URL
    assert settings["models"] == DEFAULT_MODELS
    assert _effective_base_url(state, tmp_path) == DEFAULT_BASE_URL
    assert _effective_models(state, tmp_path) == DEFAULT_MODELS


def test_container_environment_initializes_settings_before_page_save(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://container.example.test")
    monkeypatch.setenv("MODELS", "container-model-a|container-model-b")

    student_settings = student_effective_settings(default_student_state(), tmp_path)
    teacher_settings = teacher_effective_settings(default_teacher_state(), tmp_path)

    assert student_settings["base_url"] == "https://container.example.test"
    assert student_settings["models"] == ["container-model-a", "container-model-b"]
    assert teacher_settings["base_url"] == "https://container.example.test"
    assert teacher_settings["models"] == ["container-model-a", "container-model-b"]
