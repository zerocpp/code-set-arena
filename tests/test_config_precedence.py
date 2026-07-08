from fastapi.testclient import TestClient

from codesetarena.config import load_runtime_config, update_local_api_key
from codesetarena.storage import default_student_state, default_teacher_state, load_teacher_state
from codesetarena.student_app import create_student_app
from codesetarena.student_app import _effective_settings as student_effective_settings
from codesetarena.teacher_app import create_teacher_app
from codesetarena.teacher_app import _effective_settings as teacher_effective_settings
from codesetarena.teacher_eval import _effective_base_url, _effective_models


def test_runtime_config_ignores_container_environment_and_parent_env(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-container-secret")
    monkeypatch.setenv("BASE_URL", "https://container.example.test")
    monkeypatch.setenv("MODELS", "container-model-a|container-model-b")
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "API_KEY=sk-parent-secret",
                "BASE_URL=https://parent.example.test",
                "MODELS=parent-model-a|parent-model-b",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    runtime = load_runtime_config(tmp_path / "student-data")

    assert runtime.api_key == ""
    assert runtime.base_url == ""
    assert runtime.models == []
    assert runtime.api_key_source == "未设置"


def test_runtime_config_reads_only_data_dir_api_key_saved_by_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("API_KEY", "sk-container-secret")

    result = update_local_api_key(tmp_path, "sk-local-secret")
    runtime = load_runtime_config(tmp_path)

    assert result == "saved"
    assert runtime.api_key == "sk-local-secret"
    assert runtime.base_url == ""
    assert runtime.models == []
    assert runtime.api_key_source == str(tmp_path / ".env")


def test_default_web_settings_are_empty_until_user_saves(tmp_path, monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://container.example.test")
    monkeypatch.setenv("MODELS", "container-model-a|container-model-b")

    student_settings = student_effective_settings(default_student_state(), tmp_path / "student")
    teacher_settings = teacher_effective_settings(default_teacher_state(), tmp_path / "teacher")

    assert student_settings["base_url"] == ""
    assert student_settings["models"] == []
    assert teacher_settings["base_url"] == ""
    assert teacher_settings["models"] == []
    assert _effective_base_url(default_teacher_state(), tmp_path / "teacher") == ""
    assert _effective_models(default_teacher_state(), tmp_path / "teacher") == []


def test_settings_page_requires_base_url_api_key_and_models(tmp_path):
    student = TestClient(create_student_app(tmp_path / "student"))
    teacher = TestClient(create_teacher_app(tmp_path / "teacher"))

    student_response = student.post(
        "/settings",
        data={"base_url": "", "api_key": "", "models": [""]},
        follow_redirects=True,
    )
    teacher_response = teacher.post(
        "/settings",
        data={"course_name": "CodeSetArena v7", "base_url": "", "api_key": "", "models": [""]},
        follow_redirects=True,
    )

    assert "Base URL 不能为空" in student_response.text
    assert "Base URL 不能为空" in teacher_response.text


def test_default_teacher_allowed_student_versions_whitelist_contains_current_version(tmp_path):
    teacher = TestClient(create_teacher_app(tmp_path / "teacher"))

    page = teacher.get("/settings")
    state = load_teacher_state(tmp_path / "teacher")

    assert "合法学生端版本号白名单" in page.text
    assert state["settings"]["allowed_student_versions"] == ["v7.1.9", "v7.1.8", "v7.1.7", "v7.1.3"]
