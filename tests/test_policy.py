import pytest

from nsfw_guard.contracts import Verdict
from nsfw_guard.errors import InvalidInputError
from nsfw_guard.policy import PolicyConfig, evaluate_score, get_policy


def test_balanced_policy_boundaries_are_explicit() -> None:
    policy = get_policy("balanced-v1")
    assert evaluate_score(0.3499, policy)[0] is Verdict.ALLOW
    assert evaluate_score(0.35, policy)[0] is Verdict.REVIEW
    assert evaluate_score(0.7999, policy)[0] is Verdict.REVIEW
    assert evaluate_score(0.80, policy)[0] is Verdict.BLOCK


def test_invalid_policy_thresholds_are_rejected() -> None:
    with pytest.raises(InvalidInputError):
        PolicyConfig("broken", 0.8, 0.8)


def test_invalid_score_is_rejected() -> None:
    with pytest.raises(InvalidInputError):
        evaluate_score(1.1, get_policy("balanced-v1"))


@pytest.mark.parametrize(
    ("neutral", "legacy"),
    [
        ("low-threshold-v1", "safety-first-v1"),
        ("medium-threshold-v1", "balanced-v1"),
        ("high-threshold-v1", "high-precision-v1"),
    ],
)
def test_neutral_policy_names_preserve_legacy_thresholds(neutral: str, legacy: str) -> None:
    current = get_policy(neutral)
    previous = get_policy(legacy)
    assert (current.review_threshold, current.block_threshold) == (
        previous.review_threshold,
        previous.block_threshold,
    )
    assert current.name == neutral
    assert previous.name == legacy
