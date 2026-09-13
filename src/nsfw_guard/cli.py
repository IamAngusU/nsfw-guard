from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .backend import OnnxBackend
from .benchmark import run_benchmark
from .bridge import BridgeServer, serve_stream
from .contracts import Verdict
from .errors import GuardError
from .model_store import install_model, model_status
from .policy import POLICY_PROFILES, get_policy
from .scanner import ScanLimits, Scanner

EXIT_CODES = {
    Verdict.ALLOW: 0,
    Verdict.REVIEW: 10,
    Verdict.BLOCK: 20,
    Verdict.ERROR: 30,
}


def _add_runtime_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--policy",
        choices=sorted(POLICY_PROFILES),
        default="balanced-v1",
        help="Decision policy profile (default: balanced-v1).",
    )
    parser.add_argument("--provider", choices=("cpu", "cuda", "directml"), default="cpu")
    parser.add_argument(
        "--cuda-arena-limit-mib",
        type=int,
        help="Required for CUDA; advisory ONNX Runtime arena limit.",
    )
    parser.add_argument("--threads", type=int, default=0, help="CPU inference threads; 0 is auto.")
    parser.add_argument("--model-path", type=Path, help="Offline copy of the pinned model.")
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Never download a missing model.",
    )
    parser.add_argument("--max-bytes-mib", type=float, default=25.0)
    parser.add_argument("--max-pixels", type=int, default=40_000_000)
    parser.add_argument("--cache-entries", type=int, default=512)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nsfw-guard",
        description="Local-first image safety decisions with explicit uncertainty.",
    )
    parser.add_argument("--version", action="version", version=f"nsfw-guard {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser("scan", help="Scan one or more local image files.")
    scan.add_argument("paths", nargs="+", type=Path)
    scan.add_argument("--json", action="store_true", help="Write one JSON result per input.")
    scan.add_argument("--sha256", help="Expected digest; accepted only with exactly one input.")
    _add_runtime_options(scan)

    bridge = commands.add_parser("bridge", help="Run the NDJSON safety bridge on stdin/stdout.")
    bridge.add_argument(
        "--allow-root",
        action="append",
        type=Path,
        help="Allowed file root; repeat as needed. Defaults to the current directory.",
    )
    _add_runtime_options(bridge)

    benchmark = commands.add_parser("benchmark", help="Measure local synthetic runtime speed.")
    benchmark.add_argument("--runs", type=int, default=30)
    benchmark.add_argument("--warmups", type=int, default=3)
    benchmark.add_argument("--output", type=Path)
    _add_runtime_options(benchmark)

    model = commands.add_parser("model", help="Manage the pinned model artifact.")
    model_commands = model.add_subparsers(dest="model_command", required=True)
    model_install = model_commands.add_parser("install", help="Download and verify the model.")
    model_install.add_argument("--path", type=Path)
    model_status_parser = model_commands.add_parser("status", help="Inspect model integrity.")
    model_status_parser.add_argument("--path", type=Path)
    return parser


def _scanner_from_args(args: argparse.Namespace, *, cache_entries: int | None = None) -> Scanner:
    max_bytes = int(args.max_bytes_mib * 1024 * 1024)
    limits = ScanLimits(max_bytes=max_bytes, max_pixels=args.max_pixels)
    backend = OnnxBackend(
        provider=args.provider,
        threads=args.threads,
        cuda_arena_limit_mib=args.cuda_arena_limit_mib,
        model_path=args.model_path,
        allow_download=not args.no_download,
    )
    return Scanner(
        backend=backend,
        policy=get_policy(args.policy),
        limits=limits,
        cache_entries=args.cache_entries if cache_entries is None else cache_entries,
    )


def _scan_command(args: argparse.Namespace) -> int:
    if args.sha256 and len(args.paths) != 1:
        raise ValueError("--sha256 requires exactly one input path")
    scanner = _scanner_from_args(args)
    highest_exit = 0
    for path in args.paths:
        try:
            result = scanner.scan_path(path, claimed_sha256=args.sha256)
            payload: dict[str, object] = {"input": str(path), "result": result.to_dict()}
            exit_code = EXIT_CODES[result.verdict]
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                score = result.scores["nsfw"] if result.scores else None
                score_text = "n/a" if score is None else f"{score:.6f}"
                print(
                    f"{result.verdict.value:6} nsfw={score_text} "
                    f"total_ms={result.timing.total_ms:.2f} {path}"
                )
        except GuardError as exc:
            payload = {"input": str(path), "verdict": Verdict.ERROR.value, "error": exc.to_dict()}
            exit_code = EXIT_CODES[Verdict.ERROR]
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print(f"ERROR  {exc.code}: {path}", file=sys.stderr)
        highest_exit = max(highest_exit, exit_code)
    return highest_exit


def _bridge_command(args: argparse.Namespace) -> int:
    scanner = _scanner_from_args(args)
    roots = args.allow_root or [Path.cwd()]
    server = BridgeServer(scanner, roots)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    serve_stream(server, sys.stdin, sys.stdout)
    return 0


def _benchmark_command(args: argparse.Namespace) -> int:
    scanner = _scanner_from_args(args, cache_entries=0)
    report = run_benchmark(
        scanner,
        runs=args.runs,
        warmups=args.warmups,
        output_path=args.output,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _model_command(args: argparse.Namespace) -> int:
    if args.model_command == "install":
        path = install_model(args.path)
        print(json.dumps(model_status(path), indent=2, sort_keys=True))
        return 0
    print(json.dumps(model_status(args.path), indent=2, sort_keys=True))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "scan":
            return _scan_command(args)
        if args.command == "bridge":
            return _bridge_command(args)
        if args.command == "benchmark":
            return _benchmark_command(args)
        if args.command == "model":
            return _model_command(args)
    except GuardError as exc:
        print(json.dumps({"verdict": Verdict.ERROR.value, "error": exc.to_dict()}), file=sys.stderr)
        return EXIT_CODES[Verdict.ERROR]
    except ValueError as exc:
        parser.error(str(exc))
    return EXIT_CODES[Verdict.ERROR]


if __name__ == "__main__":
    raise SystemExit(main())
