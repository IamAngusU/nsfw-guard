from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import shutil
import sys
import tempfile
import time
import warnings
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from PIL import Image, UnidentifiedImageError

from . import __version__
from .errors import GuardError
from .scanner import ScanLimits, read_bounded_image_path
from .vision_adapters import (
    IMAGE_FORMATS,
    JsonObject,
    VisionAdapter,
    VisionAdapterError,
    close_adapters,
    create_adapters,
)
from .vision_config import (
    VisionConfig,
    VisionConfigError,
    VisionModelConfig,
    load_vision_config,
    starter_config,
)
from .vision_resources import VisionResourceMonitor


@dataclass(frozen=True)
class VisionInput:
    results_path: Path
    root: Path
    source_run_id: str | None
    limits: ScanLimits = field(default_factory=ScanLimits)


@dataclass
class ModelStats:
    calls: int = 0
    errors: int = 0
    elapsed_ms: float = 0.0
    max_ms: float = 0.0

    def add(self, elapsed_ms: float, *, failed: bool) -> None:
        self.calls += 1
        self.errors += int(failed)
        self.elapsed_ms += elapsed_ms
        self.max_ms = max(self.max_ms, elapsed_ms)

    def evidence(self) -> dict[str, object]:
        return {
            "calls": self.calls,
            "errors": self.errors,
            "mean_ms": self.elapsed_ms / self.calls if self.calls else None,
            "max_ms": self.max_ms if self.calls else None,
        }


@dataclass(frozen=True)
class VisionRunOutcome:
    summary_path: Path
    results_path: Path
    records: int
    calls: int
    errors: int


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    with source.open("rb") as source_handle, temporary.open("wb") as output_handle:
        shutil.copyfileobj(source_handle, output_handle, length=1024 * 1024)
        output_handle.flush()
        os.fsync(output_handle.fileno())
    os.replace(temporary, destination)


def _json_file(path: Path) -> JsonObject:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise VisionConfigError(f"cannot read input summary: {exc}") from exc
    if not isinstance(value, dict):
        raise VisionConfigError("input summary must be a JSON object")
    return cast(JsonObject, value)


def resolve_vision_input(path: Path, explicit_root: Path | None) -> VisionInput:
    resolved = path.resolve()
    if resolved.suffix.lower() == ".jsonl":
        if explicit_root is None:
            raise VisionConfigError("--root is required when input is a JSONL file")
        return VisionInput(resolved, explicit_root.resolve(), None)

    summary = _json_file(resolved)
    reports = summary.get("reports")
    if not isinstance(reports, dict) or not isinstance(reports.get("all_results"), str):
        raise VisionConfigError("summary has no reports.all_results path")
    root_value = explicit_root if explicit_root is not None else summary.get("root")
    if not isinstance(root_value, (str, Path)):
        raise VisionConfigError("summary has no root path; pass --root")
    source_run_id = summary.get("run_id")
    limits_value = summary.get("limits", {})
    if not isinstance(limits_value, dict):
        raise VisionConfigError("input summary limits must be an object")
    defaults = ScanLimits()
    max_bytes = limits_value.get("max_bytes", defaults.max_bytes)
    max_pixels = limits_value.get("max_pixels", defaults.max_pixels)
    if any(type(value) is not int or value <= 0 for value in (max_bytes, max_pixels)):
        raise VisionConfigError("input summary image limits must be positive integers")
    return VisionInput(
        Path(cast(str, reports["all_results"])).resolve(),
        Path(root_value).resolve(),
        str(source_run_id) if source_run_id is not None else None,
        ScanLimits(max_bytes=max_bytes, max_pixels=max_pixels),
    )


def _safe_source(root: Path, relative_path: object) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        raise VisionAdapterError("input record has no relative_path")
    candidate = root / relative_path
    try:
        inside = os.path.commonpath((str(root), str(candidate.resolve()))) == str(root)
    except ValueError as exc:
        raise VisionAdapterError("input path is outside the source root") from exc
    if not inside:
        raise VisionAdapterError("input path is outside the source root")
    return candidate


