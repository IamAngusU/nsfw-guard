from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap NSFW Guard locally.")
    parser.add_argument(
        "--runtime",
        choices=("cpu", "directml", "cuda", "cuda-bundled"),
        default="cpu",
    )
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--skip-model", action="store_true")
    parser.add_argument("--skip-checks", action="store_true")
    return parser


def run(command: list[str], *, cwd: Path) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    environment = root / ".venv"
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    if not python.exists():
        run([sys.executable, "-m", "venv", str(environment)], cwd=root)
    extras = [arguments.runtime]
    if arguments.dev:
        extras.append("dev")
    requirement = f".[{','.join(extras)}]"
    run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-e", requirement],
        cwd=root,
    )
    cli = scripts / ("nsfw-guard.exe" if os.name == "nt" else "nsfw-guard")
    if not arguments.skip_model:
        run([str(cli), "model", "install"], cwd=root)
    if arguments.dev and not arguments.skip_checks:
        run([str(python), "scripts/validate_local.py"], cwd=root)
    provider = "cuda" if arguments.runtime in {"cuda", "cuda-bundled"} else arguments.runtime
    provider_options = " --cuda-arena-limit-mib 64" if provider == "cuda" else ""
    print("NSFW Guard is ready.")
    print(f"Run: {cli} folder PATH --provider {provider}{provider_options} --links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
