from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    steps = [
        ("compile", [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"]),
        ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ("format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
        ("mypy", [sys.executable, "-m", "mypy", "--strict", "src", "scripts"]),
        ("tests", [sys.executable, "-m", "pytest", "-q", "-W", "error"]),
    ]
    started = time.perf_counter()
    for name, command in steps:
        step_started = time.perf_counter()
        completed = subprocess.run(command, cwd=root, check=False)
        elapsed = time.perf_counter() - step_started
        if completed.returncode:
            print(f"{name}: failed ({elapsed:.2f}s)")
            return completed.returncode
        print(f"{name}: passed ({elapsed:.2f}s)")
    print(f"validation: passed ({time.perf_counter() - started:.2f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