def _verified_payload(source: Path, artifact: object, limits: ScanLimits) -> tuple[bytes, str]:
    if not isinstance(artifact, dict):
        raise VisionAdapterError("vision_source_missing_sha256_evidence")
    expected = artifact.get("sha256")
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected.lower())
    ):
        raise VisionAdapterError("vision_source_missing_sha256_evidence")
    try:
        payload, actual = read_bounded_image_path(source, limits)
    except GuardError as exc:
        raise VisionAdapterError(f"vision_source_unavailable: {exc.code}") from exc
    if not hmac.compare_digest(actual, expected.lower()):
        raise VisionAdapterError("vision_source_changed_after_base_scan")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as image:
                media_format = (image.format or "").upper()
                width, height = image.size
                if media_format not in limits.allowed_formats or media_format not in IMAGE_FORMATS:
                    raise VisionAdapterError("vision_source_unsupported_image_format")
                if width <= 0 or height <= 0 or width * height > limits.max_pixels:
                    raise VisionAdapterError("vision_source_exceeds_pixel_limit")
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise VisionAdapterError("vision_source_exceeds_pixel_limit") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise VisionAdapterError("vision_source_invalid_image") from exc

    return payload, media_format


def _clean_error(error: BaseException, root: Path) -> str:
    message = str(error).replace(str(root), "<source-root>")
    return message[:500] or error.__class__.__name__


def _selected(model_when: frozenset[str], verdict: str) -> bool:
    return "ALL" in model_when or verdict in model_when


def _run_selected_adapters(
    payload: bytes,
    suffix: str,
    record: JsonObject,
    verdict: str,
    models: tuple[VisionModelConfig, ...],
    adapters: dict[str, VisionAdapter],
    stats: dict[str, ModelStats],
    root: Path,
) -> tuple[list[JsonObject], int]:
    analyses: list[JsonObject] = []
    errors = 0
    context: JsonObject = {
        "base_verdict": verdict,
        "scores": record.get("scores"),
        "artifact": record.get("artifact"),
    }
    for model in models:
        started = time.perf_counter()
        failed = False
        analysis: JsonObject = {
            "model_id": model.id,
            "tasks": list(model.tasks),
            "adapter": model.adapter,
        }
        try:
            # A fresh copy per adapter prevents one adapter from changing a later
            # adapter's input. Neither adapter receives the mutable original path.
            with tempfile.TemporaryDirectory(prefix="nsfw-guard-vision-") as directory:
                staged = Path(directory) / f"verified{suffix}"
                staged.write_bytes(payload)
                response = adapters[model.id].analyze(staged, tasks=model.tasks, context=context)
            analysis["ok"] = bool(response.get("ok"))
            if response.get("ok") is True:
                analysis["outputs"] = response.get("outputs", {})
                analysis["usage"] = response.get("usage")
            else:
                failed = True
                errors += 1
                analysis["error"] = str(response.get("error", "adapter rejected request"))[:500]
        except (OSError, VisionAdapterError, ValueError) as exc:
            failed = True
            errors += 1
            analysis["ok"] = False
            analysis["error"] = _clean_error(exc, root)
        elapsed_ms = (time.perf_counter() - started) * 1000
        analysis["elapsed_ms"] = round(elapsed_ms, 4)
        stats[model.id].add(elapsed_ms, failed=failed)
        analyses.append(analysis)
    return analyses, errors


