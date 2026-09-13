from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

BRIDGE_PROTOCOL = "safety-bridge/v1"
RESULT_SCHEMA_VERSION = 1


class Verdict(str, Enum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class ArtifactEvidence:
    sha256: str
    byte_length: int
    width: int
    height: int
    media_format: str
    animated: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "sha256": self.sha256,
            "byte_length": self.byte_length,
            "width": self.width,
            "height": self.height,
            "media_format": self.media_format,
            "animated": self.animated,
        }


@dataclass(frozen=True, slots=True)
class TimingEvidence:
    read_ms: float
    decode_ms: float
    preprocess_ms: float
    inference_ms: float
    total_ms: float
    cache_hit: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "read_ms": round(self.read_ms, 4),
            "decode_ms": round(self.decode_ms, 4),
            "preprocess_ms": round(self.preprocess_ms, 4),
            "inference_ms": round(self.inference_ms, 4),
            "total_ms": round(self.total_ms, 4),
            "cache_hit": self.cache_hit,
        }


@dataclass(frozen=True, slots=True)
class ScanResult:
    verdict: Verdict
    reason_codes: tuple[str, ...]
    artifact: ArtifactEvidence
    model: dict[str, object]
    policy: dict[str, object]
    timing: TimingEvidence
    scores: dict[str, float] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "verdict": self.verdict.value,
            "reason_codes": list(self.reason_codes),
            "scores": self.scores,
            "artifact": self.artifact.to_dict(),
            "model": self.model,
            "policy": self.policy,
            "timing": self.timing.to_dict(),
        }
