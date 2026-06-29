"""Prepare offline Docker installers and CodeSetArena local packages for v7.1.2."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import shutil
import tarfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

VERSION = "v7.1.2"
DEFAULT_PACKAGE_PLATFORM = "linux-amd64"
REPO_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = REPO_ROOT / "dist" / VERSION
DEFAULT_OUTPUT = DIST_DIR / f"docker-offline-{VERSION}"


@dataclass(frozen=True)
class Asset:
    key: str
    label: str
    url: str
    relative_path: str
    source: str
    required: bool = True


DOCKER_DESKTOP_ASSETS = [
    Asset(
        "docker-desktop-macos-arm64",
        "Docker Desktop for macOS Apple Silicon",
        "https://desktop.docker.com/mac/main/arm64/Docker.dmg",
        "installers/macos/apple-silicon/Docker.dmg",
        "Docker official desktop.docker.com",
    ),
    Asset(
        "docker-desktop-macos-amd64",
        "Docker Desktop for macOS Intel",
        "https://desktop.docker.com/mac/main/amd64/Docker.dmg",
        "installers/macos/intel/Docker.dmg",
        "Docker official desktop.docker.com",
    ),
    Asset(
        "docker-desktop-windows-amd64",
        "Docker Desktop for Windows AMD64",
        "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe",
        "installers/windows/amd64/Docker Desktop Installer.exe",
        "Docker official desktop.docker.com",
    ),
    Asset(
        "docker-desktop-windows-arm64",
        "Docker Desktop for Windows ARM64",
        "https://desktop.docker.com/win/main/arm64/Docker%20Desktop%20Installer.exe",
        "installers/windows/arm64/Docker Desktop Installer.exe",
        "Docker official desktop.docker.com",
    ),
    Asset(
        "docker-desktop-linux-ubuntu-amd64",
        "Docker Desktop DEB for Ubuntu/Debian AMD64",
        "https://desktop.docker.com/linux/main/amd64/docker-desktop-amd64.deb",
        "installers/linux/ubuntu-amd64/docker-desktop-amd64.deb",
        "Docker official desktop.docker.com",
    ),
]


def request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "CodeSetArena-offline-bundler"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def latest_wsl_assets() -> list[Asset]:
    release = request_json("https://api.github.com/repos/microsoft/WSL/releases/latest")
    assets = release.get("assets", [])
    out: list[Asset] = []
    for suffix, arch in [(".x64.msi", "x64"), (".arm64.msi", "arm64")]:
        matches = [item for item in assets if str(item.get("name", "")).lower().endswith(suffix)]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one WSL asset ending with {suffix}, got {len(matches)}")
        item = matches[0]
        out.append(
            Asset(
                key=f"wsl-msi-{arch}",
                label=f"Microsoft WSL MSI for Windows {arch}",
                url=str(item["browser_download_url"]),
                relative_path=f"installers/windows/wsl/{item['name']}",
                source=f"microsoft/WSL GitHub release {release.get('tag_name')}",
            )
        )
    return out


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(asset: Asset, output_root: Path, skip_download: bool) -> dict[str, Any]:
    target = output_root / asset.relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    if skip_download:
        status = "planned"
    elif target.exists() and target.stat().st_size > 0:
        status = "exists"
    else:
        status = "downloaded"
        tmp = target.with_suffix(target.suffix + ".part")
        resume_from = tmp.stat().st_size if tmp.exists() else 0
        headers = {"User-Agent": "CodeSetArena-offline-bundler"}
        if resume_from:
            headers["Range"] = f"bytes={resume_from}-"
        print(f"downloading {asset.label} -> {target}", flush=True)
        request = urllib.request.Request(asset.url, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            status_code = getattr(response, "status", 200)
            if resume_from and status_code == 206:
                mode = "ab"
                received = resume_from
                size = int(response.headers.get("Content-Length", "0") or "0") + resume_from
                print(f"  resume from {resume_from / 1024 / 1024:.1f} MiB", flush=True)
            else:
                mode = "wb"
                received = 0
                size = int(response.headers.get("Content-Length", "0") or "0")
                if resume_from:
                    print("  server did not resume; restarting this file", flush=True)
            with tmp.open(mode) as handle:
                _read_response_to_file(response, handle, received, size)
        tmp.replace(target)

    size_bytes = target.stat().st_size if target.exists() else None
    sha256 = sha256_file(target) if target.exists() else None
    return {
        "key": asset.key,
        "label": asset.label,
        "url": asset.url,
        "source": asset.source,
        "relative_path": asset.relative_path,
        "status": status,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "seconds": round(time.time() - started, 2),
    }


def _read_response_to_file(response: Any, handle: Any, received: int, size: int) -> None:
    last_print = 0.0
    while True:
        chunk = response.read(1024 * 1024)
        if not chunk:
            break
        handle.write(chunk)
        received += len(chunk)
        now = time.time()
        if now - last_print >= 5:
            if size:
                percent = received / size * 100
                print(
                    f"  {received / 1024 / 1024:.1f} MiB / {size / 1024 / 1024:.1f} MiB ({percent:.1f}%)",
                    flush=True,
                )
            else:
                print(f"  {received / 1024 / 1024:.1f} MiB", flush=True)
            last_print = now


def copy_course_package(source: Path, output_root: Path, relative_path: str) -> dict[str, Any]:
    target = output_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {
        "key": target.stem,
        "label": target.name,
        "url": "",
        "source": str(source),
        "relative_path": relative_path,
        "status": "copied",
        "size_bytes": target.stat().st_size,
        "sha256": sha256_file(target),
        "seconds": 0,
    }


def write_linux_scripts(output_root: Path) -> None:
    scripts_dir = output_root / "installers/linux/ubuntu-engine-debs"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    (scripts_dir / "collect-ubuntu-engine-debs.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail

# 在一台能联网、且 Ubuntu 版本/CPU 架构与离线机器一致的电脑上运行。
# 运行后，把当前目录下的 deb 文件和 install-ubuntu-engine-debs.sh 一起拷到离线机器。

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg apt-transport-https

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

. /etc/os-release
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update

mkdir -p debs
cd debs
packages=(docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin)
apt-cache depends --recurse --no-recommends --no-suggests --no-conflicts --no-breaks --no-replaces --no-enhances "${packages[@]}" \\
  | awk '/^[A-Za-z0-9_.+-]+$/ {print $1}' \\
  | sort -u \\
  | xargs -r apt-get download
apt-get download "${packages[@]}"
sha256sum ./*.deb > SHA256SUMS.txt
echo "Downloaded debs to $(pwd)"
""",
        encoding="utf-8",
    )
    (scripts_dir / "install-ubuntu-engine-debs.sh").write_text(
        """#!/usr/bin/env bash
set -euo pipefail

# 在离线 Ubuntu 机器上运行。本目录应包含 collect 脚本下载好的 debs/*.deb。

cd "$(dirname "$0")"
if [ ! -d debs ]; then
  echo "Missing debs directory. Run collect-ubuntu-engine-debs.sh on a matching online Ubuntu machine first." >&2
  exit 1
fi
if [ -f debs/SHA256SUMS.txt ]; then
  (cd debs && sha256sum -c SHA256SUMS.txt)
fi
sudo dpkg -i debs/*.deb || {
  echo "dpkg reported missing dependencies. The offline deb set is incomplete for this Ubuntu release/architecture." >&2
  exit 1
}
sudo systemctl enable --now docker
docker version
docker compose version
echo "If docker requires sudo, run: sudo usermod -aG docker $USER, then log out and log in again."
""",
        encoding="utf-8",
    )
    (scripts_dir / "README.md").write_text(
        """# Ubuntu Docker Engine 离线依赖包

Docker Desktop 的 Linux DEB 不一定适合所有教学机。对 Ubuntu 22.04/24.04/26.04，建议在一台同版本、同架构、可联网的 Ubuntu 机器上运行：

```bash
./collect-ubuntu-engine-debs.sh
```

然后把整个 `ubuntu-engine-debs/` 目录拷贝到离线机器，运行：

```bash
./install-ubuntu-engine-debs.sh
```

注意：离线机器的 Ubuntu 版本和 CPU 架构必须与收集依赖包的机器一致，否则 deb 依赖可能不匹配。
""",
        encoding="utf-8",
    )
    for script in scripts_dir.glob("*.sh"):
        script.chmod(0o755)


