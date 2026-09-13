from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from nsfw_guard.vision_adapters import _remote_image
from nsfw_guard.vision_config import (
    PrivacyConfig,
    VisionConfigError,
    load_vision_config,
    starter_config,
)
from nsfw_guard.vision_pipeline import (
    doctor,
    enrich_vision_results,
    resolve_vision_input,
)


def test_starter_config_is_safe_and_disabled(tmp_path: Path) -> None:
    config_path = tmp_path / "vision.toml"
    config_path.write_text(starter_config(), encoding="utf-8")

    config = load_vision_config(config_path)

    assert config.privacy.mode == "local-only"
    assert config.privacy.acknowledge_remote_image_disclosure is False
    assert config.enabled_models == ()


def test_remote_adapter_requires_tls_and_disclosure_acknowledgement(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "vision.toml"
    config_path.write_text(
        """schema_version = 1
[privacy]
mode = "remote-tls"
acknowledge_remote_image_disclosure = false
[[models]]
id = "remote"
adapter = "http-json"
url = "https://example.invalid/analyze"
tasks = ["describe"]
when = ["ALL"]
""",
        encoding="utf-8",
    )

    with pytest.raises(VisionConfigError, match="explicitly acknowledged"):
        load_vision_config(config_path)

    config_path.write_text(
        config_path.read_text(encoding="utf-8")
        .replace("https://example.invalid", "http://example.invalid")
        .replace(
            "acknowledge_remote_image_disclosure = false",
            "acknowledge_remote_image_disclosure = true",
        ),
        encoding="utf-8",
    )
    with pytest.raises(VisionConfigError, match="must use HTTPS"):
        load_vision_config(config_path)


def test_remote_sanitization_is_explicit_and_bounded(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    image = Image.new("RGB", (200, 100), (20, 30, 40))
    image.save(source, format="PNG", pnginfo=None)
    privacy = PrivacyConfig(
        mode="remote-tls",
        acknowledge_remote_image_disclosure=True,
        sanitize_remote_images=True,
        remote_max_edge=64,
        remote_jpeg_quality=80,
        max_upload_bytes=1024 * 1024,
        max_response_bytes=1024,
    )

    content, mime_type, metadata_removed = _remote_image(source, privacy)

    assert mime_type == "image/jpeg"
    assert metadata_removed is True
    with Image.open(io.BytesIO(content)) as sanitized:
        assert max(sanitized.size) == 64
        assert not sanitized.getexif()


def test_command_adapter_is_persistent_and_pipeline_routes_records(
    tmp_path: Path,
) -> None:
    root = tmp_path / "images"
    root.mkdir()
    for name, color in (("allow.png", "green"), ("block-a.png", "red"), ("block-b.png", "blue")):
        Image.new("RGB", (24, 16), color).save(root / name)
    input_path = tmp_path / "all-results.jsonl"
    records = [
        {"index": 1, "relative_path": "allow.png", "verdict": "ALLOW", "scores": {}},
        {"index": 2, "relative_path": "block-a.png", "verdict": "BLOCK", "scores": {}},
        {"index": 3, "relative_path": "block-b.png", "verdict": "BLOCK", "scores": {}},
    ]
    input_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "run_id": "source-run",
                "root": str(root),
                "reports": {"all_results": str(input_path)},
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "vision.toml"
    config_path.write_text(
        "\n".join(
            (
                "schema_version = 1",
                "[privacy]",
                'mode = "local-only"',
                "[[models]]",
                'id = "mock"',
                'adapter = "command"',
                "enabled = true",
                "trusted = true",
                'command = ["{python}", "-m", "nsfw_guard.mock_vision_adapter"]',
                'tasks = ["describe", "classify"]',
                'when = ["BLOCK"]',
                "timeout_seconds = 5",
                "",
            )
        ),
        encoding="utf-8",
    )
    config = load_vision_config(config_path)
    health = doctor(config)
    assert health["ok"] is True

    source = resolve_vision_input(summary_path, None)
    outcome = enrich_vision_results(source, config, tmp_path / "vision", progress_every=0)

    lines = [
        json.loads(line) for line in outcome.results_path.read_text(encoding="utf-8").splitlines()
    ]
    assert outcome.records == 3
    assert outcome.calls == 2
    assert outcome.errors == 0
    summary = json.loads(outcome.summary_path.read_text(encoding="utf-8"))
    assert Path(summary["metrics_chart"]).exists()
    assert summary["resources"]["peak_process_tree_rss_bytes"] > 0
    assert len(summary["resources"]["timeline"]) >= 2
    assert lines[0]["analyses"] == []
    process_ids = {line["analyses"][0]["usage"]["process_id"] for line in lines[1:]}
    assert len(process_ids) == 1
    assert lines[1]["analyses"][0]["outputs"]["labels"][0]["name"] == "mock"
