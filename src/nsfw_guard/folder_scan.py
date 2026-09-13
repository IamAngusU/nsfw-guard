from __future__ import annotations

import argparse
import heapq
import html
import json
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import unicodedata
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import psutil

from .backend import OnnxBackend
from .errors import GuardError, InvalidInputError
from .policy import POLICY_PROFILES, get_policy
from .scanner import ScanLimits, Scanner

JsonObject = dict[str, Any]
MIB = 1024 * 1024
SUPPORTED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MAX_DISCOVERY_FILES = 100_000
POLICY_NAMES = tuple(sorted(POLICY_PROFILES))
PROVIDER_NAMES = ("cpu", "cuda", "directml")


@dataclass(frozen=True, slots=True)
class FolderScanConfig:
    root: Path
    output_dir: Path | None = None
    recursive: bool = True
    create_links: bool = False
    policy_name: str = "medium-threshold-v1"
    provider: str = "cpu"
    threads: int = 0
    cuda_arena_limit_mib: int | None = None
    model_path: Path | None = None
    allow_download: bool = True
    max_bytes: int = 25 * MIB
    max_pixels: int = 40_000_000
    requested_workers: int | None = None
    max_in_flight: int | None = None
    memory_budget_mib: int | None = None
    max_files: int | None = None
    progress_every: int = 100
    fail_on: str = "error"


@dataclass(frozen=True, slots=True)
class WorkerPlan:
    requested_workers: int | None
    recommended_workers: int
    effective_workers: int
    max_in_flight: int
    memory_budget_mib: int
    estimated_worker_mib: int
    base_rss_bytes: int
    warning: str | None

    def to_dict(self) -> JsonObject:
        return {
            "requested_workers": self.requested_workers,
            "recommended_workers": self.recommended_workers,
            "effective_workers": self.effective_workers,
            "max_in_flight": self.max_in_flight,
            "memory_budget_mib": self.memory_budget_mib,
            "estimated_worker_mib": self.estimated_worker_mib,
            "base_rss_bytes": self.base_rss_bytes,
            "budget_is_hard_limit": False,
            "optimization_goal": "folder throughput with bounded in-flight work",
            "warning": self.warning,
        }


@dataclass(frozen=True, slots=True)
class FolderScanOutcome:
    summary: JsonObject
    exit_code: int


@dataclass(frozen=True, slots=True)
class ImageDiscovery:
    paths: list[Path]
    supported_candidate_count: int


@dataclass(frozen=True, slots=True)
class _ReversePathKey:
    value: tuple[str, str]

    def __lt__(self, other: _ReversePathKey) -> bool:
        return self.value > other.value


