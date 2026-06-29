"""Archive package read/write helpers for CodeSetArena v7."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .constants import APP_NAME, VERSION_TAG


class PackageError(ValueError):
    """Raised when a package is malformed or unsafe."""


def write_package(
    output_path: Path,
    *,
    role: str,
    stage: str,
    kind: str,
    payload: dict[str, Any],
    student_number: str | None = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codesetarena-package-") as temp_name:
        root = Path(temp_name)
        manifest = {
            "schema_version": "codesetarena.package.v1",
            "benchmark_name": APP_NAME,
            "system_display_name": APP_NAME,
            "version_tag": VERSION_TAG,
            "package_role": role,
            "package_stage": stage,
            "package_kind": kind,
            "student_number": student_number or "",
            "created_at": datetime.now(UTC).isoformat(),
        }
        payload_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        manifest["payload_sha256"] = hashlib.sha256(payload_bytes).hexdigest()
        (root / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (root / "payload.json").write_bytes(payload_bytes)
        _write_tar(root, output_path)
    return output_path


def read_package(archive_path: Path, extract_to: Path | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    if archive_path.suffixes[-2:] != [".tar", ".gz"]:
        raise PackageError("package must be a .tar.gz archive")
    target = extract_to or Path(tempfile.mkdtemp(prefix="codesetarena-read-"))
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    _extract_tar(archive_path, target)
    manifest_path = target / "manifest.json"
    payload_path = target / "payload.json"
    if not manifest_path.exists() or not payload_path.exists():
        raise PackageError("package missing manifest.json or payload.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload_bytes = payload_path.read_bytes()
    expected_hash = manifest.get("payload_sha256")
    actual_hash = hashlib.sha256(payload_bytes).hexdigest()
    if expected_hash and expected_hash != actual_hash:
        raise PackageError("payload hash mismatch")
    payload = json.loads(payload_bytes.decode("utf-8"))
    return manifest, payload


def write_bundle(
    output_path: Path, archives: list[Path], bundle_manifest: dict[str, Any] | None = None
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as tar:
        if bundle_manifest is not None:
            manifest_bytes = json.dumps(
                bundle_manifest, ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8")
            info = tarfile.TarInfo("bundle-manifest.json")
            info.size = len(manifest_bytes)
            tar.addfile(info, io.BytesIO(manifest_bytes))
        for archive in archives:
            tar.add(archive, arcname=archive.name)
    return output_path


def _write_tar(root: Path, output_path: Path) -> None:
    with tarfile.open(output_path, "w:gz") as tar:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(root))


def _extract_tar(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            target = destination / member.name
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise PackageError("unsafe archive member") from exc
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise PackageError("unsafe archive member")
        tar.extractall(destination)
