from __future__ import annotations

import base64
import http.client
import io
import json
import os
import queue
import ssl
import subprocess
import sys
import threading
import uuid
from contextlib import suppress
from pathlib import Path
from types import TracebackType
from typing import cast
from urllib.parse import urlsplit

from PIL import Image, ImageOps, UnidentifiedImageError

from .vision_config import (
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
    PrivacyConfig,
    VisionConfig,
    VisionModelConfig,
)

JsonObject = dict[str, object]
IMAGE_FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": (".jpg", "image/jpeg"),
    "PNG": (".png", "image/png"),
    "WEBP": (".webp", "image/webp"),
}


class VisionAdapterError(RuntimeError):
    pass


def _json_object(raw: bytes, *, model_id: str) -> JsonObject:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    try:
        value = json.loads(raw, parse_constant=reject_constant)
    except (UnicodeDecodeError, RecursionError, ValueError) as exc:
        raise VisionAdapterError(f"adapter {model_id} returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise VisionAdapterError(f"adapter {model_id} response must be a JSON object")
    return cast(JsonObject, value)


def _validate_response(
    response: JsonObject, *, model_id: str, request_id: str, response_type: str
) -> JsonObject:
    if response.get("protocol") != PROTOCOL_NAME:
        raise VisionAdapterError(f"adapter {model_id} returned the wrong protocol")
    if response.get("version") != PROTOCOL_VERSION:
        raise VisionAdapterError(f"adapter {model_id} returned an unsupported version")
    if response.get("type") != response_type:
        raise VisionAdapterError(f"adapter {model_id} returned the wrong response type")
    if response.get("request_id") != request_id:
        raise VisionAdapterError(f"adapter {model_id} returned the wrong request id")
    if not isinstance(response.get("ok"), bool):
        raise VisionAdapterError(f"adapter {model_id} response has no boolean ok field")
    return response


def _verify_capabilities(response: JsonObject, model: VisionModelConfig) -> None:
    if response.get("ok") is not True:
        raise VisionAdapterError(f"adapter {model.id} rejected the handshake")
    tasks = response.get("tasks")
    if not isinstance(tasks, list) or not all(isinstance(task, str) for task in tasks):
        raise VisionAdapterError(f"adapter {model.id} did not declare task capabilities")
    missing = set(model.tasks) - set(cast(list[str], tasks))
    if missing:
        raise VisionAdapterError(
            f"adapter {model.id} does not support configured tasks: {sorted(missing)}"
        )


class VisionAdapter:
    def __init__(self, model: VisionModelConfig, privacy: PrivacyConfig) -> None:
        self.model = model
        self.privacy = privacy
        self.capabilities: JsonObject = {}

    def analyze(self, source: Path, *, tasks: tuple[str, ...], context: JsonObject) -> JsonObject:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError

    def __enter__(self) -> VisionAdapter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class CommandVisionAdapter(VisionAdapter):
    def __init__(
        self, model: VisionModelConfig, privacy: PrivacyConfig, working_directory: Path
    ) -> None:
        super().__init__(model, privacy)
        if model.command is None:
            raise VisionAdapterError(f"adapter {model.id} has no command")
        environment = os.environ.copy()
        environment["NSFW_GUARD_VISION_PROTOCOL"] = str(PROTOCOL_VERSION)
        command = tuple(
            sys.executable if argument == "{python}" else argument for argument in model.command
        )
        try:
            self._process = subprocess.Popen(
                command,
                cwd=str(working_directory),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=environment,
                bufsize=0,
            )
        except OSError as exc:
            raise VisionAdapterError(f"cannot start adapter {model.id}: {exc}") from exc
        if self._process.stdin is None or self._process.stdout is None:
            self._process.kill()
            raise VisionAdapterError(f"adapter {model.id} has no protocol pipes")
        self._responses: queue.Queue[bytes | None] = queue.Queue(maxsize=4)
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()
        self._lock = threading.Lock()
        try:
            self.capabilities = self._exchange(
                {
                    "protocol": PROTOCOL_NAME,
                    "version": PROTOCOL_VERSION,
                    "type": "hello",
                    "request_id": uuid.uuid4().hex,
                },
                response_type="hello",
            )
            _verify_capabilities(self.capabilities, model)
        except VisionAdapterError:
            self.close()
            raise

    def _read_stdout(self) -> None:
        stdout = self._process.stdout
        if stdout is None:
            self._responses.put(None)
            return
        while True:
            line = stdout.readline(self.privacy.max_response_bytes + 2)
            if not line:
                self._responses.put(None)
                return
            self._responses.put(line)

    def _exchange(self, payload: JsonObject, *, response_type: str) -> JsonObject:
        request_id = str(payload["request_id"])
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        with self._lock:
            stdin = self._process.stdin
            if stdin is None or self._process.poll() is not None:
                raise VisionAdapterError(f"adapter {self.model.id} is not running")
            try:
                stdin.write(encoded)
                stdin.flush()
            except OSError as exc:
                raise VisionAdapterError(f"adapter {self.model.id} write failed") from exc
            try:
                raw = self._responses.get(timeout=self.model.timeout_seconds)
            except queue.Empty as exc:
                self._process.kill()
                raise VisionAdapterError(f"adapter {self.model.id} timed out") from exc
        if raw is None:
            raise VisionAdapterError(f"adapter {self.model.id} exited without a response")
        if len(raw) > self.privacy.max_response_bytes:
            self._process.kill()
            raise VisionAdapterError(f"adapter {self.model.id} response exceeded its limit")
        response = _json_object(raw, model_id=self.model.id)
        return _validate_response(
            response,
            model_id=self.model.id,
            request_id=request_id,
            response_type=response_type,
        )

    def analyze(self, source: Path, *, tasks: tuple[str, ...], context: JsonObject) -> JsonObject:
        request_id = uuid.uuid4().hex
        return self._exchange(
            {
                "protocol": PROTOCOL_NAME,
                "version": PROTOCOL_VERSION,
                "type": "analyze",
                "request_id": request_id,
                "tasks": list(tasks),
                "input": {"kind": "local-path", "path": str(source.resolve())},
                "context": context,
            },
            response_type="result",
        )

    def close(self) -> None:
        stdin = self._process.stdin
        if stdin is not None and not stdin.closed:
            with suppress(OSError):
                stdin.close()
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2.0)
        self._reader.join(timeout=2.0)
        stdout = self._process.stdout
        if stdout is not None and not stdout.closed:
            stdout.close()


