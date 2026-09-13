"""Evaluate existing folder evidence against independent, human-reviewed labels."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

MAX_RECORDS = 100_000
MAX_LINE_BYTES = 1_000_000
MAX_FILE_BYTES = 512 * 1024 * 1024
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
DOMAIN_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
VERDICTS = ("ALLOW", "REVIEW", "BLOCK", "ERROR")


@dataclass(frozen=True, slots=True)
class HumanLabel:
    label: Literal["safe", "nsfw"]
    domain: str
    split: Literal["calibration", "test"]


def _jsonl(path: Path, digest: Any) -> Iterator[dict[str, Any]]:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"{path.name} exceeds the 512 MiB evaluation limit")
    with path.open("rb") as handle:
        for line_number in range(1, MAX_RECORDS + 1):
            line = handle.readline(MAX_LINE_BYTES + 1)
            if not line:
                return
            if len(line) > MAX_LINE_BYTES:
                raise ValueError(f"{path.name}:{line_number}: JSONL line is too long")
            digest.update(line)
            try:
                record = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"{path.name}:{line_number}: invalid JSON") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path.name}:{line_number}: expected a JSON object")
            yield record
        if handle.read(1):
            raise ValueError(f"{path.name} exceeds {MAX_RECORDS} records")


def _sha256(value: Any, where: str) -> str:
    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{where}: expected a SHA-256 hex digest")
    return value.lower()


def _load_labels(path: Path) -> tuple[dict[str, HumanLabel], str]:
    digest = hashlib.sha256()
    labels: dict[str, HumanLabel] = {}
    for index, record in enumerate(_jsonl(path, digest), start=1):
        where = f"{path.name}:{index}"
        sha256 = _sha256(record.get("sha256"), where)
        if sha256 in labels:
            raise ValueError(f"{where}: duplicate image digest")
        if record.get("label_source") != "human":
            raise ValueError(f"{where}: label_source must be 'human', not a model verdict")
        label = record.get("label")
        split = record.get("split")
        domain = record.get("domain")
        if label not in {"safe", "nsfw"}:
            raise ValueError(f"{where}: label must be safe or nsfw")
        if split not in {"calibration", "test"}:
            raise ValueError(f"{where}: split must be calibration or test")
        if not isinstance(domain, str) or not DOMAIN_PATTERN.fullmatch(domain):
            raise ValueError(f"{where}: domain must be a short non-identifying slug")
        labels[sha256] = HumanLabel(label, domain, split)
    if not labels:
        raise ValueError("label manifest is empty")
    return labels, digest.hexdigest()


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _summary(counts: Counter[tuple[str, str]]) -> dict[str, Any]:
    safe = {verdict: counts["safe", verdict] for verdict in VERDICTS}
    nsfw = {verdict: counts["nsfw", verdict] for verdict in VERDICTS}
    safe_total = sum(safe.values())
    nsfw_total = sum(nsfw.values())
    safe_scored = safe_total - safe["ERROR"]
    nsfw_scored = nsfw_total - nsfw["ERROR"]
    return {
        "safe": safe,
        "nsfw": nsfw,
        "safe_count": safe_total,
        "nsfw_count": nsfw_total,
        "safe_scored_count": safe_scored,
        "nsfw_scored_count": nsfw_scored,
        "safe_attention_rate": _rate(safe["REVIEW"] + safe["BLOCK"], safe_scored),
        "safe_block_rate": _rate(safe["BLOCK"], safe_scored),
        "nsfw_false_allow_rate": _rate(nsfw["ALLOW"], nsfw_scored),
        "nsfw_attention_rate": _rate(nsfw["REVIEW"] + nsfw["BLOCK"], nsfw_scored),
        "nsfw_block_rate": _rate(nsfw["BLOCK"], nsfw_scored),
        "error_count": safe["ERROR"] + nsfw["ERROR"],
    }


def evaluate(labels_path: Path, results_path: Path) -> dict[str, Any]:
    labels, labels_sha256 = _load_labels(labels_path)
    results_digest = hashlib.sha256()
    matched: dict[str, tuple[str, float | None, str]] = {}
    groups: dict[tuple[str, str], Counter[tuple[str, str]]] = defaultdict(Counter)
    identity: str | None = None
    model: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    unlabelled = 0
    unlabelled_errors = 0
    duplicate_results = 0
    result_count = 0
    for index, record in enumerate(_jsonl(results_path, results_digest), start=1):
        result_count += 1
        artifact = record.get("artifact")
        if not isinstance(artifact, dict) or artifact.get("sha256") is None:
            unlabelled += 1  # Pre-read ERROR records cannot be bound to a digest.
            if record.get("verdict") == "ERROR":
                unlabelled_errors += 1
            continue
        sha256 = _sha256(artifact["sha256"], f"{results_path.name}:{index}")
        label = labels.get(sha256)
        if label is None:
            unlabelled += 1
            if record.get("verdict") == "ERROR":
                unlabelled_errors += 1
            continue
        verdict = record.get("verdict")
        if verdict not in VERDICTS:
            raise ValueError(f"{results_path.name}:{index}: invalid verdict")
        raw_score = record.get("scores")
        if verdict == "ERROR":
            score = None
        elif (
            not isinstance(raw_score, dict)
            or isinstance(raw_score.get("nsfw"), bool)
            or not isinstance(raw_score.get("nsfw"), (int, float))
        ):
            raise ValueError(f"{results_path.name}:{index}: missing NSFW score")
        else:
            score = float(raw_score["nsfw"])
            if not math.isfinite(score) or not 0 <= score <= 1:
                raise ValueError(f"{results_path.name}:{index}: invalid NSFW score")
        current_model = record.get("model")
        current_policy = record.get("policy")
        if not isinstance(current_model, dict) or not isinstance(current_policy, dict):
            raise ValueError(f"{results_path.name}:{index}: model or policy evidence missing")
        model_id = current_model.get("id")
        if not isinstance(model_id, str) or not model_id:
            raise ValueError(f"{results_path.name}:{index}: model ID missing")
        model_sha256 = _sha256(current_model.get("artifact_sha256"), f"{results_path.name}:{index}")
        review_at = current_policy.get("review_threshold")
        block_at = current_policy.get("block_threshold")
        if (
            not isinstance(current_policy.get("name"), str)
            or isinstance(review_at, bool)
            or isinstance(block_at, bool)
            or not isinstance(review_at, (int, float))
            or not isinstance(block_at, (int, float))
            or not 0 <= review_at < block_at <= 1
        ):
            raise ValueError(f"{results_path.name}:{index}: invalid policy evidence")
        if score is not None:
            expected = "BLOCK" if score >= block_at else "REVIEW" if score >= review_at else "ALLOW"
            if verdict != expected:
                raise ValueError(
                    f"{results_path.name}:{index}: verdict disagrees with score and policy"
                )
        current_identity = json.dumps(
            {
                "model_id": model_id,
                "model_sha256": model_sha256,
                "policy": current_policy,
            },
            sort_keys=True,
        )
        if identity is None:
            identity = current_identity
            model = {"id": model_id, "sha256": model_sha256}
            policy = current_policy
        elif identity != current_identity:
            raise ValueError("matched records mix model or policy identities")
        previous = matched.get(sha256)
        if previous is not None:
            if previous != (verdict, score, current_identity):
                raise ValueError("duplicate image digest has conflicting predictions")
            duplicate_results += 1
            continue
        matched[sha256] = (verdict, score, current_identity)
        groups[label.split, label.domain][label.label, verdict] += 1
    if not matched:
        raise ValueError("no human labels matched the result artifact digests")
    by_split: dict[str, dict[str, Any]] = {}
    for split in ("calibration", "test"):
        split_counts: Counter[tuple[str, str]] = Counter()
        by_domain: dict[str, Any] = {}
        for (group_split, domain), counts in sorted(groups.items()):
            if group_split == split:
                split_counts.update(counts)
                by_domain[domain] = _summary(counts)
        by_split[split] = {**_summary(split_counts), "domains": by_domain}
    test = by_split["test"]
    return {
        "schema_version": 1,
        "labels_sha256": labels_sha256,
        "results_sha256": results_digest.hexdigest(),
        "model": model,
        "policy": policy,
        "label_count": len(labels),
        "matched_unique_images": len(matched),
        "unmatched_labels": len(labels) - len(matched),
        "unlabelled_result_records": unlabelled,
        "unlabelled_error_records": unlabelled_errors,
        "duplicate_result_records": duplicate_results,
        "result_records": result_count,
        "splits": by_split,
        "test_has_scored_both_classes": test["safe_scored_count"] > 0
        and test["nsfw_scored_count"] > 0,
        "limitations": [
            "Human label provenance and representativeness are asserted, not verified.",
            "Rates cover only matched labeled images, not the entire population.",
            "Pre-read errors lack an image digest and cannot be joined to labels.",
            "Do not select thresholds on the frozen test split.",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="nsfw-guard evaluate",
        description="Compare folder evidence with human labels; no images are read.",
    )
    parser.add_argument("--labels", required=True, type=Path)
    parser.add_argument("--results", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        report = evaluate(arguments.labels, arguments.results)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0
