from __future__ import annotations

import json
from pathlib import Path

from nsfw_guard.folder_scan import (
    BoundedMetric,
    LinkCollection,
    discover_images,
    recommend_workers,
)


def test_discover_images_is_deterministic_and_ignores_reports(tmp_path: Path) -> None:
    (tmp_path / "B.PNG").write_bytes(b"b")
    (tmp_path / "a.jpg").write_bytes(b"a")
    (tmp_path / "notes.txt").write_text("no", encoding="utf-8")
    report = tmp_path / ".nsfw-guard"
    report.mkdir()
    (report / "ignored.png").write_bytes(b"ignored")

    found = discover_images(tmp_path, recursive=True)

    assert [path.name for path in found] == ["a.jpg", "B.PNG"]


def test_worker_plan_is_bounded_by_provider_and_memory() -> None:
    plan = recommend_workers(
        provider="directml",
        requested_workers=None,
        requested_max_in_flight=None,
        memory_budget_mib=1024,
        base_rss_bytes=400 * 1024 * 1024,
        logical_cpu_count=24,
        available_memory_bytes=16 * 1024 * 1024 * 1024,
    )

    assert plan.effective_workers == 4
    assert plan.max_in_flight == 8
    assert plan.warning is None


def test_explicit_worker_override_is_visible_when_over_budget() -> None:
    plan = recommend_workers(
        provider="cpu",
        requested_workers=8,
        requested_max_in_flight=8,
        memory_budget_mib=512,
        base_rss_bytes=200 * 1024 * 1024,
        logical_cpu_count=24,
        available_memory_bytes=16 * 1024 * 1024 * 1024,
    )

    assert plan.effective_workers == 8
    assert plan.warning is not None
    assert plan.to_dict()["budget_is_hard_limit"] is False


def test_metric_sampling_remains_bounded() -> None:
    metric = BoundedMetric(capacity=10, seed=7)
    for value in range(1000):
        metric.add(float(value))

    result = metric.to_dict()
    assert result["count"] == 1000
    assert result["sample_count"] == 10
    assert result["quantiles_exact"] is False
    assert result["min"] == 0.0
    assert result["max"] == 999.0


def test_link_collection_creates_non_destructive_windows_shortcuts(tmp_path: Path) -> None:
    source = tmp_path / "source image.png"
    source.write_bytes(b"unchanged")
    links = LinkCollection(tmp_path / "links")
    record = {"verdict": "BLOCK", "scores": {"nsfw": 0.91}}

    links.add(index=1, source=source, record=record)
    index = links.finalize(run_id="run-1", profile="balanced-v1")

    shortcuts = list((tmp_path / "links" / "BLOCK").glob("*.url"))
    assert len(shortcuts) == 1
    assert source.read_bytes() == b"unchanged"
    assert source.resolve().as_uri() in shortcuts[0].read_text(encoding="utf-8")
    assert "BLOCK" in index.read_text(encoding="utf-8")
    assert json.dumps(record)


def test_host_total_vram_peak_delta_uses_start_sample() -> None:
    from nsfw_guard.folder_scan import _host_total_vram_peak_delta_mib

    start = {"memory_used_mib": 1664}
    peak = {"memory_used_mib": 2580}

    assert _host_total_vram_peak_delta_mib(start, peak) == 916
    assert _host_total_vram_peak_delta_mib(start, {"memory_used_mib": 1200}) == 0
    assert _host_total_vram_peak_delta_mib(None, peak) is None
