import io
import json
import tarfile

import pytest

from codesetarena.packages import PackageError, read_package, write_package


def test_read_package_ignores_macos_metadata_and_extra_files(tmp_path):
    source = tmp_path / "source.tar.gz"
    write_package(
        source,
        role="student",
        stage="stage1",
        kind="problems",
        student_number="1001",
        payload={"student": {"student_number": "1001"}, "problems": []},
    )
    manifest, payload = read_package(source)
    packed = tmp_path / "with-extra.tar.gz"
    with tarfile.open(packed, "w:gz") as tar:
        manifest_bytes = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        payload_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        for name, data in [
            ("manifest.json", manifest_bytes),
            ("payload.json", payload_bytes),
            (".DS_Store", b"metadata"),
            ("__MACOSX/._payload.json", b"metadata"),
            ("notes.txt", b"extra teacher note"),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))

    read_manifest, read_payload = read_package(packed)

    assert read_manifest["student_number"] == "1001"
    assert read_payload["student"]["student_number"] == "1001"


def test_read_package_rejects_unsafe_special_tar_members(tmp_path):
    archive = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = b"{}"
        manifest = json.dumps({"payload_sha256": ""}).encode("utf-8")
        for name, data in [("manifest.json", manifest), ("payload.json", payload)]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        fifo = tarfile.TarInfo("unsafe-fifo")
        fifo.type = tarfile.FIFOTYPE
        tar.addfile(fifo)

    with pytest.raises(PackageError, match="unsafe archive member"):
        read_package(archive)
