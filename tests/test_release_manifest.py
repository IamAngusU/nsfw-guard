from __future__ import annotations

import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

from scripts import release_manifest


def _artifacts(tmp_path: Path, *, version: str) -> tuple[Path, Path]:
    metadata = (f"Metadata-Version: 2.1\nName: nsfw-guard\nVersion: {version}\n\n").encode()
    wheel = tmp_path / f"nsfw_guard-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"nsfw_guard-{version}.dist-info/METADATA", metadata)
    sdist = tmp_path / f"nsfw_guard-{version}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        info = tarfile.TarInfo(f"nsfw_guard-{version}/PKG-INFO")
        info.size = len(metadata)
        archive.addfile(info, io.BytesIO(metadata))
        nested = tarfile.TarInfo(f"nsfw_guard-{version}/src/nsfw_guard.egg-info/PKG-INFO")
        nested.size = len(metadata)
        archive.addfile(nested, io.BytesIO(metadata))
    return wheel, sdist


def test_manifest_is_deterministic_and_does_not_claim_validation_passed(tmp_path: Path) -> None:
    _, version = release_manifest._source_identity(release_manifest.ROOT)
    wheel, sdist = _artifacts(tmp_path, version=version)
    later = tmp_path / "z-validation.txt"
    earlier = tmp_path / "a-validation.txt"
    later.write_text("tests failed\n", encoding="utf-8")
    earlier.write_text("build output\n", encoding="utf-8")
    first = release_manifest.build_manifest(
        root=release_manifest.ROOT,
        commit="a" * 40,
        wheel=wheel,
        sdist=sdist,
        validation_logs=[later, earlier],
    )
    second = release_manifest.build_manifest(
        root=release_manifest.ROOT,
        commit="a" * 40,
        wheel=wheel,
        sdist=sdist,
        validation_logs=[earlier, later],
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["package"] == {"name": "nsfw-guard", "version": version}
    assert first["source"] == {"git_commit": "a" * 40, "tracked_tree_clean": True}
    assert [item["filename"] for item in first["validation_evidence"]["logs"]] == [
        "a-validation.txt",
        "z-validation.txt",
    ]
    assert "passed" not in json.dumps(first).lower()
    assert first["pinned_model"]["bundled_in_distribution"] is False


def test_manifest_rejects_artifact_version_mismatch(tmp_path: Path) -> None:
    wheel, sdist = _artifacts(tmp_path, version="9.9.9")
    log = tmp_path / "validation.txt"
    log.write_text("checked\n", encoding="utf-8")
    with pytest.raises(ValueError, match="metadata must match"):
        release_manifest.build_manifest(
            root=release_manifest.ROOT,
            commit="b" * 40,
            wheel=wheel,
            sdist=sdist,
            validation_logs=[log],
        )


def test_manifest_requires_nonempty_unique_validation_logs(tmp_path: Path) -> None:
    _, version = release_manifest._source_identity(release_manifest.ROOT)
    wheel, sdist = _artifacts(tmp_path, version=version)
    empty = tmp_path / "empty.txt"
    empty.touch()
    with pytest.raises(ValueError, match="must not be empty"):
        release_manifest.build_manifest(
            root=release_manifest.ROOT,
            commit="c" * 40,
            wheel=wheel,
            sdist=sdist,
            validation_logs=[empty],
        )
    same_name = tmp_path / "nested" / "log.txt"
    same_name.parent.mkdir()
    same_name.write_text("one\n", encoding="utf-8")
    other = tmp_path / "log.txt"
    other.write_text("two\n", encoding="utf-8")
    with pytest.raises(ValueError, match="basenames must be unique"):
        release_manifest.build_manifest(
            root=release_manifest.ROOT,
            commit="c" * 40,
            wheel=wheel,
            sdist=sdist,
            validation_logs=[same_name, other],
        )


def test_cli_refuses_to_overwrite_existing_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, version = release_manifest._source_identity(release_manifest.ROOT)
    wheel, sdist = _artifacts(tmp_path, version=version)
    log = tmp_path / "validation.txt"
    log.write_text("checked\n", encoding="utf-8")
    output = tmp_path / "release-manifest.json"
    output.write_text("original\n", encoding="utf-8")
    monkeypatch.setattr(release_manifest, "_git_commit", lambda root: "d" * 40)
    assert (
        release_manifest.main(
            [
                "--wheel",
                str(wheel),
                "--sdist",
                str(sdist),
                "--validation-log",
                str(log),
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert output.read_text(encoding="utf-8") == "original\n"


def test_cli_writes_manifest_for_existing_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, version = release_manifest._source_identity(release_manifest.ROOT)
    wheel, sdist = _artifacts(tmp_path, version=version)
    log = tmp_path / "validation.txt"
    log.write_text("command exited 0\n", encoding="utf-8")
    output = tmp_path / "release-manifest.json"
    monkeypatch.setattr(release_manifest, "_git_commit", lambda root: "e" * 40)
    assert (
        release_manifest.main(
            [
                "--wheel",
                str(wheel),
                "--sdist",
                str(sdist),
                "--validation-log",
                str(log),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["source"]["git_commit"] == "e" * 40
    assert (
        manifest["artifacts"]["wheel"]["sha256"] == release_manifest._file_evidence(wheel)["sha256"]
    )
