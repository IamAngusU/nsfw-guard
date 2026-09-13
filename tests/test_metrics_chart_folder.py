from __future__ import annotations

import json
from pathlib import Path

from nsfw_guard.metrics_chart import load_measurements, render_svg


def test_history_chart_loads_best_folder_result_per_provider(tmp_path: Path) -> None:
    payload = {
        "measurement_date": "2026-09-13",
        "benchmark_kind": "folder-pipeline-real-world",
        "measurements": [
            {
                "provider": "cpu",
                "workers": 1,
                "throughput_images_per_second": 10.0,
                "total_p50_ms": 90.0,
                "peak_process_rss_bytes": 100 * 1024 * 1024,
            },
            {
                "provider": "cpu",
                "workers": 4,
                "throughput_images_per_second": 24.89,
                "total_p50_ms": 40.0,
                "peak_process_rss_bytes": 200 * 1024 * 1024,
            },
            {
                "provider": "directml",
                "workers": 4,
                "throughput_images_per_second": 84.07,
                "total_p50_ms": 12.0,
                "peak_process_rss_bytes": 300 * 1024 * 1024,
            },
        ],
    }
    (tmp_path / "2026-09-13-real.json").write_text(json.dumps(payload), encoding="utf-8")

    measurements = load_measurements(tmp_path)

    assert [(item.provider, item.throughput) for item in measurements] == [
        ("cpu", 24.89),
        ("directml", 84.07),
    ]
    svg = render_svg(measurements)
    assert "09-13 real folder" in svg
    assert ">24.9<" in svg
    assert ">84.1<" in svg
