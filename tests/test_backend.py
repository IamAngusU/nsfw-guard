from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from nsfw_guard.backend import OnnxBackend
from nsfw_guard.errors import InvalidInputError, ProviderUnavailableError


class _SessionOptions:
    def __init__(self) -> None:
        self.enable_mem_pattern = True
        self.execution_mode: object | None = None
        self.intra_op_num_threads = 0


class _Session:
    def __init__(
        self,
        _path: str,
        *,
        sess_options: _SessionOptions,
        providers: list[object],
    ) -> None:
        self.options = sess_options
        self.providers = providers

    def get_providers(self) -> list[str]:
        return ["CPUExecutionProvider"]


def _fake_ort(available: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        ExecutionMode=SimpleNamespace(ORT_SEQUENTIAL="sequential"),
        GraphOptimizationLevel=SimpleNamespace(ORT_ENABLE_ALL="all"),
        SessionOptions=_SessionOptions,
        InferenceSession=_Session,
        get_available_providers=lambda: available,
        preload_dlls=lambda **_kwargs: None,
    )


def test_cuda_requires_explicit_arena_budget() -> None:
    with pytest.raises(InvalidInputError, match="cuda_arena_limit_mib"):
        OnnxBackend(provider="cuda")


def test_cuda_refuses_silent_cpu_fallback(tmp_path: Path) -> None:
    fake = _fake_ort(["CUDAExecutionProvider", "CPUExecutionProvider"])
    with (
        patch("nsfw_guard.backend.ensure_model", return_value=tmp_path / "model.onnx"),
        patch("nsfw_guard.backend.ort", fake),
        pytest.raises(ProviderUnavailableError, match="silent CPU fallback"),
    ):
        OnnxBackend(provider="cuda", cuda_arena_limit_mib=256)


def test_directml_refuses_fake_arena_cap() -> None:
    with pytest.raises(InvalidInputError, match="cannot enforce"):
        OnnxBackend(provider="directml", cuda_arena_limit_mib=256)


def test_directml_refuses_silent_cpu_fallback(tmp_path: Path) -> None:
    fake = _fake_ort(["DmlExecutionProvider", "CPUExecutionProvider"])
    with (
        patch("nsfw_guard.backend.ensure_model", return_value=tmp_path / "model.onnx"),
        patch("nsfw_guard.backend.ort", fake),
        pytest.raises(ProviderUnavailableError, match="silent CPU fallback"),
    ):
        OnnxBackend(provider="directml")
