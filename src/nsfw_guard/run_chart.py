from __future__ import annotations

import html
import os
from dataclasses import dataclass
from pathlib import Path

RunSample = dict[str, float | int | None]


class BoundedTimeline:
    """Keep a representative ordered timeline without unbounded report growth."""

    def __init__(self, capacity: int = 2048) -> None:
        if capacity < 4:
            raise ValueError("timeline capacity must be at least four")
        self._capacity = capacity
        self._samples: list[RunSample] = []
        self._seen = 0
        self._stride = 1

    def add(self, sample: RunSample, *, force: bool = False) -> None:
        completed = sample.get("completed")
        if self._samples and self._samples[-1].get("completed") == completed:
            self._samples[-1] = dict(sample)
            return

        self._seen += 1
        if not force and (self._seen - 1) % self._stride:
            return
        self._samples.append(dict(sample))
        if len(self._samples) > self._capacity:
            self._samples = self._samples[::2]
            self._stride *= 2

    def to_list(self) -> list[RunSample]:
        return [dict(sample) for sample in self._samples]


@dataclass(frozen=True)
class SeriesSpec:
    key: str
    label: str
    color: str


@dataclass(frozen=True)
class PanelSpec:
    title: str
    unit: str
    series: tuple[SeriesSpec, ...]
    fixed_maximum: float | None = None


def _number(sample: RunSample, key: str) -> float | None:
    value = sample.get(key)
    if isinstance(value, int | float):
        return float(value)
    return None


def _atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _points(
    samples: list[RunSample],
    key: str,
    *,
    left: float,
    top: float,
    width: float,
    height: float,
    maximum_x: float,
    maximum_y: float,
) -> str:
    points: list[str] = []
    for sample in samples:
        elapsed = _number(sample, "elapsed_seconds")
        value = _number(sample, key)
        if elapsed is None or value is None:
            continue
        x = left + width * min(1.0, max(0.0, elapsed / maximum_x))
        y = top + height * (1.0 - min(1.0, max(0.0, value / maximum_y)))
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def render_run_metrics_svg(
    samples: list[RunSample],
    output: Path,
    *,
    title: str,
    subtitle: str,
) -> Path:
    panels = (
        PanelSpec(
            "Collection throughput",
            "images/s",
            (SeriesSpec("throughput_images_per_second", "Throughput", "#006d77"),),
        ),
        PanelSpec(
            "Host utilization",
            "percent",
            (
                SeriesSpec("host_cpu_percent", "CPU", "#d97706"),
                SeriesSpec("gpu_utilization_percent", "GPU host-total", "#2563eb"),
            ),
            100.0,
        ),
        PanelSpec(
            "Scanner resident memory",
            "MiB",
            (SeriesSpec("process_rss_mib", "Process RSS", "#b42318"),),
        ),
        PanelSpec(
            "GPU memory witness",
            "MiB",
            (SeriesSpec("gpu_memory_used_mib", "GPU host-total", "#7c3aed"),),
        ),
    )
    maximum_x = max(
        1.0,
        max(
            ((_number(sample, "elapsed_seconds") or 0.0) for sample in samples),
            default=0.0,
        ),
    )
    svg: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="920" viewBox="0 0 1200 920">',
        "<style>",
        ".bg{fill:#f6f1e7}.card{fill:#fffdf8;stroke:#d6cfbf;stroke-width:1}",
        ".title{font:700 34px Georgia,serif;fill:#17252a}",
        ".sub{font:15px Aptos,Candara,sans-serif;fill:#526064}",
        ".panel{font:700 17px Georgia,serif;fill:#223438}",
        ".axis{font:12px Aptos,Candara,sans-serif;fill:#667579}",
        ".legend{font:13px Aptos,Candara,sans-serif;fill:#314247}",
        ".grid{stroke:#ded8ca;stroke-width:1}",
        ".line{fill:none;stroke-width:3;stroke-linejoin:round;stroke-linecap:round}",
        "</style>",
        '<rect class="bg" width="1200" height="920"/>',
        '<rect class="card" x="42" y="34" width="1116" height="850" rx="24"/>',
        f'<text class="title" x="82" y="88">{html.escape(title)}</text>',
        f'<text class="sub" x="82" y="118">{html.escape(subtitle)}</text>',
    ]
    left = 108.0
    width = 1000.0
    panel_height = 122.0
    first_top = 172.0
    panel_gap = 44.0

    for panel_index, panel in enumerate(panels):
        top = first_top + panel_index * (panel_height + panel_gap)
        values = [
            value
            for series in panel.series
            for sample in samples
            if (value := _number(sample, series.key)) is not None
        ]
        maximum_y = panel.fixed_maximum or max(1.0, max(values, default=0.0) * 1.08)
        svg.append(
            f'<text class="panel" x="82" y="{top - 18:.1f}">{html.escape(panel.title)}</text>'
        )
        svg.append(
            f'<text class="axis" x="1108" y="{top - 18:.1f}" text-anchor="end">'
            f"{html.escape(panel.unit)}</text>"
        )
        for tick in range(5):
            y = top + panel_height * tick / 4
            label = maximum_y * (1 - tick / 4)
            svg.append(
                f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{left + width}" y2="{y:.1f}"/>'
            )
            svg.append(
                f'<text class="axis" x="98" y="{y + 4:.1f}" text-anchor="end">{label:.0f}</text>'
            )
        legend_x = left
        rendered = False
        for series in panel.series:
            points = _points(
                samples,
                series.key,
                left=left,
                top=top,
                width=width,
                height=panel_height,
                maximum_x=maximum_x,
                maximum_y=maximum_y,
            )
            if points:
                rendered = True
                svg.append(f'<polyline class="line" stroke="{series.color}" points="{points}"/>')
            svg.append(
                f'<line x1="{legend_x}" y1="{top + panel_height + 22:.1f}" '
                f'x2="{legend_x + 24}" y2="{top + panel_height + 22:.1f}" '
                f'stroke="{series.color}" stroke-width="3"/>'
            )
            svg.append(
                f'<text class="legend" x="{legend_x + 32}" '
                f'y="{top + panel_height + 27:.1f}">{html.escape(series.label)}</text>'
            )
            legend_x += 180
        if not rendered:
            svg.append(
                f'<text class="sub" x="{left + width / 2:.1f}" '
                f'y="{top + panel_height / 2:.1f}" text-anchor="middle">'
                "not exposed by this host</text>"
            )

    for tick in range(5):
        x = left + width * tick / 4
        seconds = maximum_x * tick / 4
        svg.append(
            f'<text class="axis" x="{x:.1f}" y="870" text-anchor="middle">{seconds:.1f}s</text>'
        )
    svg.append('<text class="axis" x="1108" y="870" text-anchor="end">elapsed wall time</text>')
    svg.append("</svg>\n")
    _atomic_text(output, "".join(svg))
    return output


def write_file_shortcut(target: Path, output: Path) -> Path:
    _atomic_text(output, f"[InternetShortcut]\nURL={target.resolve().as_uri()}\n")
    return output
