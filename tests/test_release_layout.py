from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_scripts_write_to_versioned_dist_directory():
    local_script = (ROOT / "scripts/build-local-release.sh").read_text(encoding="utf-8")
    offline_script = (ROOT / "scripts/prepare_docker_offline_bundle_v714.py").read_text(
        encoding="utf-8"
    )
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert 'DIST_ROOT="dist"' in local_script
    assert 'DIST_DIR="${DIST_ROOT}/${VERSION_TAG}"' in local_script
    assert 'DIST_DIR = REPO_ROOT / "dist" / VERSION' in offline_script
    assert "[环境安装手册](docs/环境安装手册/环境安装手册.md)" in readme
    assert "[系统使用手册](docs/系统使用手册/系统使用手册.md)" in readme
    assert "linux-amd64" in readme
    assert "linux-arm64" in readme


def test_local_release_packages_do_not_bundle_markdown_or_pdf_manuals():
    local_script = (ROOT / "scripts/build-local-release.sh").read_text(encoding="utf-8")

    assert "STUDENT_MANUAL" not in local_script
    assert "TEACHER_MANUAL" not in local_script
    assert "CLI_MANUAL" not in local_script
    assert "RELEASE_NOTES" not in local_script
    assert "deploy/student/README.md" not in local_script
    assert "deploy/teacher/README.md" not in local_script
    assert "--exclude='*.md'" in local_script
    assert "--exclude='*.pdf'" in local_script


def test_deploy_env_examples_use_placeholders_for_user_supplied_api_settings():
    student_env = (ROOT / "deploy/student/.env.example").read_text(encoding="utf-8")
    teacher_env = (ROOT / "deploy/teacher/.env.example").read_text(encoding="utf-8")

    for payload in [student_env, teacher_env]:
        assert "BASE_URL=https://your-model-service-base-url.example.com" in payload
        assert "API_KEY=" in payload
        assert "API_KEY=sk-" not in payload