def write_bundle_readme(output_root: Path, records: list[dict[str, Any]]) -> None:
    readme = f"""# CodeSetArena Docker 离线安装包 {VERSION}

本目录用于网络较差或无法访问 Docker Hub 的学生/助教电脑。请优先按系统选择本地安装包，不要让每位学生现场重新下载。

## 目录结构

```text
installers/
  macos/apple-silicon/Docker.dmg
  macos/intel/Docker.dmg
  windows/amd64/Docker Desktop Installer.exe
  windows/arm64/Docker Desktop Installer.exe
  windows/wsl/*.msi
  linux/ubuntu-amd64/docker-desktop-amd64.deb
  linux/ubuntu-engine-debs/*.sh
codesetarena/
  codesetarena-local-{VERSION}-universal.tar.gz
  codesetarena-student-local-{VERSION}-linux-amd64.tar.gz
  codesetarena-teacher-local-{VERSION}-linux-amd64.tar.gz
manifest.json
SHA256SUMS.txt
```

## 安装前先校验

macOS/Linux:

```bash
shasum -a 256 -c SHA256SUMS.txt
```

Windows PowerShell:

```powershell
Get-FileHash "installers\\windows\\amd64\\Docker Desktop Installer.exe" -Algorithm SHA256
```

将输出值与 `SHA256SUMS.txt` 中对应文件比对。

## macOS

Apple Silicon 机器使用 `installers/macos/apple-silicon/Docker.dmg`；Intel 机器使用 `installers/macos/intel/Docker.dmg`。双击 DMG 后把 Docker 拖到 Applications，启动 Docker Desktop，菜单栏 Docker 图标稳定后执行：

```bash
docker version
docker compose version
```

## Windows

AMD64 机器运行 `installers\\windows\\amd64\\Docker Desktop Installer.exe`；ARM64 机器运行 `installers\\windows\\arm64\\Docker Desktop Installer.exe`。

如果提示需要 WSL 2，请用管理员 PowerShell 执行：

```powershell
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
```

然后重启，双击 `installers\\windows\\wsl\\*.msi` 安装 WSL，再启动 Docker Desktop。

## Linux

Ubuntu 桌面用户可尝试：

```bash
sudo apt install ./installers/linux/ubuntu-amd64/docker-desktop-amd64.deb
```

如果离线机器缺依赖，请改用 `installers/linux/ubuntu-engine-debs/` 的两步脚本：先在同版本同架构的联网 Ubuntu 上收集 deb，再在离线机器安装。

## CodeSetArena 镜像

学生端和助教端本地交付包在 `codesetarena/` 目录。Windows WSL 2 和普通 x86_64 Linux 使用 `linux-amd64`；Apple Silicon 或 ARM64 Linux 可使用通用包中的 `linux-arm64` 版本。先确认 Docker Server 架构：

```bash
docker version --format '{{.Server.Os}}/{{.Server.Arch}}'
```

安装 Docker 后，学生端示例：

```bash
tar -xzf codesetarena/codesetarena-student-local-{VERSION}-linux-amd64.tar.gz
cd codesetarena-student-local-{VERSION}-linux-amd64
docker load -i codesetarena-student-{VERSION}.image.tar
docker compose up -d
```

助教端同理使用 `codesetarena-teacher-local-{VERSION}-linux-amd64.tar.gz`。

## 许可提醒

Docker Desktop 对教育用途免费，但仍应遵守 Docker Desktop Subscription Service Agreement。课程分发安装包前，请确认使用场景符合 Docker 的许可条款。
"""
    output_root.joinpath("README.md").write_text(readme, encoding="utf-8")

    sha_lines = []
    for record in records:
        if record.get("sha256"):
            sha_lines.append(f"{record['sha256']}  {record['relative_path']}")
    output_root.joinpath("SHA256SUMS.txt").write_text("\n".join(sha_lines) + "\n", encoding="utf-8")


