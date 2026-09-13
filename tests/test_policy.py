from pathlib import Path

import pytest

from nsfw_guard.cli import build_parser as build_cli_parser
from nsfw_guard.contracts import Verdict
from nsfw_guard.errors import InvalidInputError
from nsfw_guard.folder_scan import FolderScanConfig
from nsfw_guard.folder_scan import build_parser as build_folder_parser
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


def test_new_runs_default_to_neutral_policy_without_changing_legacy_choice() -> None:
    assert FolderScanConfig(root=Path(".")).policy_name == "medium-threshold-v1"
    assert build_folder_parser().parse_args(["."]).policy == "medium-threshold-v1"
    assert build_cli_parser().parse_args(["scan", "image.png"]).policy == "medium-threshold-v1"
    assert build_cli_parser().parse_args(["bridge"]).policy == "medium-threshold-v1"
    assert build_cli_parser().parse_args(["benchmark"]).policy == "medium-threshold-v1"
    assert build_folder_parser().parse_args([".", "--policy", "balanced-v1"]).policy == (
        "balanced-v1"
    )