def _analyze_record(
    record: JsonObject,
    *,
    root: Path,
    config: VisionConfig,
    adapters: dict[str, VisionAdapter],
    stats: dict[str, ModelStats],
    limits: ScanLimits | None = None,
) -> tuple[JsonObject, int]:
    verdict = str(record.get("verdict", "ERROR")).upper()
    try:
        source = _safe_source(root, record.get("relative_path"))
    except VisionAdapterError as exc:
        return (
            {
                "schema_version": 1,
                "index": record.get("index"),
                "relative_path": record.get("relative_path"),
                "base_verdict": verdict,
                "analyses": [],
                "pipeline_error": _clean_error(exc, root),
            },
            1,
        )
    models = tuple(model for model in config.enabled_models if _selected(model.when, verdict))
    analyses: list[JsonObject] = []
    errors = 0
    if models:
        try:
            payload, media_format = _verified_payload(
                source, record.get("artifact"), limits or ScanLimits()
            )
            analyses, errors = _run_selected_adapters(
                payload,
                IMAGE_FORMATS[media_format][0],
                record,
                verdict,
                models,
                adapters,
                stats,
                root,
            )
        except (OSError, VisionAdapterError) as exc:
            return (
                {
                    "schema_version": 1,
                    "index": record.get("index"),
                    "relative_path": record.get("relative_path"),
                    "base_verdict": verdict,
                    "analyses": [],
                    "pipeline_error": _clean_error(exc, root),
                },
                1,
            )
    return (
        {
            "schema_version": 1,
            "index": record.get("index"),
            "relative_path": record.get("relative_path"),
            "base_verdict": verdict,
            "base_scores": record.get("scores"),
            "analyses": analyses,
        },
        errors,
    )


def enrich_vision_results(
    source: VisionInput,
    config: VisionConfig,
    output_root: Path,
    *,
    max_records: int | None = None,
    progress_every: int = 100,
) -> VisionRunOutcome:
    if not config.enabled_models:
        raise VisionConfigError("vision config has no enabled models")
    if max_records is not None and max_records < 1:
        raise VisionConfigError("max_records must be at least one")
    if progress_every < 0:
        raise VisionConfigError("progress_every cannot be negative")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    run_dir = output_root.resolve() / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    temporary = run_dir / ".vision-results.jsonl.tmp"
    results_path = run_dir / "vision-results.jsonl"
    stats = {model.id: ModelStats() for model in config.enabled_models}
    verdict_counts: Counter[str] = Counter()
    records = 0
    errors = 0
    started = time.perf_counter()
    monitor = VisionResourceMonitor()
    monitor.start()
    adapters: dict[str, VisionAdapter] = {}
    try:
        adapters = create_adapters(config)
        with (
            source.results_path.open("r", encoding="utf-8") as input_handle,
            temporary.open("w", encoding="utf-8", newline="\n") as output_handle,
        ):
            for line_number, line in enumerate(input_handle, start=1):
                if max_records is not None and records >= max_records:
                    break
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise VisionConfigError(f"invalid JSONL input at line {line_number}") from exc
                if not isinstance(raw, dict):
                    raise VisionConfigError(f"input line {line_number} is not an object")
                record = cast(JsonObject, raw)
                enriched, record_errors = _analyze_record(
                    record,
                    root=source.root,
                    config=config,
                    adapters=adapters,
                    stats=stats,
                    limits=source.limits,
                )
                output_handle.write(
                    json.dumps(enriched, ensure_ascii=True, separators=(",", ":")) + "\n"
                )
                records += 1
                errors += record_errors
                verdict_counts[str(enriched["base_verdict"])] += 1
                monitor.update(
                    records=records,
                    calls=sum(item.calls for item in stats.values()),
                )
                if progress_every > 0 and records % progress_every == 0:
                    elapsed = time.perf_counter() - started
                    print(
                        f"{records} records | {sum(item.calls for item in stats.values())} calls | "
                        f"{records / elapsed:.2f} records/s | errors={errors}",
                        file=sys.stderr,
                        flush=True,
                    )
            output_handle.flush()
            os.fsync(output_handle.fileno())
    finally:
        monitor.stop()
        close_adapters(adapters)
    os.replace(temporary, results_path)
    elapsed = time.perf_counter() - started
    total_calls = sum(item.calls for item in stats.values())
    metrics_path = monitor.render(
        run_dir / "metrics.svg",
        run_id=run_id,
        model_count=len(config.enabled_models),
    )
    summary: JsonObject = {
        "schema_version": 1,
        "run_id": run_id,
        "source_run_id": source.source_run_id,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "complete": True,
        "records": records,
        "adapter_calls": total_calls,
        "adapter_errors": errors,
        "elapsed_seconds": elapsed,
        "records_per_second": records / elapsed if elapsed else None,
        "verdict_counts": dict(sorted(verdict_counts.items())),
        "privacy": config.privacy.evidence(),
        "models": [
            {
                **model.evidence(),
                "capabilities": adapters[model.id].capabilities,
            }
            for model in config.enabled_models
        ],
        "model_metrics": {key: value.evidence() for key, value in stats.items()},
        "config_sha256": hashlib.sha256(config.path.read_bytes()).hexdigest(),
        "resources": monitor.evidence(),
        "source_results": str(source.results_path),
        "results": str(results_path),
        "metrics_chart": str(metrics_path),
        "application_version": __version__,
        "streaming": "record-by-record with atomic replace; no full input materialization",
    }
    summary_path = run_dir / "summary.json"
    _atomic_json(summary_path, summary)
    output_root.mkdir(parents=True, exist_ok=True)
    _atomic_json(output_root / "latest-summary.json", summary)
    _copy_atomic(results_path, output_root / "latest-results.jsonl")
    return VisionRunOutcome(summary_path, results_path, records, total_calls, errors)


