from __future__ import annotations

import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import cast

import psutil

from .run_chart import BoundedTimeline, RunSample, render_run_metrics_svg

JsonObject = dict[str, object]


def _nvidia_snapshot() -> JsonObject | None:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=3.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    lines = result.stdout.splitlines()
    parts = [part.strip() for part in (lines[0] if lines else "").split(",")]
    if len(parts) != 5:
        return None
    try:
        return {
            "name": parts[0],
            "driver_version": parts[1],
            "memory_total_mib": int(parts[2]),
            "memory_used_mib": int(parts[3]),
            "utilization_percent": int(parts[4]),
        }
    except ValueError:
        return None


def _process_tree_rss(process: psutil.Process) -> int:
    try:
        processes = [process, *process.children(recursive=True)]
    except psutil.Error:
        processes = [process]
    total = 0
    for item in processes:
        try:
            total += item.memory_info().rss
        except psutil.Error:
            continue
    return total


class VisionResourceMonitor:
    def __init__(self, *, interval_seconds: float = 1.0) -> None:
        self._interval = interval_seconds
        self._process = psutil.Process()
        self._timeline = BoundedTimeline()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._started = 0.0
        self._records = 0
        self._calls = 0
        self._sequence = 0
        self._peak_rss = 0
        self._gpu_start: JsonObject | None = None
        self._gpu_peak: JsonObject | None = None
        self._gpu_end: JsonObject | None = None
        self._host: JsonObject = {}

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("resource monitor already started")
        memory = psutil.virtual_memory()
        cpu_start = psutil.cpu_percent(interval=0.1)
        self._started = time.perf_counter()
        self._gpu_start = _nvidia_snapshot()
        self._gpu_peak = self._gpu_start
        self._host = {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
            "logical_cpu_count": psutil.cpu_count(logical=True),
            "physical_cpu_count": psutil.cpu_count(logical=False),
            "ram_total_bytes": memory.total,
            "ram_available_at_start_bytes": memory.available,
            "cpu_utilization_at_start_percent": cpu_start,
            "gpu_at_start": self._gpu_start,
        }
        self._sample(gpu=self._gpu_start, force=True, cpu_percent=cpu_start)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def update(self, *, records: int, calls: int) -> None:
        with self._lock:
            self._records = records
            self._calls = calls

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._sample(gpu=_nvidia_snapshot(), force=False)

    def _sample(
        self,
        *,
        gpu: JsonObject | None,
        force: bool,
        cpu_percent: float | None = None,
    ) -> None:
        with self._lock:
            records = self._records
            calls = self._calls
            self._sequence += 1
            sequence = self._sequence
        elapsed = max(0.0, time.perf_counter() - self._started)
        rss = _process_tree_rss(self._process)
        self._peak_rss = max(self._peak_rss, rss)
        if gpu is not None and (
            self._gpu_peak is None
            or cast(int, gpu["memory_used_mib"]) > cast(int, self._gpu_peak["memory_used_mib"])
        ):
            self._gpu_peak = gpu
        sample: RunSample = {
            "completed": sequence,
            "records": records,
            "adapter_calls": calls,
            "elapsed_seconds": elapsed,
            "throughput_images_per_second": records / elapsed if elapsed else 0.0,
            "host_cpu_percent": (
                cpu_percent if cpu_percent is not None else psutil.cpu_percent(interval=None)
            ),
            "gpu_utilization_percent": (
                cast(int, gpu["utilization_percent"]) if gpu is not None else None
            ),
            "process_rss_mib": rss / (1024 * 1024),
            "gpu_memory_used_mib": (cast(int, gpu["memory_used_mib"]) if gpu is not None else None),
        }
        self._timeline.add(sample, force=force)

    def stop(self) -> None:
        thread = self._thread
        if thread is None:
            return
        self._stop.set()
        thread.join(timeout=self._interval + 4.0)
        self._gpu_end = _nvidia_snapshot()
        self._sample(gpu=self._gpu_end, force=True)
        self._thread = None

    def render(self, output: Path, *, run_id: str, model_count: int) -> Path:
        return render_run_metrics_svg(
            self._timeline.to_list(),
            output,
            title=f"NSFW Guard vision run {run_id}",
            subtitle=(
                f"models={model_count} | interval={self._interval:g}s | "
                "RSS includes child adapters; GPU values are host-total"
            ),
        )

    def evidence(self) -> JsonObject:
        timeline = self._timeline.to_list()
        cpu_start = cast(float, self._host.get("cpu_utilization_at_start_percent", 0.0))
        warnings: list[str] = []
        if cpu_start > 25.0:
            warnings.append(
                "CPU utilization exceeded 25 percent at start; timing may be contaminated."
            )
        if self._gpu_start is not None and cast(int, self._gpu_start["utilization_percent"]) > 20:
            warnings.append(
                "GPU utilization exceeded 20 percent at start; timing may be contaminated."
            )
        return {
            "host": self._host,
            "peak_process_tree_rss_bytes": self._peak_rss,
            "gpu_at_start": self._gpu_start,
            "gpu_peak_observed": self._gpu_peak,
            "gpu_at_end": self._gpu_end,
            "gpu_witness": "host-total nvidia-smi sample; not per-process attribution",
            "timeline_interval_seconds": self._interval,
            "timeline": timeline,
            "measurement_quality": {
                "headline_eligible": not warnings,
                "warnings": warnings,
            },
        }
