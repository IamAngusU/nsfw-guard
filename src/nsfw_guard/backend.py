from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import onnxruntime as ort  # type: ignore[import-untyped]
from numpy.typing import NDArray
from PIL import Image

from .errors import InferenceError, InvalidInputError, ProviderUnavailableError
from .model_store import DEFAULT_MODEL, ModelSpec, ensure_model


@dataclass(frozen=True, slots=True)
class Prediction:
    nsfw_score: float
    safe_score: float
    preprocess_ms: float
    inference_ms: float


class ImageBackend(Protocol):
    @property
    def evidence(self) -> dict[str, object]: ...

    def predict(self, image: Image.Image) -> Prediction: ...


class OnnxBackend:
    def __init__(
        self,
        *,
        provider: str = "cpu",
        threads: int = 0,
        cuda_arena_limit_mib: int | None = None,
        model_path: Path | None = None,
        allow_download: bool = True,
        spec: ModelSpec = DEFAULT_MODEL,
    ) -> None:
        if threads < 0:
            raise InvalidInputError("Thread count must be zero or greater.")
        if provider not in {"cpu", "cuda", "directml"}:
            raise InvalidInputError("Provider must be 'cpu', 'cuda', or 'directml'.")
        if provider == "cuda" and (cuda_arena_limit_mib is None or cuda_arena_limit_mib <= 0):
            raise InvalidInputError(
                "CUDA requires an explicit positive cuda_arena_limit_mib value."
            )
        if provider == "directml" and cuda_arena_limit_mib is not None:
            raise InvalidInputError(
                "DirectML cannot enforce cuda_arena_limit_mib; omit it or use CUDA."
            )

        self._spec = spec
        self._model_path = ensure_model(model_path, spec, allow_download=allow_download)
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.inter_op_num_threads = 1
        if threads:
            options.intra_op_num_threads = threads

        if provider == "cuda":
            preload_dlls = getattr(ort, "preload_dlls", None)
            if callable(preload_dlls):
                try:
                    preload_dlls(directory="")
                except Exception as exc:
                    raise ProviderUnavailableError(
                        "CUDA runtime libraries could not be preloaded."
                    ) from exc

        available = set(ort.get_available_providers())
        providers: list[str | tuple[str, dict[str, str]]]
        if provider == "cpu":
            if "CPUExecutionProvider" not in available:
                raise ProviderUnavailableError("ONNX Runtime has no CPU execution provider.")
            providers = ["CPUExecutionProvider"]
        elif provider == "cuda":
            if "CUDAExecutionProvider" not in available:
                raise ProviderUnavailableError(
                    "CUDA was requested but this environment has no CUDA execution provider.",
                    details={"available_providers": sorted(available)},
                )
            assert cuda_arena_limit_mib is not None
            providers = [
                (
                    "CUDAExecutionProvider",
                    {"gpu_mem_limit": str(cuda_arena_limit_mib * 1024 * 1024)},
                ),
                "CPUExecutionProvider",
            ]
        else:
            if "DmlExecutionProvider" not in available:
                raise ProviderUnavailableError(
                    "DirectML was requested but this environment has no "
                    "DirectML execution provider.",
                    details={"available_providers": sorted(available)},
                )
            options.enable_mem_pattern = False
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]

        load_started = time.perf_counter()
        try:
            self._session = ort.InferenceSession(
                str(self._model_path),
                sess_options=options,
                providers=providers,
            )
        except Exception as exc:
            raise InferenceError("The ONNX model session could not be created.") from exc
        active_providers = self._session.get_providers()
        if provider == "cuda" and "CUDAExecutionProvider" not in active_providers:
            raise ProviderUnavailableError(
                "CUDA initialization failed; refusing a silent CPU fallback.",
                details={"active_providers": active_providers},
            )
        if provider == "directml" and "DmlExecutionProvider" not in active_providers:
            raise ProviderUnavailableError(
                "DirectML initialization failed; refusing a silent CPU fallback.",
                details={"active_providers": active_providers},
            )
        self._load_ms = (time.perf_counter() - load_started) * 1000.0
        self._requested_provider = provider
        self._threads = threads
        self._cuda_arena_limit_mib = cuda_arena_limit_mib
        self._validate_interface()

    def _validate_interface(self) -> None:
        inputs = self._session.get_inputs()
        outputs = self._session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise InferenceError("The ONNX model interface has an unexpected tensor count.")
        shape = list(inputs[0].shape)
        expected = [1, 3, self._spec.input_height, self._spec.input_width]
        if shape != expected or inputs[0].name != "input" or outputs[0].name != "logits":
            raise InferenceError(
                "The ONNX model interface does not match the pinned contract.",
                details={"input_name": inputs[0].name, "input_shape": shape},
            )
        self._input_name = inputs[0].name
        self._output_name = outputs[0].name

    @property
    def evidence(self) -> dict[str, object]:
        return {
            **self._spec.to_dict(),
            "runtime": "onnxruntime",
            "runtime_version": ort.__version__,
            "requested_provider": self._requested_provider,
            "active_providers": self._session.get_providers(),
            "threads": self._threads,
            "cuda_arena_limit_mib": self._cuda_arena_limit_mib,
            "model_load_ms": round(self._load_ms, 4),
        }

    def predict(self, image: Image.Image) -> Prediction:
        preprocess_started = time.perf_counter()
        resized = image.resize(
            (self._spec.input_width, self._spec.input_height),
            Image.Resampling.BICUBIC,
        )
        pixels = np.asarray(resized, dtype=np.float32) / np.float32(255.0)
        pixels = (pixels - np.float32(0.5)) / np.float32(0.5)
        inputs: NDArray[np.float32] = np.ascontiguousarray(pixels.transpose(2, 0, 1)[None, ...])
        preprocess_ms = (time.perf_counter() - preprocess_started) * 1000.0

        inference_started = time.perf_counter()
        try:
            raw = self._session.run([self._output_name], {self._input_name: inputs})[0]
        except Exception as exc:
            raise InferenceError("ONNX inference failed.") from exc
        inference_ms = (time.perf_counter() - inference_started) * 1000.0
        logits = np.asarray(raw, dtype=np.float64)
        if logits.shape != (1, 2) or not np.isfinite(logits).all():
            raise InferenceError("The model returned invalid logits.")
        shifted = logits[0] - np.max(logits[0])
        exponentials = np.exp(shifted)
        denominator = float(np.sum(exponentials))
        if not math.isfinite(denominator) or denominator <= 0.0:
            raise InferenceError("The model logits could not be normalized.")
        nsfw_score = float(exponentials[0] / denominator)
        safe_score = float(exponentials[1] / denominator)
        return Prediction(nsfw_score, safe_score, preprocess_ms, inference_ms)

    def warmup(self) -> None:
        self.predict(Image.new("RGB", (self._spec.input_width, self._spec.input_height)))