def _sanitized_jpeg(source: Path, privacy: PrivacyConfig) -> bytes:
    try:
        with Image.open(source) as opened:
            opened.seek(0)
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail(
                (privacy.remote_max_edge, privacy.remote_max_edge),
                Image.Resampling.LANCZOS,
            )
            output = io.BytesIO()
            image.save(
                output,
                format="JPEG",
                quality=privacy.remote_jpeg_quality,
                optimize=False,
                progressive=False,
            )
    except (OSError, ValueError) as exc:
        raise VisionAdapterError("remote image sanitization failed") from exc
    encoded = output.getvalue()
    if len(encoded) > privacy.max_upload_bytes:
        raise VisionAdapterError("sanitized remote image exceeded its upload limit")
    return encoded


def _remote_image(source: Path, privacy: PrivacyConfig) -> tuple[bytes, str, bool]:
    if privacy.sanitize_remote_images:
        return _sanitized_jpeg(source, privacy), "image/jpeg", True
    try:
        with source.open("rb") as handle:
            content = handle.read(privacy.max_upload_bytes + 1)
    except OSError as exc:
        raise VisionAdapterError("remote image read failed") from exc
    if len(content) > privacy.max_upload_bytes:
        raise VisionAdapterError("remote image exceeded its upload limit")
    try:
        with Image.open(io.BytesIO(content)) as image:
            media_format = (image.format or "").upper()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise VisionAdapterError("remote image format could not be identified") from exc
    if media_format not in IMAGE_FORMATS:
        raise VisionAdapterError("remote image format is not supported")
    mime_type = IMAGE_FORMATS[media_format][1]
    return content, mime_type, False


