import hashlib
from pathlib import Path

import pytest

from nsfw_guard.errors import ModelIntegrityError, ModelUnavailableError
from nsfw_guard.model_store import (
    ModelSpec,
    ensure_model,
    install_model,
    model_status,
    verify_model,
)


def spec_for(payload: bytes) -> ModelSpec:
    return ModelSpec(
        model_id="test-model",
        version="1",
        repository="example/model",
        repository_revision="a" * 40,
        source_model="example/source",
        source_revision="b" * 40,
        license="Apache-2.0",
        filename="model.onnx",
        download_url="https://example.invalid/model.onnx",
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_existing_model_must_match_exact_digest(tmp_path: Path) -> None:
    payload = b"model fixture"
    path = tmp_path / "model.onnx"
    path.write_bytes(payload)
    spec = spec_for(payload)
    assert verify_model(path, spec) == path
    path.write_bytes(b"changed")
    with pytest.raises(ModelIntegrityError):
        verify_model(path, spec)


def test_valid_existing_model_install_never_uses_network(tmp_path: Path) -> None:
    payload = b"model fixture"
    path = tmp_path / "model.onnx"
    path.write_bytes(payload)
    spec = spec_for(payload)
    assert install_model(path, spec) == path
    assert model_status(path, spec)["valid"] is True


def test_missing_model_can_be_required_offline(tmp_path: Path) -> None:
    with pytest.raises(ModelUnavailableError):
        ensure_model(tmp_path / "missing.onnx", spec_for(b"x"), allow_download=False)
