from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_scripts_write_to_versioned_dist_directory():
    local_script = (ROOT / "scripts/build-local-release.sh").read_text(encoding="utf-8")
    offline_script = (ROOT / "scripts/prepare_docker_offline_bundle_v713.py").read_text(
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
