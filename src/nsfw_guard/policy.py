from __future__ import annotations

from dataclasses import dataclass

from .contracts import Verdict
from .errors import InvalidInputError


@dataclass(frozen=True, slots=True)
class PolicyConfig:
    name: str
    review_threshold: float
    block_threshold: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.review_threshold < self.block_threshold <= 1.0:
            raise InvalidInputError("Policy thresholds must satisfy 0 <= review < block <= 1.")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "review_threshold": self.review_threshold,
            "block_threshold": self.block_threshold,
        }


POLICY_PROFILES: dict[str, PolicyConfig] = {
    "safety-first-v1": PolicyConfig("safety-first-v1", 0.15, 0.65),
    "balanced-v1": PolicyConfig("balanced-v1", 0.35, 0.80),
    "high-precision-v1": PolicyConfig("high-precision-v1", 0.60, 0.93),
}


def get_policy(name: str) -> PolicyConfig:
    try:
        return POLICY_PROFILES[name]
    except KeyError as exc:
        raise InvalidInputError(
            "Unknown policy profile.", details={"available": sorted(POLICY_PROFILES)}
        ) from exc


def evaluate_score(score: float, policy: PolicyConfig) -> tuple[Verdict, tuple[str, ...]]:
    if not 0.0 <= score <= 1.0:
        raise InvalidInputError("Model score must be between zero and one.")
    if score >= policy.block_threshold:
        return Verdict.BLOCK, ("nsfw_score_at_or_above_block_threshold",)
    if score >= policy.review_threshold:
        return Verdict.REVIEW, ("nsfw_score_in_review_band",)
    return Verdict.ALLOW, ("nsfw_score_below_review_threshold",)