class HttpVisionAdapter(VisionAdapter):
    def __init__(self, model: VisionModelConfig, privacy: PrivacyConfig) -> None:
        super().__init__(model, privacy)
        if model.url is None:
            raise VisionAdapterError(f"adapter {model.id} has no URL")
        self._parsed = urlsplit(model.url)
        self._connection: http.client.HTTPConnection | None = None
        self._headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if model.auth_env is not None:
            token = os.environ.get(model.auth_env)
            if not token:
                raise VisionAdapterError(
                    f"adapter {model.id} requires environment variable {model.auth_env}"
                )
            self._headers["Authorization"] = f"Bearer {token}"
        try:
            self.capabilities = self._exchange(
                {
                    "protocol": PROTOCOL_NAME,
                    "version": PROTOCOL_VERSION,
                    "type": "hello",
                    "request_id": uuid.uuid4().hex,
                },
                response_type="hello",
            )
            _verify_capabilities(self.capabilities, model)
        except VisionAdapterError:
            self.close()
            raise

    def _connect(self) -> http.client.HTTPConnection:
        if self._connection is not None:
            return self._connection
        host = self._parsed.hostname
        if host is None:
            raise VisionAdapterError(f"adapter {self.model.id} URL has no host")
        if self._parsed.scheme == "https":
            self._connection = http.client.HTTPSConnection(
                host,
                self._parsed.port,
                timeout=self.model.timeout_seconds,
                context=ssl.create_default_context(),
            )
        else:
            self._connection = http.client.HTTPConnection(
                host, self._parsed.port, timeout=self.model.timeout_seconds
            )
        return self._connection

    def _exchange(self, payload: JsonObject, *, response_type: str) -> JsonObject:
        request_id = str(payload["request_id"])
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        maximum_request = (self.privacy.max_upload_bytes * 4 // 3) + 512 * 1024
        if len(body) > maximum_request:
            raise VisionAdapterError(f"adapter {self.model.id} request exceeded its limit")
        path = self._parsed.path or "/"
        if self._parsed.query:
            path = f"{path}?{self._parsed.query}"
        connection = self._connect()
        try:
            connection.request("POST", path, body=body, headers=self._headers)
            response = connection.getresponse()
            content_length = response.getheader("Content-Length")
            if content_length is not None and int(content_length) > self.privacy.max_response_bytes:
                self.close()
                raise VisionAdapterError(
                    f"adapter {self.model.id} response exceeded its declared limit"
                )
            raw = response.read(self.privacy.max_response_bytes + 1)
        except (OSError, http.client.HTTPException, ValueError) as exc:
            self.close()
            raise VisionAdapterError(f"adapter {self.model.id} HTTP request failed") from exc
        if len(raw) > self.privacy.max_response_bytes:
            self.close()
            raise VisionAdapterError(f"adapter {self.model.id} response exceeded its limit")
        if not 200 <= response.status < 300:
            raise VisionAdapterError(
                f"adapter {self.model.id} returned HTTP status {response.status}"
            )
        result = _json_object(raw, model_id=self.model.id)
        return _validate_response(
            result,
            model_id=self.model.id,
            request_id=request_id,
            response_type=response_type,
        )

    def analyze(self, source: Path, *, tasks: tuple[str, ...], context: JsonObject) -> JsonObject:
        image, mime_type, metadata_removed = _remote_image(source, self.privacy)
        return self._exchange(
            {
                "protocol": PROTOCOL_NAME,
                "version": PROTOCOL_VERSION,
                "type": "analyze",
                "request_id": uuid.uuid4().hex,
                "tasks": list(tasks),
                "input": {
                    "kind": "inline-image",
                    "mime_type": mime_type,
                    "encoding": "base64",
                    "data": base64.b64encode(image).decode("ascii"),
                    "byte_length": len(image),
                    "metadata_removed": metadata_removed,
                },
                "context": context,
            },
            response_type="result",
        )

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def create_adapters(config: VisionConfig) -> dict[str, VisionAdapter]:
    adapters: dict[str, VisionAdapter] = {}
    try:
        for model in config.enabled_models:
            adapter: VisionAdapter
            if model.adapter == "command":
                adapter = CommandVisionAdapter(model, config.privacy, config.path.parent)
            else:
                adapter = HttpVisionAdapter(model, config.privacy)
            adapters[model.id] = adapter
    except Exception:
        for adapter in adapters.values():
            adapter.close()
        raise
    return adapters


def close_adapters(adapters: dict[str, VisionAdapter]) -> None:
    for adapter in adapters.values():
        adapter.close()
