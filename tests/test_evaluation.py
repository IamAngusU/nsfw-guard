import json
from pathlib import Path

import pytest

from nsfw_guard.evaluation import evaluate


def _label(digest: str, label: str, *, domain: str = "screenshots", split: str = "test") -> dict:
    return {
        "sha256": digest,
        "label": label,
        "domain": domain,
        "split": split,
        "label_source": "human",
    }


def _result(digest: str, verdict: str, score: float) -> dict:
    return {
        "artifact": {"sha256": digest},
        "ok": True,
        "verdict": verdict,
        "scores": {"nsfw": score},
        "model": {"id": "reference", "artifact_sha256": "f" * 64},
        "policy": {"name": "medium-threshold-v1", "review_threshold": 0.35, "block_threshold": 0.8},
    }


def _write_jsonl(path: Path, records: list[dict]) -> Path:
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def test_evaluate_uses_only_human_labeled_digest_matches(tmp_path: Path) -> None:
    labels = _write_jsonl(
        tmp_path / "labels.jsonl",
        [_label("a" * 64, "safe"), _label("b" * 64, "nsfw"), _label("c" * 64, "safe")],
    )
    results = _write_jsonl(
        tmp_path / "results.jsonl",
        [
            _result("a" * 64, "REVIEW", 0.55),
            _result("b" * 64, "ALLOW", 0.2),
            _result("b" * 64, "ALLOW", 0.2),  # Same bytes must not inflate accuracy.
            _result("d" * 64, "BLOCK", 0.9),  # Unlabeled results have no ground truth.
        ],
    )
    report = evaluate(labels, results)
    assert report["matched_unique_images"] == 2
    assert report["unmatched_labels"] == 1
    assert report["unlabelled_result_records"] == 1
    assert report["duplicate_result_records"] == 1
    assert report["test_has_scored_both_classes"] is True
    test = report["splits"]["test"]
    assert test["safe_attention_rate"] == 1.0
    assert test["nsfw_false_allow_rate"] == 1.0
    assert test["safe_block_rate"] == 0.0
    assert test["domains"]["screenshots"]["safe"]["REVIEW"] == 1


def test_evaluate_rejects_model_derived_labels(tmp_path: Path) -> None:
    label = _label("a" * 64, "safe")
    label["label_source"] = "model"
    labels = _write_jsonl(tmp_path / "labels.jsonl", [label])
    results = _write_jsonl(tmp_path / "results.jsonl", [_result("a" * 64, "ALLOW", 0.1)])
    with pytest.raises(ValueError, match="label_source"):
        evaluate(labels, results)


def test_evaluate_rejects_conflicting_duplicate_predictions(tmp_path: Path) -> None:
    labels = _write_jsonl(tmp_path / "labels.jsonl", [_label("a" * 64, "safe")])
    results = _write_jsonl(
        tmp_path / "results.jsonl",
        [_result("a" * 64, "ALLOW", 0.1), _result("a" * 64, "REVIEW", 0.5)],
    )
    with pytest.raises(ValueError, match="conflicting predictions"):
        evaluate(labels, results)


def test_evaluate_rejects_verdict_score_disagreement(tmp_path: Path) -> None:
    labels = _write_jsonl(tmp_path / "labels.jsonl", [_label("a" * 64, "safe")])
    results = _write_jsonl(tmp_path / "results.jsonl", [_result("a" * 64, "ALLOW", 0.9)])
    with pytest.raises(ValueError, match="verdict disagrees"):
        evaluate(labels, results)


def test_evaluate_reports_missing_class_instead_of_inventing_rate(tmp_path: Path) -> None:
    labels = _write_jsonl(tmp_path / "labels.jsonl", [_label("a" * 64, "safe")])
    results = _write_jsonl(tmp_path / "results.jsonl", [_result("a" * 64, "REVIEW", 0.55)])
    report = evaluate(labels, results)
    assert report["test_has_scored_both_classes"] is False
    assert report["splits"]["test"]["nsfw_false_allow_rate"] is None


def test_evaluate_counts_pre_read_errors_without_assigning_ground_truth(tmp_path: Path) -> None:
    labels = _write_jsonl(tmp_path / "labels.jsonl", [_label("a" * 64, "safe")])
    results = _write_jsonl(
        tmp_path / "results.jsonl",
        [
            {"verdict": "ERROR", "ok": False, "relative_path": "unreadable.png"},
            _result("a" * 64, "ALLOW", 0.1),
        ],
    )
    report = evaluate(labels, results)
    assert report["unlabelled_error_records"] == 1
    assert report["splits"]["test"]["error_count"] == 0


def test_evaluate_rejects_mixed_model_identities(tmp_path: Path) -> None:
    labels = _write_jsonl(
        tmp_path / "labels.jsonl", [_label("a" * 64, "safe"), _label("b" * 64, "safe")]
    )
    different_model = _result("b" * 64, "ALLOW", 0.1)
    different_model["model"]["artifact_sha256"] = "e" * 64
    results = _write_jsonl(
        tmp_path / "results.jsonl", [_result("a" * 64, "ALLOW", 0.1), different_model]
    )
    with pytest.raises(ValueError, match="mix model or policy identities"):
        evaluate(labels, results)


def test_evaluate_rejects_boolean_score(tmp_path: Path) -> None:
    labels = _write_jsonl(tmp_path / "labels.jsonl", [_label("a" * 64, "safe")])
    result = _result("a" * 64, "ALLOW", 0.1)
    result["scores"]["nsfw"] = False
    results = _write_jsonl(tmp_path / "results.jsonl", [result])
    with pytest.raises(ValueError, match="missing NSFW score"):
        evaluate(labels, results)
