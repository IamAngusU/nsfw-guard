from __future__ import annotations

import json
from pathlib import Path

from nsfw_guard.metrics_chart import load_measurements, render_svg


def test_chart_reads_versioned_measurements_and_renders_svg(tmp_path: Path) -> None:
    history = tmp_path / "history"
    history.mkdir()
    (history / "run.json").write_text(
        json.dumps(
            {
                "measurement_date": "2026-09-13",
                "nsfw_guard": [
                    {
                        "provider": "cpu",
                        "total_p50_ms": 10.0,
                        "throughput_images_per_second": 100.0,
                        "peak_process_rss_bytes": 104857600,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    measurements = load_measurements(history)
    svg = render_svg(measurements)

    assert measurements[0].provider == "cpu"
    assert measurements[0].peak_rss_mib == 100.0
    assert svg.startswith("<svg")
    assert "Measured performance history" in svg
    assert "cpu" in svg
