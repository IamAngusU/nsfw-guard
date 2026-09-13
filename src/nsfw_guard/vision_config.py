from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

PROTOCOL_NAME = "nsfw-guard.vision-adapter"
PROTOCOL_VERSION = 1
PRIVACY_MODES = frozenset({"local-only", "remote-tls"})
ADAPTER_TYPES = frozenset({"command", "http-json"})
ROUTES = frozenset({"ALL", "ALLOW", "REVIEW", "BLOCK", "ERROR"})
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
_TOMLLIB = import_module("tomllib")


class VisionConfigError(ValueError):
    pass


@dataclass(frozen=True)
class PrivacyConfig:
    mode: str
    acknowledge_remote_image_disclosure: bool
    sanitize_remote_images: bool
    remote_max_edge: int
    remote_jpeg_quality: int
    max_upload_bytes: int
    max_response_bytes: int

    def evidence(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "remote_image_disclosure_acknowledged": (self.acknowledge_remote_image_disclosure),
            "sanitize_remote_images": self.sanitize_remote_images,
            "remote_max_edge": self.remote_max_edge,
            "remote_jpeg_quality": self.remote_jpeg_quality,
            "max_upload_bytes": self.max_upload_bytes,
            "max_response_bytes": self.max_response_bytes,
            "e2ee_claimed": False,
        }


@dataclass(frozen=True)
class VisionModelConfig:
    id: str
    adapter: str
    enabled: bool
    tasks: tuple[str, ...]
    when: frozenset[str]
    timeout_seconds: float
    trusted: bool
    command: tuple[str, ...] | None
    url: str | None
    auth_env: str | None

    def evidence(self) -> dict[str, object]:
        return {
            "id": self.id,
            "adapter": self.adapter,
            "enabled": self.enabled,
            "tasks": list(self.tasks),
            "when": sorted(self.when),
            "timeout_seconds": self.timeout_seconds,
            "transport": ("trusted-local-command" if self.adapter == "command" else "http-json"),
            "url_origin": _url_origin(self.url) if self.url is not None else None,
            "auth_from_environment": self.auth_env is not None,
        }


@dataclass(frozen=True)
class VisionConfig:
    path: Path
    privacy: PrivacyConfig
    models: tuple[VisionModelConfig, ...]

    @property
    def enabled_models(self) -> tuple[VisionModelConfig, ...]:
        return tuple(model for model in self.models if model.enabled)


