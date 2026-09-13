from __future__ import annotations

import sys
from collections.abc import Sequence

from .cli import main as legacy_main
from .folder_scan import main as folder_main
from .metrics_chart import main as chart_main

TOP_LEVEL_HELP = """usage: nsfw-guard COMMAND [OPTIONS]

Local-first image safety decisions.

commands:
  scan       Scan one or more image files
  folder     Scan a folder with bounded parallelism and optional link collections
  bridge     Run the safety-bridge/v1 NDJSON service
  benchmark  Measure one warm model session
  chart      Render versioned benchmark history as a light-mode SVG
  model      Install or inspect the pinned model

Run `nsfw-guard COMMAND --help` for command-specific options.
"""


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments in (["-h"], ["--help"]):
        print(TOP_LEVEL_HELP)
        return 0
    command = arguments[0]
    if command == "folder":
        return folder_main(arguments[1:])
    if command == "chart":
        return chart_main(arguments[1:])
    return legacy_main(arguments)
