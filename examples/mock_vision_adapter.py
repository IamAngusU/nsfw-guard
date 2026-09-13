from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import cast

from PIL import Image

PROTOCOL = "nsfw-guard.vision-adapter"
VERSION = 1


def respond(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=True, separators=(",", ":")), flush=True)


for line in sys.stdin:
    try:
        raw = json.loads(line)
        request = cast(dict[str, object], raw)
        request_id = str(request.get("request_id", ""))
        if request.get("protocol") != PROTOCOL or request.get("version") != VERSION:
            raise ValueError("unsupported protocol")
        if request.get("type") == "hello":
            respond(
                {
                    "protocol": PROTOCOL,
                    "version": VERSION,
                    "type": "hello",
                    "request_id": request_id,
                    "ok": True,
                    "adapter": "mock-vision",
                    "tasks": ["describe", "classify"],
                    "persistent_process_id": os.getpid(),
                }
            )
            continue
        if request.get("type") != "analyze":
            raise ValueError("unsupported request type")
        input_value = request.get("input")
        if not isinstance(input_value, dict) or input_value.get("kind") != "local-path":
            raise ValueError("mock adapter expects a local path")
        source = Path(str(input_value["path"]))
        with Image.open(source) as image:
            width, height = image.size
            media_format = image.format or "unknown"
        respond(
            {
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
        )
    except Exception as exc:
        respond(
            {
                "protocol": PROTOCOL,
                "version": VERSION,
                "type": "result",
                "request_id": str(locals().get("request_id", "")),
                "ok": False,
                "error": str(exc)[:300],
            }
        )
