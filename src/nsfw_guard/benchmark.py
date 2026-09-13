from __future__ import annotations

import io
import json
import math
import os
import platform
import statistics
from datetime import datetime, timezone
from pathlib import Path

import psutil
from PIL import Image, ImageDraw

from .scanner import Scanner


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _synthetic_payloads() -> list[bytes]:
    payloads: list[bytes] = []
    colors = [(245, 240, 230), (30, 60, 90), (180, 200, 160), (120, 80, 140)]
    for index, color in enumerate(colors):
        image = Image.new("RGB", (1280, 720), color)
        draw = ImageDraw.Draw(image)
        for step in range(24):
            left = (step * 71 + index * 29) % 1180
            top = (step * 43 + index * 17) % 620
            draw.rectangle(
                (left, top, left + 100, top + 100),
                fill=((step * 31) % 255, (step * 53) % 255, (step * 79) % 255),
            )
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=90, optimize=False)
        payloads.append(buffer.getvalue())
    return payloads


def run_benchmark(
    scanner: Scanner,
    *,
    runs: int = 30,
    warmups: int = 3,
    output_path: Path | None = None,
) -> dict[str, object]:
    if runs < 1 or warmups < 0:
        raise ValueError("runs must be positive and warmups must not be negative")
    payloads = _synthetic_payloads()
    for index in range(warmups):
        scanner.scan_bytes(payloads[index % len(payloads)])

    totals: list[float] = []
    decodes: list[float] = []
    preprocesses: list[float] = []
    inferences: list[float] = []
    for index in range(runs):
        result = scanner.scan_bytes(payloads[index % len(payloads)])
        totals.append(result.timing.total_ms)
        decodes.append(result.timing.decode_ms)
        preprocesses.append(result.timing.preprocess_ms)
        inferences.append(result.timing.inference_ms)

    memory = psutil.Process().memory_info()
    peak_rss = getattr(memory, "peak_wset", memory.rss)
    measured_seconds = sum(totals) / 1000.0
    report: dict[str, object] = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "profile": "synthetic-1280x720-jpeg-sequential-end-to-end",
        "runs": runs,
        "warmups": warmups,
        "model": scanner.backend.evidence,
        "timings_ms": {
            "decode_p50": statistics.median(decodes),
            "preprocess_p50": statistics.median(preprocesses),
            "inference_p50": statistics.median(inferences),
            "inference_p95": _percentile(inferences, 0.95),
            "total_p50": statistics.median(totals),
            "total_p95": _percentile(totals, 0.95),
            "total_mean": statistics.fmean(totals),
        },
        "throughput_images_per_second": runs / measured_seconds,
        "memory": {"current_rss_bytes": memory.rss, "peak_rss_bytes": peak_rss},
        "host": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "unknown"),
            "logical_cpu_count": os.cpu_count(),
        },
        "limitations": [
            "Synthetic inputs measure runtime behavior, not classification accuracy.",
            "Results are host-specific and are not a service-level guarantee.",
            "GPU memory must be measured by a host-level witness.",
        ],
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output_path)
    return report
