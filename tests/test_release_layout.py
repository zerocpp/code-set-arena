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


def test_deploy_packages_do_not_ship_model_env_examples():
    local_script = (ROOT / "scripts/build-local-release.sh").read_text(encoding="utf-8")
    student_compose = (ROOT / "deploy/student/docker-compose.yml").read_text(encoding="utf-8")
    teacher_compose = (ROOT / "deploy/teacher/docker-compose.yml").read_text(encoding="utf-8")

    assert not (ROOT / "deploy/student/.env.example").exists()
    assert not (ROOT / "deploy/teacher/.env.example").exists()
    assert ".env.example" not in local_script
    assert "env_file:" not in student_compose
    assert "env_file:" not in teacher_compose


def test_student_and_teacher_dockerfiles_keep_dependency_layer_before_source():
    for name in ["student", "teacher"]:
        dockerfile = (ROOT / f"docker/{name}/Dockerfile").read_text(encoding="utf-8")
        assert "COPY requirements.txt /app/" in dockerfile
        assert "RUN python -m pip install --no-cache-dir -r requirements.txt" in dockerfile
        assert dockerfile.index("COPY requirements.txt /app/") < dockerfile.index("COPY src /app/src")
        assert "RUN python -m pip install --no-cache-dir --no-deps ." in dockerfile