def recommend_inference_threads(
    *,
    provider: str,
    requested_threads: int,
    requested_workers: int | None,
    physical_cpu_count: int | None,
) -> int:
    """Bound CPU intra-op threads so folder workers do not oversubscribe the host."""
    if requested_threads < 0:
        raise InvalidInputError("Thread count must be zero or greater.")
    if requested_threads or provider != "cpu":
        return requested_threads
    physical = max(1, physical_cpu_count or 1)
    workers = requested_workers or min(4, physical)
    return max(1, min(4, physical // workers))


class BoundedMetric:
    def __init__(self, *, capacity: int = 10_000, seed: int = 0) -> None:
        if capacity < 1:
            raise ValueError("Metric capacity must be positive.")
        self._capacity = capacity
        self._random = random.Random(seed)
        self._sample: list[float] = []
        self._count = 0
        self._sum = 0.0
        self._minimum: float | None = None
        self._maximum: float | None = None

    def add(self, value: float) -> None:
        self._count += 1
        self._sum += value
        self._minimum = value if self._minimum is None else min(self._minimum, value)
        self._maximum = value if self._maximum is None else max(self._maximum, value)
        if len(self._sample) < self._capacity:
            self._sample.append(value)
            return
        index = self._random.randrange(self._count)
        if index < self._capacity:
            self._sample[index] = value

    def to_dict(self) -> JsonObject:
        if not self._sample:
            return {
                "count": 0,
                "sample_count": 0,
                "quantiles_exact": True,
                "min": None,
                "mean": None,
                "p50": None,
                "p95": None,
                "max": None,
            }
        ordered = sorted(self._sample)
        p95_index = max(0, int(len(ordered) * 0.95) - 1)
        return {
            "count": self._count,
            "sample_count": len(ordered),
            "quantiles_exact": self._count <= self._capacity,
            "min": self._minimum,
            "mean": self._sum / self._count,
            "p50": statistics.median(ordered),
            "p95": ordered[p95_index],
            "max": self._maximum,
        }


class LinkCollection:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.counts: Counter[str] = Counter()
        self._html_parts: dict[str, Path] = {}
        for verdict in ("BLOCK", "REVIEW", "ERROR"):
            verdict_dir = root / verdict
            verdict_dir.mkdir(parents=True, exist_ok=False)
            html_part = verdict_dir / ".index.html.part"
            write_text_atomic(
                html_part,
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                f"<title>NSFW Guard {verdict} review links</title></head><body>"
                f"<h1>{verdict} review links</h1><p>Links open original local files. "
                "No images were copied or changed.</p><ol>\n",
            )
            self._html_parts[verdict] = html_part

    @staticmethod
    def _safe_stem(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", ascii_value).strip("-._")
        return safe[:80] or "image"

    def add(self, *, index: int, source: Path, record: JsonObject) -> None:
        verdict = str(record["verdict"])
        if verdict not in {"BLOCK", "REVIEW", "ERROR"}:
            return
        self.counts[verdict] += 1
        score = record.get("scores", {}).get("nsfw")
        score_part = "no-score" if score is None else f"{float(score):.4f}"
        stem = self._safe_stem(source.stem)
        name = f"{index:07d}_{score_part}_{stem}.url"
        target = self.root / verdict / name
        write_text_atomic(
            target,
            f"[InternetShortcut]\nURL={source.resolve().as_uri()}\n",
        )
        source_uri = html.escape(source.resolve().as_uri(), quote=True)
        label = html.escape(source.name)
        with self._html_parts[verdict].open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f'<li><a href="{source_uri}">{index}: {label}</a></li>\n')

    def finalize(self, *, run_id: str, profile: str) -> Path:
        cards = []
        colors = {"BLOCK": "#b42318", "REVIEW": "#b54708", "ERROR": "#475467"}
        for verdict in ("BLOCK", "REVIEW", "ERROR"):
            html_part = self._html_parts[verdict]
            with html_part.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write("</ol></body></html>\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(html_part, html_part.with_name("index.html"))
            count = self.counts[verdict]
            cards.append(
                f'<a class="card" href="./{verdict}/index.html">'
                f'<span style="color:{colors[verdict]}">{html.escape(verdict)}</span>'
                f"<strong>{count}</strong><small>Open link folder</small></a>"
            )
        document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>NSFW Guard results {html.escape(run_id)}</title>
<style>
:root{{--ink:#14212b;--muted:#667085;--line:#d0d5dd;--paper:#fffdf7;--accent:#087e8b}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(135deg,#f4f8f7,#fff8e8);color:var(--ink);font:16px/1.5 Georgia,serif}}
main{{max-width:920px;margin:7vh auto;padding:42px;background:var(--paper);border:1px solid var(--line);box-shadow:0 24px 80px #18343b18}}
h1{{font:700 clamp(2rem,6vw,4.6rem)/.95 Georgia,serif;margin:.2em 0}}p{{color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-top:32px}}
.card{{display:grid;gap:8px;padding:22px;border:1px solid var(--line);color:inherit;text-decoration:none;background:white}}
.card span{{font:700 13px/1.2 Consolas,monospace;letter-spacing:.12em}}.card strong{{font-size:2.5rem}}.card small{{color:var(--muted)}}
code{{font-family:Consolas,monospace}}@media(max-width:600px){{main{{margin:0;padding:28px;min-height:100vh}}}}
</style></head><body><main><p>LOCAL-FIRST / NON-DESTRUCTIVE</p><h1>Review the evidence.</h1>
<p>Run <code>{html.escape(run_id)}</code>, policy <code>{html.escape(profile)}</code>. These are model outcomes, not legal or factual conclusions. Source images were not modified.</p>
<div class="grid">{"".join(cards)}</div></main></body></html>
"""
        index_path = self.root / "index.html"
        write_text_atomic(index_path, document)
        write_text_atomic(
            self.root / "README.txt",
            "NSFW Guard link collection\n\n"
            "Open index.html, then a verdict's index.html for portable review links. "
            "Windows .url shortcuts are also available. Links point to original "
            "images; deleting a link does not delete an image.\n",
        )
        return index_path


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_json_atomic(path: Path, value: object) -> None:
    write_text_atomic(
        path,
        json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
    )


def copy_atomic(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    with source.open("rb") as source_handle, temporary.open("wb") as target_handle:
        shutil.copyfileobj(source_handle, target_handle, length=1024 * 1024)
        target_handle.flush()
        os.fsync(target_handle.fileno())
    os.replace(temporary, target)


def discover_images(
    root: Path,
    *,
    recursive: bool,
    max_files: int | None = None,
) -> list[Path]:
    return _discover_images(root, recursive=recursive, max_files=max_files).paths


def _discover_images(
    root: Path,
    *,
    recursive: bool,
    max_files: int | None = None,
) -> ImageDiscovery:
    if not root.is_dir():
        raise InvalidInputError("The folder does not exist or is not a directory.")
    if max_files is not None and max_files < 1:
        raise InvalidInputError("max_files must be positive when supplied.")
    if max_files is not None and max_files > MAX_DISCOVERY_FILES:
        raise InvalidInputError(
            f"max_files cannot exceed the discovery path limit of {MAX_DISCOVERY_FILES}.",
            details={"max_files": max_files, "discovery_path_limit": MAX_DISCOVERY_FILES},
        )
    candidates = root.rglob("*") if recursive else root.glob("*")
    paths: list[Path] = []
    top_k: list[tuple[_ReversePathKey, Path]] = []
    supported_count = 0
    for path in candidates:
        if not path.is_file() or path.suffix.casefold() not in SUPPORTED_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part.casefold() == ".nsfw-guard" for part in relative.parts):
            continue
        supported_count += 1
        if max_files is None:
            if supported_count > MAX_DISCOVERY_FILES:
                raise InvalidInputError(
                    f"Folder contains more than {MAX_DISCOVERY_FILES} supported images. "
                    "Split the folder or use --max-files for an explicit partial selection.",
                    details={"discovery_path_limit": MAX_DISCOVERY_FILES},
                )
            paths.append(path)
            continue
        relative_text = relative.as_posix()
        key = (relative_text.casefold(), relative_text)
        entry = (_ReversePathKey(key), path)
        if len(top_k) < max_files:
            heapq.heappush(top_k, entry)
        elif key < top_k[0][0].value:
            heapq.heapreplace(top_k, entry)
    if max_files is not None:
        paths = [path for _, path in top_k]
    paths.sort(
        key=lambda path: (
            path.relative_to(root).as_posix().casefold(),
            path.relative_to(root).as_posix(),
        )
    )
    return ImageDiscovery(paths=paths, supported_candidate_count=supported_count)


def recommend_workers(
    *,
    provider: str,
    requested_workers: int | None,
    requested_max_in_flight: int | None,
    memory_budget_mib: int | None,
    base_rss_bytes: int,
    logical_cpu_count: int,
    available_memory_bytes: int,
) -> WorkerPlan:
    if requested_workers is not None and requested_workers < 1:
        raise InvalidInputError("workers must be positive or 'auto'.")
    if requested_max_in_flight is not None and requested_max_in_flight < 1:
        raise InvalidInputError("max_in_flight must be positive.")
    available_mib = max(1, available_memory_bytes // MIB)
    budget = (
        memory_budget_mib
        if memory_budget_mib is not None
        else min(4096, max(512, available_mib // 4))
    )
    if budget < 256:
        raise InvalidInputError("memory_budget_mib must be at least 256.")
    estimated_worker_mib = 128
    reserve_mib = 96
    base_mib = (base_rss_bytes + MIB - 1) // MIB
    memory_slots = max(1, (budget - base_mib - reserve_mib) // estimated_worker_mib)
    provider_cap = min(4, max(1, logical_cpu_count // 4))
    recommended = max(1, min(provider_cap, memory_slots))
    effective = recommended if requested_workers is None else requested_workers
    max_in_flight = (
        max(effective, effective * 2)
        if requested_max_in_flight is None
        else requested_max_in_flight
    )
    if max_in_flight < effective:
        raise InvalidInputError("max_in_flight cannot be lower than workers.")
    estimated_peak_mib = base_mib + reserve_mib + effective * estimated_worker_mib
    warning = None
    if estimated_peak_mib > budget:
        warning = (
            "The explicit worker count exceeds the planner budget estimate. "
            "This budget is advisory, not an operating-system hard limit."
        )
    return WorkerPlan(
        requested_workers=requested_workers,
        recommended_workers=recommended,
        effective_workers=effective,
        max_in_flight=max_in_flight,
        memory_budget_mib=budget,
        estimated_worker_mib=estimated_worker_mib,
        base_rss_bytes=base_rss_bytes,
        warning=warning,
    )


def _nvidia_snapshot() -> JsonObject | None:
    try:
        completed = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode or not completed.stdout.strip():
        return None
    parts = [part.strip() for part in completed.stdout.splitlines()[0].split(",")]
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


def _host_evidence() -> JsonObject:
    memory = psutil.virtual_memory()
    return {
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python": platform.python_version(),
        "logical_cpu_count": psutil.cpu_count(logical=True),
        "physical_cpu_count": psutil.cpu_count(logical=False),
        "cpu_utilization_at_start_percent": psutil.cpu_percent(interval=0.2),
        "ram_total_bytes": memory.total,
        "ram_available_at_start_bytes": memory.available,
        "gpu_at_start": _nvidia_snapshot(),
    }


def _build_scan_function(
    *,
    backend: OnnxBackend,
    policy_name: str,
    limits: ScanLimits,
    root: Path,
) -> Callable[[int, Path], JsonObject]:
    local = threading.local()
    policy = get_policy(policy_name)

    def scan(index: int, path: Path) -> JsonObject:
        scanner = cast(Scanner | None, getattr(local, "scanner", None))
        if scanner is None:
            scanner = Scanner(backend=backend, policy=policy, limits=limits, cache_entries=0)
            local.scanner = scanner
        relative_path = path.relative_to(root).as_posix()
        try:
            result_dict = scanner.scan_path(path).to_dict()
            return {
                "index": index,
                "relative_path": relative_path,
                "ok": True,
                **result_dict,
            }
        except GuardError as exc:
            return {
                "index": index,
                "relative_path": relative_path,
                "ok": False,
                "verdict": "ERROR",
                "error": exc.to_dict(),
            }
        except Exception as exc:
            return {
                "index": index,
                "relative_path": relative_path,
                "ok": False,
                "verdict": "ERROR",
                "error": {
                    "code": "internal_error",
                    "message": "Unexpected scanner failure.",
                    "details": {"exception_type": type(exc).__name__},
                    "retryable": False,
                },
            }

    return scan


def _exit_code(counts: Counter[str], fail_on: str) -> int:
    if fail_on == "never":
        return 0
    if counts["ERROR"]:
        return 30
    if fail_on in {"block", "review"} and counts["BLOCK"]:
        return 20
    if fail_on == "review" and counts["REVIEW"]:
        return 10
    return 0


def _host_total_vram_peak_delta_mib(
    start: JsonObject | None, peak: JsonObject | None
) -> int | None:
    """Return observed host-total VRAM growth relative to the start sample."""
    if start is None or peak is None:
        return None
    return max(0, int(peak["memory_used_mib"]) - int(start["memory_used_mib"]))


def scan_folder(config: FolderScanConfig) -> FolderScanOutcome:
    root = config.root.resolve()
    discovery = _discover_images(root, recursive=config.recursive, max_files=config.max_files)
    files = discovery.paths
    if not files:
        raise InvalidInputError("The folder contains no supported image candidates.")
    selection_truncated = discovery.supported_candidate_count > len(files)
    output_root = (
        config.output_dir.resolve() if config.output_dir is not None else root / ".nsfw-guard"
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = output_root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    write_json_atomic(
        run_dir / "status.json",
        {
            "run_id": run_id,
            "complete": False,
            "input_count": len(files),
            "selection_truncated": selection_truncated,
        },
    )

    host = _host_evidence()
    process = psutil.Process()
    effective_threads = recommend_inference_threads(
        provider=config.provider,
        requested_threads=config.threads,
        requested_workers=config.requested_workers,
        physical_cpu_count=int(host["physical_cpu_count"]),
    )
    backend = OnnxBackend(
        provider=config.provider,
        threads=effective_threads,
        cuda_arena_limit_mib=config.cuda_arena_limit_mib,
        model_path=config.model_path,
        allow_download=config.allow_download,
    )
    base_rss = process.memory_info().rss
    memory = psutil.virtual_memory()
    plan = recommend_workers(
        provider=config.provider,
        requested_workers=config.requested_workers,
        requested_max_in_flight=config.max_in_flight,
        memory_budget_mib=config.memory_budget_mib,
        base_rss_bytes=base_rss,
        logical_cpu_count=psutil.cpu_count(logical=True) or 1,
        available_memory_bytes=memory.available,
    )
    limits = ScanLimits(max_bytes=config.max_bytes, max_pixels=config.max_pixels)
    scan_one = _build_scan_function(
        backend=backend,
        policy_name=config.policy_name,
        limits=limits,
        root=root,
    )

    full_temp = run_dir / ".all-results.jsonl.tmp"
    flags_temp = run_dir / ".flags.jsonl.tmp"
    full_path = run_dir / "all-results.jsonl"
    flags_path = run_dir / "flags.jsonl"
    link_collection = LinkCollection(run_dir / "links") if config.create_links else None
    counts: Counter[str] = Counter()
    metrics = {
        name: BoundedMetric(seed=index)
        for index, name in enumerate(
            ("read_ms", "decode_ms", "preprocess_ms", "inference_ms", "total_ms")
        )
    }
    peak_rss = base_rss
    gpu_peak = cast(JsonObject | None, host.get("gpu_at_start"))
    total_bytes = 0
    started = time.perf_counter()
    from nsfw_guard.run_chart import (
        BoundedTimeline,
        render_run_metrics_svg,
        write_file_shortcut,
    )

    timeline = BoundedTimeline()
    timeline.add(
        {
            "completed": 0,
            "elapsed_seconds": 0.0,
            "throughput_images_per_second": 0.0,
            "host_cpu_percent": float(host["cpu_utilization_at_start_percent"]),
            "gpu_utilization_percent": (
                int(gpu_peak["utilization_percent"]) if gpu_peak is not None else None
            ),
            "process_rss_mib": base_rss / (1024 * 1024),
            "gpu_memory_used_mib": (
                int(gpu_peak["memory_used_mib"]) if gpu_peak is not None else None
            ),
        },
        force=True,
    )
    psutil.cpu_percent(interval=None)
    completed_count = 0
    ready: dict[int, JsonObject] = {}
    next_to_write = 1

    def submit_next(
        executor: ThreadPoolExecutor,
        iterator: Any,
        pending: dict[Future[JsonObject], int],
    ) -> bool:
        try:
            index, path = next(iterator)
        except StopIteration:
            return False
        future = executor.submit(scan_one, index, path)
        pending[future] = index
        return True

    with (
        full_temp.open("w", encoding="utf-8", newline="\n") as full_handle,
        flags_temp.open("w", encoding="utf-8", newline="\n") as flags_handle,
        ThreadPoolExecutor(
            max_workers=plan.effective_workers,
            thread_name_prefix="nsfw-guard-folder",
        ) as executor,
    ):
        iterator = iter(enumerate(files, start=1))
        pending: dict[Future[JsonObject], int] = {}
        for _ in range(plan.max_in_flight):
            if not submit_next(executor, iterator, pending):
                break
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                index = pending.pop(future)
                ready[index] = future.result()
                submit_next(executor, iterator, pending)
            while next_to_write in ready:
                record = ready.pop(next_to_write)
                verdict = str(record["verdict"])
                counts[verdict] += 1
                full_handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
                if verdict != "ALLOW":
                    flags_handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
                    if link_collection is not None:
                        link_collection.add(
                            index=next_to_write,
                            source=files[next_to_write - 1],
                            record=record,
                        )
                artifact = cast(JsonObject, record.get("artifact", {}))
                total_bytes += int(artifact.get("byte_length", 0))
                timing = cast(JsonObject, record.get("timing", {}))
                for name, accumulator in metrics.items():
                    value = timing.get(name)
                    if isinstance(value, int | float):
                        accumulator.add(float(value))
                completed_count += 1
                next_to_write += 1
                memory_info = process.memory_info()
                peak_rss = max(
                    peak_rss,
                    memory_info.rss,
                    int(getattr(memory_info, "peak_wset", 0)),
                )
                if completed_count % 100 == 0:
                    snapshot = _nvidia_snapshot() if config.provider != "cpu" else None
                    if snapshot is not None and (
                        gpu_peak is None
                        or int(snapshot["memory_used_mib"]) > int(gpu_peak["memory_used_mib"])
                    ):
                        gpu_peak = snapshot
                    sample_elapsed = time.perf_counter() - started
                    timeline.add(
                        {
                            "completed": completed_count,
                            "elapsed_seconds": sample_elapsed,
                            "throughput_images_per_second": completed_count / sample_elapsed,
                            "host_cpu_percent": psutil.cpu_percent(interval=None),
                            "gpu_utilization_percent": (
                                int(snapshot["utilization_percent"])
                                if snapshot is not None
                                else None
                            ),
                            "process_rss_mib": memory_info.rss / (1024 * 1024),
                            "gpu_memory_used_mib": (
                                int(snapshot["memory_used_mib"]) if snapshot is not None else None
                            ),
                        }
                    )
                if config.progress_every > 0 and (
                    completed_count % config.progress_every == 0 or completed_count == len(files)
                ):
                    elapsed = time.perf_counter() - started
                    rate = completed_count / elapsed if elapsed else 0.0
                    print(
                        f"{completed_count}/{len(files)} {rate:.2f} images/s "
                        f"review={counts['REVIEW']} block={counts['BLOCK']} "
                        f"error={counts['ERROR']}",
                        file=sys.stderr,
                        flush=True,
                    )
        for handle in (full_handle, flags_handle):
            handle.flush()
            os.fsync(handle.fileno())

    os.replace(full_temp, full_path)
    os.replace(flags_temp, flags_path)
    elapsed = time.perf_counter() - started
    links_index: Path | None = None
    gpu_after = _nvidia_snapshot()
    if gpu_after is not None and (
        gpu_peak is None or int(gpu_after["memory_used_mib"]) > int(gpu_peak["memory_used_mib"])
    ):
        gpu_peak = gpu_after
    gpu_before = cast(JsonObject | None, host.get("gpu_at_start"))
    gpu_delta = _host_total_vram_peak_delta_mib(gpu_before, gpu_peak)
    final_memory = process.memory_info().rss
    timeline.add(
        {
            "completed": completed_count,
            "elapsed_seconds": elapsed,
            "throughput_images_per_second": completed_count / elapsed if elapsed else 0.0,
            "host_cpu_percent": psutil.cpu_percent(interval=None),
            "gpu_utilization_percent": (
                int(gpu_after["utilization_percent"]) if gpu_after is not None else None
            ),
            "process_rss_mib": final_memory / (1024 * 1024),
            "gpu_memory_used_mib": (
                int(gpu_after["memory_used_mib"]) if gpu_after is not None else None
            ),
        },
        force=True,
    )
    timeline_samples = timeline.to_list()
    environment_warnings: list[str] = []
    cpu_utilization = float(host["cpu_utilization_at_start_percent"])
    if cpu_utilization > 25.0:
        environment_warnings.append(
            "CPU utilization exceeded 25 percent at start; timing may be contaminated."
        )
    if config.provider != "cpu" and gpu_before is not None:
        gpu_utilization = int(gpu_before["utilization_percent"])
        if gpu_utilization > 20:
            environment_warnings.append(
                "GPU utilization exceeded 20 percent at start; timing may be contaminated."
            )
    metrics_path = render_run_metrics_svg(
        timeline_samples,
        run_dir / "metrics.svg",
        title=f"NSFW Guard run {run_id}",
        subtitle=(
            f"provider={config.provider} | samples={len(timeline_samples)} | "
            "GPU values are host-total witnesses"
        ),
    )
    if link_collection is not None:
        write_file_shortcut(metrics_path, run_dir / "links" / "00-RUN-METRICS.url")
        links_index = link_collection.finalize(run_id=run_id, profile=config.policy_name)
    summary: JsonObject = {
        "schema_version": 1,
        "run_id": run_id,
        "complete": completed_count == len(files),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "input_count": len(files),
        "scanned_count": completed_count,
        "discovery": {
            "supported_candidate_count": discovery.supported_candidate_count,
            "selected_count": len(files),
            "omitted_count": discovery.supported_candidate_count - len(files),
            "selection_truncated": selection_truncated,
            "path_limit": MAX_DISCOVERY_FILES,
            "selection_order": "casefolded relative path, then original relative path",
        },
        "input_bytes": total_bytes,
        "counts": dict(sorted(counts.items())),
        "flagged_count": sum(counts[name] for name in ("REVIEW", "BLOCK", "ERROR")),
        "elapsed_seconds": elapsed,
        "throughput_images_per_second": completed_count / elapsed if elapsed else None,
        "policy": config.policy_name,
        "provider": config.provider,
        "thread_plan": {
            "requested_threads": config.threads,
            "effective_threads": effective_threads,
            "auto_tuned": config.provider == "cpu" and config.threads == 0,
            "strategy": "bounded_physical_cores_per_folder_worker",
        },
        "worker_plan": plan.to_dict(),
        "measurement_quality": {
            "headline_eligible": not environment_warnings,
            "warnings": environment_warnings,
        },
        "limits": {
            "max_bytes": config.max_bytes,
            "max_pixels": config.max_pixels,
            "recursive": config.recursive,
            "max_files": config.max_files,
        },
        "timings_ms": {name: value.to_dict() for name, value in metrics.items()},
        "timing_semantics": {
            "total_ms": "per-file latency including queueing inside shared inference",
            "inference_ms": "includes waiting for the serialized GPU session when workers exceed one",
        },
        "resources": {
            "peak_process_rss_bytes": peak_rss,
            "gpu_at_start": gpu_before,
            "gpu_peak_observed": gpu_peak,
            "gpu_at_end": gpu_after,
            "approximate_host_total_vram_delta_mib": gpu_delta,
            "gpu_witness": "host-total nvidia-smi sample; not per-process attribution",
            "timeline_sampling": "every 100 completed files plus final; bounded and decimated",
            "timeline": timeline_samples,
        },
        "host": host,
        "model": backend.evidence,
        "reports": {
            "summary": str(run_dir / "summary.json"),
            "all_results": str(full_path),
            "flags": str(flags_path),
            "links_index": str(links_index) if links_index is not None else None,
            "metrics_chart": str(metrics_path),
        },
        "flag_semantics": "REVIEW, BLOCK, and ERROR; source images are unchanged",
    }
    write_json_atomic(run_dir / "summary.json", summary)
    write_json_atomic(
        run_dir / "status.json",
        {"run_id": run_id, "complete": True, "selection_truncated": selection_truncated},
    )
    output_root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(output_root / "latest-summary.json", summary)
    copy_atomic(flags_path, output_root / "latest-flags.jsonl")
    if links_index is not None:
        write_text_atomic(
            output_root / "OPEN-LATEST-RESULTS.url",
            f"[InternetShortcut]\nURL={links_index.resolve().as_uri()}\n",
        )
        write_text_atomic(
            output_root / "OPEN-LATEST-RESULTS.html",
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            "<title>Latest NSFW Guard review</title></head><body>"
            f'<a href="{html.escape(links_index.resolve().as_uri(), quote=True)}">'
            "Open latest review links</a></body></html>\n",
        )
    return FolderScanOutcome(summary=summary, exit_code=_exit_code(counts, config.fail_on))


def _parse_workers(value: str) -> int | None:
    if value.casefold() == "auto":
        return None
    try:
        workers = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("workers must be 'auto' or a positive integer") from exc
    if workers < 1:
        raise argparse.ArgumentTypeError("workers must be 'auto' or a positive integer")
    return workers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nsfw-guard folder",
        description="Scan a folder with bounded parallelism and non-destructive reports.",
    )
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-recursive", action="store_true")
    parser.add_argument(
        "--links",
        action="store_true",
        help="Create portable HTML review indexes and Windows .url shortcuts.",
    )
    parser.add_argument("--policy", choices=POLICY_NAMES, default="medium-threshold-v1")
    parser.add_argument("--provider", choices=PROVIDER_NAMES, default="cpu")
    parser.add_argument(
        "--threads",
        type=int,
        default=0,
        help="Inference threads; 0 auto-tunes bounded CPU folder runs.",
    )
    parser.add_argument("--cuda-arena-limit-mib", type=int)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--max-bytes-mib", type=float, default=25.0)
    parser.add_argument("--max-pixels", type=int, default=40_000_000)
    parser.add_argument("--workers", type=_parse_workers, default=None, metavar="AUTO_OR_N")
    parser.add_argument("--max-in-flight", type=int)
    parser.add_argument(
        "--memory-budget-mib",
        type=int,
        help="Advisory worker-planning budget, not an OS hard memory cap.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        help=(
            f"Scan only the first N images in deterministic path order "
            f"(1..{MAX_DISCOVERY_FILES}); the full candidate count is reported."
        ),
    )
    parser.add_argument("--progress-every", type=int, default=100)
    parser.add_argument("--fail-on", choices=("never", "error", "block", "review"), default="error")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        outcome = scan_folder(
            FolderScanConfig(
                root=arguments.folder,
                output_dir=arguments.output_dir,
                recursive=not arguments.no_recursive,
                create_links=arguments.links,
                policy_name=arguments.policy,
                provider=arguments.provider,
                threads=arguments.threads,
                cuda_arena_limit_mib=arguments.cuda_arena_limit_mib,
                model_path=arguments.model_path,
                allow_download=not arguments.no_download,
                max_bytes=int(arguments.max_bytes_mib * MIB),
                max_pixels=arguments.max_pixels,
                requested_workers=arguments.workers,
                max_in_flight=arguments.max_in_flight,
                memory_budget_mib=arguments.memory_budget_mib,
                max_files=arguments.max_files,
                progress_every=arguments.progress_every,
                fail_on=arguments.fail_on,
            )
        )
    except GuardError as exc:
        print(json.dumps({"ok": False, "error": exc.to_dict()}), file=sys.stderr)
        return 30
    except OSError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "io_error",
                        "message": "The folder report could not be created.",
                        "details": {"exception_type": type(exc).__name__},
                        "retryable": False,
                    },
                }
            ),
            file=sys.stderr,
        )
        return 30
    if arguments.json:
        print(json.dumps(outcome.summary, ensure_ascii=True, sort_keys=True))
    else:
        counts = cast(dict[str, int], outcome.summary["counts"])
        reports = cast(JsonObject, outcome.summary["reports"])
        print("NSFW Guard folder scan complete")
        print(f"Images: {outcome.summary['scanned_count']}")
        discovery = cast(JsonObject, outcome.summary["discovery"])
        if discovery["selection_truncated"]:
            print(
                f"Partial selection: {discovery['selected_count']} of "
                f"{discovery['supported_candidate_count']} supported images "
                "(--max-files)."
            )
        print(
            f"ALLOW {counts.get('ALLOW', 0)} | REVIEW {counts.get('REVIEW', 0)} | "
            f"BLOCK {counts.get('BLOCK', 0)} | ERROR {counts.get('ERROR', 0)}"
        )
        print(f"Throughput: {outcome.summary['throughput_images_per_second']:.2f} images/s")
        print(f"Summary: {reports['summary']}")
        if reports["links_index"] is not None:
            print(f"Links: {reports['links_index']}")
    return outcome.exit_code