def create_tarball(output_root: Path) -> Path:
    tar_path = DIST_DIR / f"codesetarena-docker-offline-{VERSION}.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
    def exclude_partial(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        return None if info.name.endswith(".part") else info

    with tarfile.open(tar_path, "w:gz") as archive:
        archive.add(output_root, arcname=output_root.name, filter=exclude_partial)
    return tar_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-download", action="store_true", help="Only write manifests and helper scripts")
    parser.add_argument("--no-wsl", action="store_true", help="Do not resolve or download Microsoft WSL MSI assets")
    parser.add_argument("--no-archive", action="store_true", help="Do not create the final tar.gz bundle")
    parser.add_argument("--workers", type=int, default=4, help="Concurrent installer downloads")
    args = parser.parse_args()

    output_root = args.output
    output_root.mkdir(parents=True, exist_ok=True)
    write_linux_scripts(output_root)

    assets = list(DOCKER_DESKTOP_ASSETS)
    if not args.no_wsl:
        assets.extend(latest_wsl_assets())

    records: list[dict[str, Any]] = []
    if args.skip_download or args.workers <= 1:
        for asset in assets:
            records.append(download(asset, output_root, args.skip_download))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(download, asset, output_root, False): asset for asset in assets}
            for future in as_completed(futures):
                records.append(future.result())

    platform = DEFAULT_PACKAGE_PLATFORM
    course_packages = [
        (
            DIST_DIR / f"codesetarena-local-{VERSION}-universal.tar.gz",
            f"codesetarena/codesetarena-local-{VERSION}-universal.tar.gz",
        ),
        (
            DIST_DIR / f"codesetarena-student-local-{VERSION}-{platform}.tar.gz",
            f"codesetarena/codesetarena-student-local-{VERSION}-{platform}.tar.gz",
        ),
        (
            DIST_DIR / f"codesetarena-teacher-local-{VERSION}-{platform}.tar.gz",
            f"codesetarena/codesetarena-teacher-local-{VERSION}-{platform}.tar.gz",
        ),
    ]
    for source, relative_path in course_packages:
        if source.exists():
            records.append(copy_course_package(source, output_root, relative_path))
        else:
            print(f"warning: missing course package {source}")

    manifest = {
        "schema": "codesetarena.docker_offline_bundle.v7.1",
        "version": VERSION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "assets": records,
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_bundle_readme(output_root, records)

    print(output_root)
    if not args.no_archive:
        print(create_tarball(output_root))


if __name__ == "__main__":
    main()
