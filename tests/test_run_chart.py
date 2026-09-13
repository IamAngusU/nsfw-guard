from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from nsfw_guard.run_chart import BoundedTimeline, render_run_metrics_svg


def test_timeline_decimates_instead_of_growing_without_bound() -> None:
    timeline = BoundedTimeline(capacity=8)
    for completed in range(100):
        timeline.add(
            {
                "completed": completed,
                "elapsed_seconds": float(completed),
                "throughput_images_per_second": 10.0,
            }
        )

    samples = timeline.to_list()
    assert len(samples) <= 8
    assert samples == sorted(samples, key=lambda sample: int(sample["completed"] or 0))


def test_run_metrics_chart_is_valid_light_mode_svg(tmp_path: Path) -> None:
    output = tmp_path / "metrics.svg"
    render_run_metrics_svg(
        [
            {
                "completed": 100,
                "elapsed_seconds": 2.0,
                "throughput_images_per_second": 50.0,
                "host_cpu_percent": 25.0,
                "gpu_utilization_percent": 60.0,
                "process_rss_mib": 400.0,
                "gpu_memory_used_mib": 1000.0,
            }
        ],
        output,
        title="Run test",
        subtitle="GPU is host-total",
    )

    ElementTree.parse(output)
    content = output.read_text(encoding="utf-8")
    assert "#f6f1e7" in content
    assert "Collection throughput" in content
    assert "GPU host-total" in content
