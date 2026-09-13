from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .errors import ModelIntegrityError, ModelUnavailableError

DOWNLOAD_CHUNK_BYTES = 1024 * 1024
MAX_MODEL_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ModelSpec:
    model_id: str
    version: str
    repository: str
    repository_revision: str
    source_model: str
    source_revision: str
    license: str
    filename: str
    download_url: str
    sha256: str
    input_width: int = 384
    input_height: int = 384

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.model_id,
            "version": self.version,
            "repository": self.repository,
            "repository_revision": self.repository_revision,
            "source_model": self.source_model,
            "source_revision": self.source_revision,
            "license": self.license,
            "artifact_sha256": self.sha256,
            "input_width": self.input_width,
            "input_height": self.input_height,
        }


DEFAULT_MODEL = ModelSpec(
    model_id="marqo-nsfw-image-detection-384-onnx",
    version="0.1.0",
    repository="KanariKanaru/nsfw-image-detection-384-onnx",
    repository_revision="8edc47eedf74b30fd379673bc202fe3b754b1538",
    source_model="Marqo/nsfw-image-detection-384",
    source_revision="dcbee2f0570c16c3212bc6b81bb8911194b9fa62",
    license="Apache-2.0",
    filename="model.onnx",
    download_url=(
        "https://huggingface.co/KanariKanaru/nsfw-image-detection-384-onnx/resolve/"
        "8edc47eedf74b30fd379673bc202fe3b754b1538/model.onnx?download=true"
    ),
    sha256="e9350e576608afe4b57a089ffeb0ebafa1389cdcea4882dd61df28c45f1c24d2",
)


def default_cache_root() -> Path:
    configured = os.environ.get("NSFW_GUARD_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "nsfw-guard"
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache) / "nsfw-guard"
    return Path.home() / ".cache" / "nsfw-guard"


def default_model_path(spec: ModelSpec = DEFAULT_MODEL) -> Path:
    return default_cache_root() / "models" / spec.sha256[:16] / spec.filename


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(DOWNLOAD_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(path: Path, spec: ModelSpec = DEFAULT_MODEL) -> Path:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ModelUnavailableError("The pinned model is not installed.") from exc
    if path.is_symlink():
        raise ModelIntegrityError("The model path must not be a symbolic link.")
    if not path.is_file():
        raise ModelIntegrityError("The model path is not a regular file.")
    if metadata.st_size <= 0 or metadata.st_size > MAX_MODEL_BYTES:
        raise ModelIntegrityError(
            "The model file size is outside the accepted bounds.",
            details={"max_bytes": MAX_MODEL_BYTES, "actual_bytes": metadata.st_size},
        )
    actual = sha256_file(path)
    if actual != spec.sha256:
        raise ModelIntegrityError(
            "The model SHA-256 does not match the pinned artifact.",
            details={"expected_sha256": spec.sha256, "actual_sha256": actual},
        )
    return path


def model_status(path: Path | None = None, spec: ModelSpec = DEFAULT_MODEL) -> dict[str, object]:
    candidate = path or default_model_path(spec)
    try:
        verify_model(candidate, spec)
    except (ModelIntegrityError, ModelUnavailableError) as exc:
        return {
            "installed": False,
            "valid": False,
            "path": str(candidate),
            "model": spec.to_dict(),
            "error": exc.to_dict(),
        }
    return {
        "installed": True,
        "valid": True,
        "path": str(candidate),
        "bytes": candidate.stat().st_size,
        "model": spec.to_dict(),
    }


def install_model(
    path: Path | None = None,
    spec: ModelSpec = DEFAULT_MODEL,
    *,
    timeout_seconds: float = 120.0,
) -> Path:
    target = path or default_model_path(spec)
    if target.exists():
        try:
            return verify_model(target, spec)
        except ModelIntegrityError:
            pass

    target.parent.mkdir(parents=True, exist_ok=True)
    request = Request(
        spec.download_url,
        headers={"User-Agent": "nsfw-guard/0.1 model-installer"},
    )
    temporary_path: Path | None = None
    try:
        response: Any = urlopen(request, timeout=timeout_seconds)
        with response:
            if urlparse(str(response.geturl())).scheme.lower() != "https":
                raise ModelIntegrityError("The model download left HTTPS.")
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > MAX_MODEL_BYTES:
                raise ModelIntegrityError("The remote model exceeds the download limit.")
            digest = hashlib.sha256()
            written = 0
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".part",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_MODEL_BYTES:
                        raise ModelIntegrityError("The model download exceeded its byte limit.")
                    digest.update(chunk)
                    temporary.write(chunk)
                temporary.flush()
                os.fsync(temporary.fileno())
        if written <= 0 or digest.hexdigest() != spec.sha256:
            raise ModelIntegrityError(
                "The downloaded model failed SHA-256 verification.",
                details={"expected_sha256": spec.sha256, "actual_sha256": digest.hexdigest()},
            )
        os.replace(temporary_path, target)
        temporary_path = None
        return verify_model(target, spec)
    except ModelIntegrityError:
        raise
    except Exception as exc:
        raise ModelUnavailableError("The pinned model could not be downloaded.") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def ensure_model(
    path: Path | None = None,
    spec: ModelSpec = DEFAULT_MODEL,
    *,
    allow_download: bool = True,
) -> Path:
    candidate = path or default_model_path(spec)
    try:
        return verify_model(candidate, spec)
    except ModelUnavailableError:
        if not allow_download:
            raise
    if not allow_download:
        return verify_model(candidate, spec)
    return install_model(candidate, spec)