def doctor(config: VisionConfig) -> JsonObject:
    adapters = create_adapters(config)
    try:
        return {
            "ok": True,
            "protocol": "nsfw-guard.vision-adapter",
            "version": 1,
            "privacy": config.privacy.evidence(),
            "models": [
                {
                    "config": model.evidence(),
                    "capabilities": adapters[model.id].capabilities,
                }
                for model in config.enabled_models
            ],
        }
    finally:
        close_adapters(adapters)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nsfw-guard vision",
        description="Attach optional local or explicitly approved remote vision models.",
    )
    commands = parser.add_subparsers(dest="vision_command", required=True)
    init = commands.add_parser("init", help="Write a safe disabled starter config")
    init.add_argument("--output", type=Path, default=Path("vision.toml"))
    init.add_argument("--force", action="store_true")
    doctor_parser = commands.add_parser("doctor", help="Validate config and handshakes")
    doctor_parser.add_argument("--config", type=Path, default=Path("vision.toml"))
    enrich = commands.add_parser("enrich", help="Stream adapters over an existing folder run")
    enrich.add_argument("input", type=Path, help="Folder summary JSON or all-results JSONL")
    enrich.add_argument("--config", type=Path, default=Path("vision.toml"))
    enrich.add_argument("--root", type=Path)
    enrich.add_argument("--output-dir", type=Path)
    enrich.add_argument("--max-records", type=int)
    enrich.add_argument("--progress-every", type=int, default=100)
    enrich.add_argument("--fail-on", choices=("never", "error"), default="error")
    enrich.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.vision_command == "init":
            output = cast(Path, args.output).resolve()
            if output.exists() and not args.force:
                raise VisionConfigError(f"config already exists: {output}")
            _atomic_text(output, starter_config())
            print(output)
            return 0
        config = load_vision_config(cast(Path, args.config))
        if args.vision_command == "doctor":
            print(json.dumps(doctor(config), ensure_ascii=True, indent=2, sort_keys=True))
            return 0
        source = resolve_vision_input(cast(Path, args.input), cast(Path | None, args.root))
        output_dir = cast(Path | None, args.output_dir) or source.results_path.parent / "vision"
        outcome = enrich_vision_results(
            source,
            config,
            output_dir,
            max_records=cast(int | None, args.max_records),
            progress_every=cast(int, args.progress_every),
        )
        result = {
            "summary": str(outcome.summary_path),
            "results": str(outcome.results_path),
            "records": outcome.records,
            "calls": outcome.calls,
            "errors": outcome.errors,
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        else:
            print("NSFW Guard vision enrichment complete")
            print(f"Records: {outcome.records} | calls: {outcome.calls} | errors: {outcome.errors}")
            print(f"Summary: {outcome.summary_path}")
            print(f"Results: {outcome.results_path}")
        return 31 if args.fail_on == "error" and outcome.errors else 0
    except (OSError, VisionAdapterError, VisionConfigError) as exc:
        print(f"vision error: {exc}", file=sys.stderr)
        return 30
