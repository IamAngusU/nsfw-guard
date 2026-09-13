"""Record local, inspectable evidence for a manually prepared release.

This is a checksum inventory, not a signature or a claim that validation passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tarfile
import zipfile
from collections.abc import Sequence
from email import message_from_bytes
from pathlib import Path

from nsfw_guard import model_store

ROOT = Path(__file__).resolve().parents[1]


def _source_identity(root: Path) -> tuple[str, str]:
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(r"(?ms)^\[project\]\s*$(.*?)(?=^\[|\Z)", project)
    if section is None:
        raise ValueError("pyproject.toml has no [project] section")

    def field(name: str) -> str:
        matches: list[str] = re.findall(rf'(?m)^{name}\s*=\s*"([^"]+)"\s*$', section.group(1))
        if len(matches) != 1:
            raise ValueError(f"pyproject.toml must have exactly one [project].{name}")
        return matches[0]

    name, version = field("name"), field("version")
    package = (root / "src" / "nsfw_guard" / "__init__.py").read_text(encoding="utf-8")
    package_versions = re.findall(r'(?m)^__version__\s*=\s*"([^"]+)"\s*$', package)
    if package_versions != [version]:
        raise ValueError("package __version__ and pyproject.toml version disagree")
    return name, version


def _wheel_identity(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        metadata = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata) != 1:
            raise ValueError("wheel must contain exactly one dist-info/METADATA")
        message = message_from_bytes(archive.read(metadata[0]))
    return str(message.get("Name", "")), str(message.get("Version", ""))


def _sdist_identity(path: Path) -> tuple[str, str]:
    with tarfile.open(path, "r:gz") as archive:
        metadata = [
            member
            for member in archive.getmembers()
            if len(member.name.split("/")) == 2 and member.name.endswith("/PKG-INFO")
        ]
        if len(metadata) != 1:
            raise ValueError("sdist must contain exactly one PKG-INFO")
        extracted = archive.extractfile(metadata[0])
        if extracted is None:
            raise ValueError("sdist PKG-INFO is not a regular file")
        with extracted:
            message = message_from_bytes(extracted.read())
    return str(message.get("Name", "")), str(message.get("Version", ""))


def _file_evidence(path: Path) -> dict[str, str | int]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"evidence must be a regular file: {path}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    if size == 0:
        raise ValueError(f"evidence must not be empty: {path}")
    return {"filename": path.name, "bytes": size, "sha256": digest.hexdigest()}


def _git_commit(root: Path) -> str:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise ValueError(
            "tracked source tree is dirty; commit it before building release artifacts"
        )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("git did not return a full SHA-1 commit ID")
    return commit


def build_manifest(
    *,
    root: Path,
    commit: str,
    wheel: Path,
    sdist: Path,
    validation_logs: Sequence[Path],
) -> dict[str, object]:
    """Build a deterministic inventory without making any pass/fail inference."""
    name, version = _source_identity(root)
    model_source = (root / "src" / "nsfw_guard" / "model_store.py").resolve()
    if Path(model_store.__file__).resolve() != model_source:
        raise ValueError("the loaded model pin does not come from this source tree")
    model = model_store.DEFAULT_MODEL
    expected = (name, version)
    if _wheel_identity(wheel) != expected or _sdist_identity(sdist) != expected:
        raise ValueError("wheel and sdist metadata must match the source package name and version")
    if not validation_logs:
        raise ValueError("at least one existing validation log is required")
    logs = [_file_evidence(path) for path in validation_logs]
    if len({str(item["filename"]) for item in logs}) != len(logs):
        raise ValueError("validation log basenames must be unique")
    logs.sort(key=lambda item: str(item["filename"]))
    return {
        "schema_version": 1,
        "package": {"name": name, "version": version},
        "source": {"git_commit": commit, "tracked_tree_clean": True},
        "artifacts": {"wheel": _file_evidence(wheel), "sdist": _file_evidence(sdist)},
        "pinned_model": {
            "id": model.model_id,
            "repository": model.repository,
            "repository_revision": model.repository_revision,
            "source_model": model.source_model,
            "source_revision": model.source_revision,
            "download_url": model.download_url,
            "license": model.license,
            "sha256": model.sha256,
            "bundled_in_distribution": False,
        },
        "validation_evidence": {
            "logs": logs,
            "meaning": "Hashes only; inspect logs for commands, outcomes, and host details.",
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--sdist", type=Path, required=True)
    parser.add_argument("--validation-log", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        manifest = build_manifest(
            root=ROOT,
            commit=_git_commit(ROOT),
            wheel=arguments.wheel,
            sdist=arguments.sdist,
            validation_logs=arguments.validation_log,
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        with arguments.output.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except (
        OSError,
        ValueError,
        subprocess.CalledProcessError,
        zipfile.BadZipFile,
        tarfile.TarError,
    ) as exc:
        print(f"release manifest: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
