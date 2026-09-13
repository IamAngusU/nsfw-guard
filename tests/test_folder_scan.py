from __future__ import annotations

import html
import json
from collections.abc import Callable
from pathlib import Path

import pytest

import nsfw_guard.folder_scan as folder_scan
from nsfw_guard.errors import InvalidInputError
from nsfw_guard.folder_scan import (
    BoundedMetric,
    FolderScanConfig,
    LinkCollection,
    discover_images,
    recommend_workers,
    scan_folder,
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


def test_discovery_limit_fails_closed_before_creating_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(folder_scan, "MAX_DISCOVERY_FILES", 2)
    for name in ("c.jpg", "b.jpg", "a.jpg"):
        (tmp_path / name).write_bytes(b"image")

    with pytest.raises(InvalidInputError, match="more than 2 supported images"):
        scan_folder(FolderScanConfig(root=tmp_path))

    assert not (tmp_path / ".nsfw-guard").exists()


def test_max_files_selects_deterministic_top_k_and_counts_omissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(folder_scan, "MAX_DISCOVERY_FILES", 2)
    for name in ("z.PNG", "C.webp", "b.jpeg", "a.jpg"):
        (tmp_path / name).write_bytes(b"image")

    discovery = folder_scan._discover_images(tmp_path, recursive=False, max_files=2)

    assert [path.name for path in discovery.paths] == ["a.jpg", "b.jpeg"]
    assert discovery.supported_candidate_count == 4
    assert discover_images(tmp_path, recursive=False, max_files=2) == discovery.paths


def test_max_files_above_path_limit_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(folder_scan, "MAX_DISCOVERY_FILES", 2)

    with pytest.raises(InvalidInputError, match="cannot exceed the discovery path limit"):
        discover_images(tmp_path, recursive=False, max_files=3)


def test_partial_selection_is_explicit_in_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("c.jpg", "a.jpg", "b.jpg"):
        (tmp_path / name).write_bytes(b"image")

    class FakeBackend:
        def __init__(self, **_kwargs: object) -> None:
            self.evidence = {"test": True}

    def fake_scan_function(**_kwargs: object) -> Callable[[int, Path], dict[str, object]]:
        def scan(index: int, path: Path) -> dict[str, object]:
            return {
                "index": index,
                "relative_path": path.name,
                "ok": True,
                "verdict": "ALLOW",
            }

        return scan

    monkeypatch.setattr(folder_scan, "OnnxBackend", FakeBackend)
    monkeypatch.setattr(folder_scan, "_build_scan_function", fake_scan_function)
    monkeypatch.setattr(folder_scan, "_nvidia_snapshot", lambda: None)
    monkeypatch.setattr(
        folder_scan,
        "_host_evidence",
        lambda: {
            "physical_cpu_count": 1,
            "cpu_utilization_at_start_percent": 0.0,
            "gpu_at_start": None,
        },
    )

    outcome = scan_folder(
        FolderScanConfig(
            root=tmp_path,
            max_files=2,
            requested_workers=1,
            progress_every=0,
            create_links=True,
        )
    )

    assert outcome.summary["complete"] is True
    assert outcome.summary["discovery"] == {
        "supported_candidate_count": 3,
        "selected_count": 2,
        "omitted_count": 1,
        "selection_truncated": True,
        "path_limit": folder_scan.MAX_DISCOVERY_FILES,
        "selection_order": "casefolded relative path, then original relative path",
    }
    run_dir = tmp_path / ".nsfw-guard" / "runs" / str(outcome.summary["run_id"])
    status = json.loads((run_dir / "status.json").read_text(encoding="utf-8"))
    assert status["selection_truncated"] is True
    records = [
        json.loads(line) for line in (run_dir / "all-results.jsonl").read_text().splitlines()
    ]
    assert [record["relative_path"] for record in records] == ["a.jpg", "b.jpg"]
    latest_html = tmp_path / ".nsfw-guard" / "OPEN-LATEST-RESULTS.html"
    assert (run_dir / "links" / "BLOCK" / "index.html").exists()
    assert (run_dir / "links" / "REVIEW" / "index.html").exists()
    assert (run_dir / "links" / "ERROR" / "index.html").exists()
    assert (run_dir / "links" / "index.html").resolve().as_uri() in latest_html.read_text(
        encoding="utf-8"
    )
    assert (tmp_path / ".nsfw-guard" / "OPEN-LATEST-RESULTS.url").exists()


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
    source = tmp_path / "source image #&.png"
    source.write_bytes(b"unchanged")
    links = LinkCollection(tmp_path / "links")
    record = {"verdict": "BLOCK", "scores": {"nsfw": 0.91}}

    links.add(index=1, source=source, record=record)
    index = links.finalize(run_id="run-1", profile="balanced-v1")

    shortcuts = list((tmp_path / "links" / "BLOCK").glob("*.url"))
    assert len(shortcuts) == 1
    assert source.read_bytes() == b"unchanged"
    assert source.resolve().as_uri() in shortcuts[0].read_text(encoding="utf-8")
    root_html = index.read_text(encoding="utf-8")
    assert "BLOCK" in root_html
    assert "./BLOCK/index.html" in root_html
    block_html = (tmp_path / "links" / "BLOCK" / "index.html").read_text(encoding="utf-8")
    assert html.escape(source.resolve().as_uri(), quote=True) in block_html
    assert html.escape(source.name) in block_html
    assert source.read_bytes() == b"unchanged"
    assert not list((tmp_path / "links" / "BLOCK").glob("*.part"))
    assert json.dumps(record)


def test_host_total_vram_peak_delta_uses_start_sample() -> None:
    from nsfw_guard.folder_scan import _host_total_vram_peak_delta_mib

    start = {"memory_used_mib": 1664}
    peak = {"memory_used_mib": 2580}

    assert _host_total_vram_peak_delta_mib(start, peak) == 916
    assert _host_total_vram_peak_delta_mib(start, {"memory_used_mib": 1200}) == 0
    assert _host_total_vram_peak_delta_mib(None, peak) is None
