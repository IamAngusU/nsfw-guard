from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast

from PIL import Image

PROTOCOL = "nsfw-guard.vision-adapter"
VERSION = 1


def _respond(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=True, separators=(",", ":")), flush=True)


def _handle(request: dict[str, object]) -> dict[str, object]:
    request_id = str(request.get("request_id", ""))
    if request.get("protocol") != PROTOCOL or request.get("version") != VERSION:
        raise ValueError("unsupported protocol")
    if request.get("type") == "hello":
        return {
            "protocol": PROTOCOL,
            "version": VERSION,
            "type": "hello",
            "request_id": request_id,
            "ok": True,
            "adapter": "mock-vision",
            "tasks": ["describe", "classify"],
            "persistent_process_id": os.getpid(),
        }
    if request.get("type") != "analyze":
        raise ValueError("unsupported request type")
    input_value = request.get("input")
    if not isinstance(input_value, dict) or input_value.get("kind") != "local-path":
        raise ValueError("mock adapter expects a local path")
    source = Path(str(input_value["path"]))
    with Image.open(source) as image:
        width, height = image.size
        media_format = image.format or "unknown"
    return {
        "protocol": PROTOCOL,
        "version": VERSION,
        "type": "result",
        "request_id": request_id,
        "ok": True,
        "outputs": {
            "description": (
                f"Mock protocol check: {width}x{height} {media_format}; "
                "no semantic model was executed."
            ),
            "labels": [{"name": "mock", "score": 1.0}],
        },
        "usage": {"model_calls": 0, "process_id": os.getpid()},
    }


def main() -> int:
    request_id = ""
    for line in sys.stdin:
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("request must be an object")
            request = cast(dict[str, object], value)
            request_id = str(request.get("request_id", ""))
            _respond(_handle(request))
        except (OSError, ValueError) as exc:
            _respond(
                {
                    "protocol": PROTOCOL,
                    "version": VERSION,
                    "type": "result",
                    "request_id": request_id,
                    "ok": False,
                    "error": str(exc)[:300],
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
