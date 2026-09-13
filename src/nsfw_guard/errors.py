from __future__ import annotations

from typing import Any


class GuardError(Exception):
    code = "guard_error"
    retryable = False

    def __init__(self, message: str, *, details: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": self.details,
        }


class InvalidInputError(GuardError):
    code = "invalid_input"


class ArtifactTooLargeError(GuardError):
    code = "artifact_too_large"


class UnsupportedMediaError(GuardError):
    code = "unsupported_media"


class DigestMismatchError(GuardError):
    code = "artifact_digest_mismatch"


class SourceChangedError(GuardError):
    code = "source_changed_during_read"


class ModelUnavailableError(GuardError):
    code = "model_unavailable"
    retryable = True


class ModelIntegrityError(GuardError):
    code = "model_integrity_error"


class ProviderUnavailableError(GuardError):
    code = "execution_provider_unavailable"


class InferenceError(GuardError):
    code = "inference_failed"
    retryable = True


class BridgeProtocolError(GuardError):
    code = "bridge_protocol_error"


class PathBoundaryError(GuardError):
    code = "path_outside_allowed_roots"
