from __future__ import annotations

import base64
import io
import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast

import pytest
from PIL import Image, PngImagePlugin

from nsfw_guard.vision_adapters import (
    HttpVisionAdapter,
    VisionAdapterError,
    close_adapters,
    create_adapters,
)
from nsfw_guard.vision_config import load_vision_config


class _State:
    def __init__(self, *, large_analysis: bool) -> None:
        self.large_analysis = large_analysis
        self.requests: list[dict[str, object]] = []
        self.client_ports: list[int] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_POST(self) -> None:
        state = cast(_State, self.server.state)  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length", "0"))
        request = json.loads(self.rfile.read(length))
        state.requests.append(cast(dict[str, object], request))
        state.client_ports.append(self.client_address[1])
        if request["type"] == "hello":
            response = {
                "protocol": "nsfw-guard.vision-adapter",
                "version": 1,
                "type": "hello",
                "request_id": request["request_id"],
                "ok": True,
                "tasks": ["describe"],
            }
            body = json.dumps(response).encode("utf-8")
        elif state.large_analysis:
            body = b"x" * 2048
        else:
            response = {
                "protocol": "nsfw-guard.vision-adapter",
                "version": 1,
                "type": "result",
                "request_id": request["request_id"],
                "ok": True,
                "outputs": {"description": "local HTTP adapter"},
            }
            body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@contextmanager
def _server(*, large_analysis: bool = False) -> Iterator[tuple[str, _State]]:
    state = _State(large_analysis=large_analysis)
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.state = state  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/analyze", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def _config(
    path: Path, url: str, *, response_kib: int = 256, sanitize_remote_images: bool = True
) -> None:
    path.write_text(
        f"""schema_version = 1
[privacy]
mode = "local-only"
sanitize_remote_images = {str(sanitize_remote_images).lower()}
remote_max_edge = 128
max_response_kib = {response_kib}
[[models]]
id = "loopback"
adapter = "http-json"
url = "{url}"
tasks = ["describe"]
when = ["ALL"]
timeout_seconds = 5
""",
        encoding="utf-8",
    )


def test_loopback_http_reuses_connection_and_receives_sanitized_pixels(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private", "remove-me")
    Image.new("RGB", (200, 100), "orange").save(source, pnginfo=metadata)
    with _server() as (url, state):
        config_path = tmp_path / "vision.toml"
        _config(config_path, url)
        adapters = create_adapters(load_vision_config(config_path))
        try:
            adapter = cast(HttpVisionAdapter, adapters["loopback"])
            response = adapter.analyze(source, tasks=("describe",), context={})
        finally:
            close_adapters(adapters)

    assert response["ok"] is True
    assert len(state.requests) == 2
    assert len(set(state.client_ports)) == 1
    image_input = cast(dict[str, object], state.requests[1]["input"])
    assert image_input["metadata_removed"] is True
    content = base64.b64decode(cast(str, image_input["data"]))
    with Image.open(io.BytesIO(content)) as remote_image:
        assert remote_image.format == "JPEG"
        assert max(remote_image.size) == 128
        assert not remote_image.getexif()


def test_unsanitized_http_mime_uses_image_bytes(tmp_path: Path) -> None:
    source = tmp_path / "misnamed.jpg"
    Image.new("RGB", (16, 16), "red").save(source, format="PNG")
    original_bytes = source.read_bytes()
    with _server() as (url, state):
        config_path = tmp_path / "vision.toml"
        _config(config_path, url, sanitize_remote_images=False)
        adapters = create_adapters(load_vision_config(config_path))
        try:
            response = adapters["loopback"].analyze(source, tasks=("describe",), context={})
        finally:
            close_adapters(adapters)

    assert response["ok"] is True
    image_input = cast(dict[str, object], state.requests[1]["input"])
    assert image_input["mime_type"] == "image/png"
    assert image_input["metadata_removed"] is False
    assert base64.b64decode(cast(str, image_input["data"])) == original_bytes


def test_http_response_limit_stops_without_retry(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (32, 32), "blue").save(source)
    with _server(large_analysis=True) as (url, state):
        config_path = tmp_path / "vision.toml"
        _config(config_path, url, response_kib=1)
        adapters = create_adapters(load_vision_config(config_path))
        try:
            with pytest.raises(VisionAdapterError, match="declared limit"):
                adapters["loopback"].analyze(source, tasks=("describe",), context={})
        finally:
            close_adapters(adapters)

    assert len(state.requests) == 2
