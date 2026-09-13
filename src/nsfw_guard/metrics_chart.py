from __future__ import annotations

import argparse
import html
import json
import os
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Measurement:
    date: str
    provider: str
    total_p50_ms: float
    throughput: float
    peak_rss_mib: float


def load_measurements(history: Path) -> list[Measurement]:
    measurements: list[Measurement] = []
    for path in sorted(history.glob("*.json")):
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        date = str(data.get("measurement_date", path.stem[:10]))
        for record in data.get("nsfw_guard", []):
            measurements.append(
                Measurement(
                    date=date,
                    provider=str(record["provider"]),
                    total_p50_ms=float(record["total_p50_ms"]),
                    throughput=float(record["throughput_images_per_second"]),
                    peak_rss_mib=float(record["peak_process_rss_bytes"]) / (1024 * 1024),
                )
            )
    if not measurements:
        raise ValueError("No NSFW Guard measurements were found.")
    return measurements


def render_svg(measurements: list[Measurement]) -> str:
    width, height = 1200, 760
    margin_left, margin_right = 92, 50
    chart_width = width - margin_left - margin_right
    dates = sorted({item.date for item in measurements})
    providers = sorted({item.provider for item in measurements})
    colors = {"cpu": "#087e8b", "directml": "#db6d28", "cuda": "#2364aa"}
    grouped: dict[str, list[Measurement]] = defaultdict(list)
    for item in measurements:
        grouped[item.provider].append(item)
    panels: list[tuple[str, str, Callable[[Measurement], float], bool]] = [
        ("Throughput", "images/s", lambda item: item.throughput, True),
        ("Warm latency p50", "ms", lambda item: item.total_p50_ms, False),
        ("Peak process RSS", "MiB", lambda item: item.peak_rss_mib, False),
    ]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<title>NSFW Guard measured performance history</title>",
        "<desc>Local CPU, DirectML, and CUDA throughput, latency, and memory over time.</desc>",
        "<defs><linearGradient id="
        + '"bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#f3faf8"/><stop offset="1" stop-color="#fff7e4"/></linearGradient></defs>',
        f'<rect width="{width}" height="{height}" rx="28" fill="url(#bg)"/>',
        '<text x="64" y="62" font-family="Georgia,serif" font-size="34" font-weight="700" fill="#14212b">Measured performance history</text>',
        '<text x="64" y="91" font-family="Consolas,monospace" font-size="13" fill="#667085">LOCAL HOST EVIDENCE / NOT AN SLA / LOWER LATENCY AND RSS ARE BETTER</text>',
    ]
    for provider_index, provider in enumerate(providers):
        x = 710 + provider_index * 145
        color = colors.get(provider, "#667085")
        parts.append(f'<circle cx="{x}" cy="65" r="6" fill="{color}"/>')
        parts.append(
            f'<text x="{x + 12}" y="70" font-family="Consolas,monospace" font-size="14" fill="#344054">{html.escape(provider)}</text>'
        )

    panel_height = 170
    for panel_index, (title, unit, accessor, higher_better) in enumerate(panels):
        top = 125 + panel_index * 198
        bottom = top + panel_height
        values = [accessor(item) for item in measurements]
        maximum = max(values) * 1.15 or 1.0
        parts.append(
            f'<rect x="48" y="{top - 26}" width="1104" height="190" rx="14" fill="#ffffff" stroke="#d0d5dd"/>'
        )
        parts.append(
            f'<text x="64" y="{top}" font-family="Georgia,serif" font-size="20" font-weight="700" fill="#14212b">{html.escape(title)}</text>'
        )
        direction = "higher is better" if higher_better else "lower is better"
        parts.append(
            f'<text x="1132" y="{top}" text-anchor="end" font-family="Consolas,monospace" font-size="11" fill="#667085">{html.escape(unit)} / {direction}</text>'
        )
        plot_top = top + 18
        plot_bottom = bottom - 10
        for grid_index in range(4):
            y = plot_top + (plot_bottom - plot_top) * grid_index / 3
            label = maximum * (1 - grid_index / 3)
            parts.append(
                f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" stroke="#e4e7ec"/>'
            )
            parts.append(
                f'<text x="{margin_left - 10}" y="{y + 4:.1f}" text-anchor="end" font-family="Consolas,monospace" font-size="10" fill="#667085">{label:.1f}</text>'
            )
        for provider in providers:
            points = []
            provider_items = sorted(grouped[provider], key=lambda item: item.date)
            for item in provider_items:
                date_index = dates.index(item.date)
                center = margin_left + chart_width * (date_index + 0.5) / len(dates)
                offset = (providers.index(provider) - (len(providers) - 1) / 2) * 22
                point_x = center + offset
                value = accessor(item)
                point_y = plot_bottom - (value / maximum) * (plot_bottom - plot_top)
                points.append((point_x, point_y, value))
            color = colors.get(provider, "#667085")
            if len(points) > 1:
                coordinates = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in points)
                parts.append(
                    f'<polyline points="{coordinates}" fill="none" stroke="{color}" stroke-width="3"/>'
                )
            for point_x, point_y, value in points:
                parts.append(
                    f'<circle cx="{point_x:.1f}" cy="{point_y:.1f}" r="6" fill="{color}"/>'
                )
                parts.append(
                    f'<text x="{point_x:.1f}" y="{point_y - 10:.1f}" text-anchor="middle" font-family="Consolas,monospace" font-size="10" fill="#344054">{value:.1f}</text>'
                )
        for date_index, date in enumerate(dates):
            date_x = margin_left + chart_width * (date_index + 0.5) / len(dates)
            parts.append(
                f'<text x="{date_x:.1f}" y="{bottom + 8}" text-anchor="middle" font-family="Consolas,monospace" font-size="10" fill="#667085">{html.escape(date)}</text>'
            )
    parts.append(
        '<text x="64" y="730" font-family="Georgia,serif" font-size="13" fill="#667085">Generated locally from versioned JSON evidence. Synthetic speed does not establish moderation accuracy.</text>'
    )
    parts.append("</svg>\n")
    return "".join(parts)


def write_svg_atomic(path: Path, svg: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(svg)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nsfw-guard chart")
    parser.add_argument("--history", type=Path, default=Path("benchmarks"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/assets/performance-history.svg"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        measurements = load_measurements(arguments.history)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"chart: {exc}")
        return 2
    write_svg_atomic(arguments.output, render_svg(measurements))
    print(arguments.output)
    return 0
