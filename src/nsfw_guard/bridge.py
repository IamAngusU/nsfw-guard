from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TextIO

from .contracts import BRIDGE_PROTOCOL
from .errors import (
    BridgeProtocolError,
    GuardError,
    InvalidInputError,
    PathBoundaryError,
)
from .policy import get_policy
from .scanner import Scanner

LOGGER = logging.getLogger("nsfw_guard.bridge")
MAX_REQUEST_LINE_CHARS = 1024 * 1024
MAX_REQUEST_ID_CHARS = 128


class BridgeServer:
    def __init__(self, scanner: Scanner, allowed_roots: list[Path]) -> None:
        if not allowed_roots:
            raise InvalidInputError("At least one allowed bridge root is required.")
        self.scanner = scanner
        self.allowed_roots = tuple(root.resolve(strict=True) for root in allowed_roots)

    def handle(self, payload: object) -> dict[str, Any]:
        request_id: str | None = None
        try:
            request = self._require_object(payload)
            request_id = self._request_id(request)
            if request.get("protocol") != BRIDGE_PROTOCOL:
                raise BridgeProtocolError(
                    "Unsupported bridge protocol.",
                    details={"supported_protocol": BRIDGE_PROTOCOL},
                )
            operation = request.get("operation")
            if operation == "health":
                result: dict[str, object] = {
                    "status": "ready",
                    "capabilities": ["image.scan", "artifact.sha256-binding"],
                    "model": self.scanner.backend.evidence,
                }
            elif operation == "scan":
                result = self._scan(request)
            else:
                raise BridgeProtocolError("Unsupported bridge operation.")
            return {
                "protocol": BRIDGE_PROTOCOL,
                "id": request_id,
                "ok": True,
                "result": result,
            }
        except GuardError as exc:
            return self._error_response(request_id, exc)
        except Exception:
            LOGGER.exception("Unhandled bridge failure")
            return self._error_response(
                request_id,
                BridgeProtocolError("The bridge encountered an internal error."),
            )

    def _scan(self, request: dict[str, Any]) -> dict[str, object]:
        artifact = self._require_object(request.get("artifact"))
        if artifact.get("kind") != "file":
            raise BridgeProtocolError("Only file artifacts are supported in protocol v1.")
        raw_path = artifact.get("path")
        if not isinstance(raw_path, str) or not raw_path or len(raw_path) > 4096:
            raise BridgeProtocolError("artifact.path must be a non-empty bounded string.")
        claimed_sha256 = artifact.get("sha256")
        if claimed_sha256 is not None and not isinstance(claimed_sha256, str):
            raise BridgeProtocolError("artifact.sha256 must be a string when present.")

        policy_request = request.get("policy", {"profile": self.scanner.policy.name})
        policy_object = self._require_object(policy_request)
        profile = policy_object.get("profile", self.scanner.policy.name)
        if not isinstance(profile, str):
            raise BridgeProtocolError("policy.profile must be a string.")
        policy = get_policy(profile)
        candidate = self._resolve_artifact(raw_path)
        return self.scanner.scan_path(
            candidate,
            claimed_sha256=claimed_sha256,
            policy=policy,
        ).to_dict()

    def _resolve_artifact(self, raw_path: str) -> Path:
        supplied = Path(raw_path)
        try:
            candidate = (
                supplied.resolve(strict=True)
                if supplied.is_absolute()
                else (self.allowed_roots[0] / supplied).resolve(strict=True)
            )
        except OSError as exc:
            raise InvalidInputError("The requested artifact does not exist.") from exc
        if not any(
            candidate == root or candidate.is_relative_to(root) for root in self.allowed_roots
        ):
            raise PathBoundaryError("The requested artifact is outside the allowed roots.")
        return candidate

    @staticmethod
    def _require_object(value: object) -> dict[str, Any]:
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise BridgeProtocolError("The bridge request must contain JSON objects.")
        return value

    @staticmethod
    def _request_id(request: dict[str, Any]) -> str:
        value = request.get("id")
        if (
            not isinstance(value, str)
            or not value
            or len(value) > MAX_REQUEST_ID_CHARS
            or any(ord(character) < 32 for character in value)
        ):
            raise BridgeProtocolError("id must be a non-empty bounded printable string.")
        return value

    @staticmethod
    def _error_response(request_id: str | None, error: GuardError) -> dict[str, Any]:
        return {
            "protocol": BRIDGE_PROTOCOL,
            "id": request_id,
            "ok": False,
            "error": error.to_dict(),
        }


def serve_stream(server: BridgeServer, input_stream: TextIO, output_stream: TextIO) -> None:
    while True:
        line = input_stream.readline(MAX_REQUEST_LINE_CHARS + 1)
        if not line:
            return
        if len(line) > MAX_REQUEST_LINE_CHARS:
            while line and not line.endswith("\n"):
                line = input_stream.readline(MAX_REQUEST_LINE_CHARS + 1)
            response = BridgeServer._error_response(
                None,
                BridgeProtocolError("The bridge request exceeds its line limit."),
            )
        elif not line.strip():
            continue
        else:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                response = BridgeServer._error_response(
                    None,
                    BridgeProtocolError("The bridge request is not valid JSON."),
                )
            else:
                response = server.handle(payload)
        output_stream.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
        output_stream.flush()