def _table(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise VisionConfigError(f"{label} must be a TOML table")
    return cast(dict[str, object], value)


def _string(value: object, label: str, *, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise VisionConfigError(f"{label} must be a non-empty string")
    return value.strip()


def _boolean(value: object, label: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise VisionConfigError(f"{label} must be true or false")
    return value


def _integer(
    value: object,
    label: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool):
        raise VisionConfigError(f"{label} must be an integer")
    if not minimum <= value <= maximum:
        raise VisionConfigError(f"{label} must be between {minimum} and {maximum}")
    return value


def _number(
    value: object,
    label: str,
    *,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    if value is None:
        return default
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise VisionConfigError(f"{label} must be a number")
    result = float(value)
    if not minimum <= result <= maximum:
        raise VisionConfigError(f"{label} must be between {minimum} and {maximum}")
    return result


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise VisionConfigError(f"{label} must be a non-empty string array")
    items: list[str] = []
    for item in value:
        text = _string(item, label)
        if not SAFE_NAME.fullmatch(text):
            raise VisionConfigError(f"{label} contains an unsafe name: {text!r}")
        items.append(text)
    return tuple(items)


def _command(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise VisionConfigError(f"{label} must be a non-empty string array")
    command: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item:
            raise VisionConfigError(f"{label} must contain only non-empty strings")
        command.append(item)
    return tuple(command)


def _is_loopback(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _url_origin(url: str) -> str:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"{parsed.scheme}://{host}{port}"


def _parse_privacy(data: dict[str, object]) -> PrivacyConfig:
    mode = _string(data.get("mode"), "privacy.mode", default="local-only")
    if mode not in PRIVACY_MODES:
        raise VisionConfigError(f"privacy.mode must be one of {sorted(PRIVACY_MODES)}")
    return PrivacyConfig(
        mode=mode,
        acknowledge_remote_image_disclosure=_boolean(
            data.get("acknowledge_remote_image_disclosure"),
            "privacy.acknowledge_remote_image_disclosure",
            default=False,
        ),
        sanitize_remote_images=_boolean(
            data.get("sanitize_remote_images"),
            "privacy.sanitize_remote_images",
            default=True,
        ),
        remote_max_edge=_integer(
            data.get("remote_max_edge"),
            "privacy.remote_max_edge",
            default=1280,
            minimum=128,
            maximum=8192,
        ),
        remote_jpeg_quality=_integer(
            data.get("remote_jpeg_quality"),
            "privacy.remote_jpeg_quality",
            default=85,
            minimum=40,
            maximum=95,
        ),
        max_upload_bytes=_integer(
            data.get("max_upload_mib"),
            "privacy.max_upload_mib",
            default=8,
            minimum=1,
            maximum=128,
        )
        * 1024
        * 1024,
        max_response_bytes=_integer(
            data.get("max_response_kib"),
            "privacy.max_response_kib",
            default=256,
            minimum=1,
            maximum=16384,
        )
        * 1024,
    )


def _parse_model(raw: object, index: int, privacy: PrivacyConfig) -> VisionModelConfig:
    data = _table(raw, f"models[{index}]")
    prefix = f"models[{index}]"
    model_id = _string(data.get("id"), f"{prefix}.id")
    if not SAFE_NAME.fullmatch(model_id):
        raise VisionConfigError(f"{prefix}.id contains unsafe characters")
    adapter = _string(data.get("adapter"), f"{prefix}.adapter")
    if adapter not in ADAPTER_TYPES:
        raise VisionConfigError(f"{prefix}.adapter must be one of {sorted(ADAPTER_TYPES)}")
    enabled = _boolean(data.get("enabled"), f"{prefix}.enabled", default=True)
    tasks = _string_list(data.get("tasks"), f"{prefix}.tasks")
    routes = frozenset(route.upper() for route in _string_list(data.get("when"), f"{prefix}.when"))
    unknown_routes = routes - ROUTES
    if unknown_routes:
        raise VisionConfigError(f"{prefix}.when contains unknown routes: {sorted(unknown_routes)}")
    timeout = _number(
        data.get("timeout_seconds"),
        f"{prefix}.timeout_seconds",
        default=30.0,
        minimum=0.1,
        maximum=3600.0,
    )
    trusted = _boolean(data.get("trusted"), f"{prefix}.trusted", default=False)
    command = _command(data.get("command"), f"{prefix}.command") if adapter == "command" else None
    url = _string(data.get("url"), f"{prefix}.url") if adapter == "http-json" else None
    auth_env_value = data.get("auth_env")
    auth_env = _string(auth_env_value, f"{prefix}.auth_env") if auth_env_value is not None else None

    if enabled and adapter == "command" and not trusted:
        raise VisionConfigError(
            f"{prefix} executes local code; set trusted = true only after reviewing it"
        )
    if url is not None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise VisionConfigError(f"{prefix}.url must be an absolute HTTP(S) URL")
        loopback = _is_loopback(url)
        if enabled and privacy.mode == "local-only" and not loopback:
            raise VisionConfigError(f"{prefix} is remote but privacy.mode is local-only")
        if enabled and not loopback and parsed.scheme != "https":
            raise VisionConfigError(f"{prefix}.url must use HTTPS outside loopback")
        if enabled and not loopback and not privacy.acknowledge_remote_image_disclosure:
            raise VisionConfigError(
                "remote image disclosure must be explicitly acknowledged in [privacy]"
            )
    return VisionModelConfig(
        id=model_id,
        adapter=adapter,
        enabled=enabled,
        tasks=tasks,
        when=routes,
        timeout_seconds=timeout,
        trusted=trusted,
        command=command,
        url=url,
        auth_env=auth_env,
    )


def load_vision_config(path: Path) -> VisionConfig:
    try:
        parsed = cast(
            dict[str, object],
            _TOMLLIB.loads(path.read_text(encoding="utf-8")),
        )
    except (OSError, ValueError) as exc:
        raise VisionConfigError(f"cannot read vision config: {exc}") from exc
    root = parsed
    if root.get("schema_version") != 1:
        raise VisionConfigError("vision config schema_version must be 1")
    privacy = _parse_privacy(_table(root.get("privacy", {}), "privacy"))
    raw_models = root.get("models", [])
    if not isinstance(raw_models, list):
        raise VisionConfigError("models must be an array of tables")
    models = tuple(_parse_model(raw, index, privacy) for index, raw in enumerate(raw_models))
    identifiers = [model.id for model in models]
    if len(identifiers) != len(set(identifiers)):
        raise VisionConfigError("model ids must be unique")
    return VisionConfig(path=path.resolve(), privacy=privacy, models=models)


def starter_config() -> str:
    return """# NSFW Guard vision adapters. Disabled until you review and enable one.
schema_version = 1

[privacy]
mode = "local-only" # local-only | remote-tls
acknowledge_remote_image_disclosure = false
sanitize_remote_images = true
remote_max_edge = 1280
remote_jpeg_quality = 85
max_upload_mib = 8
max_response_kib = 256

[[models]]
id = "local-example"
adapter = "command"
enabled = false
trusted = false
command = ["{python}", "-m", "nsfw_guard.mock_vision_adapter"]
tasks = ["describe", "classify"]
when = ["REVIEW", "BLOCK"]
timeout_seconds = 30

# Remote endpoints must implement vision-adapter/v1. Outside loopback they require
# privacy.mode = "remote-tls", HTTPS, and explicit disclosure acknowledgement.
[[models]]
id = "remote-example"
adapter = "http-json"
enabled = false
url = "https://vision.example.invalid/v1/analyze"
auth_env = "VISION_API_TOKEN"
tasks = ["describe"]
when = ["ALL"]
timeout_seconds = 60
"""
