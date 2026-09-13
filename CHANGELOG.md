# Changelog

## 0.1.0a2 - 2026-09-13

- Add bounded per-run CPU, GPU, throughput, and RSS timelines with automatic SVG evidence.
- Correct host-total VRAM peak growth to use the start sample as its baseline.

- Added bounded parallel folder scanning with automatic worker planning.
- Added opt-in BLOCK, REVIEW, and ERROR link collections without modifying images.
- Added exact and bounded run metrics with host, provider, RSS, and GPU context.
- Added dependency-free light-mode SVG performance-history rendering.
- Added one-command CPU, DirectML, CUDA, and bundled-CUDA bootstrap paths.
- Serialized shared CUDA and DirectML inference while overlapping CPU preparation.
- Added measurement-quality warnings for busy CPU and GPU environments.
- Increased the verified test suite from 22 to 28 tests.

## 0.1.0a1 - Unreleased

- Added a local ONNX image classifier with CPU-first execution.
- Added commit-pinned, SHA-256-verified model installation.
- Added bounded image decoding and conservative animated-media handling.
- Added configurable policy profiles with an explicit review band.
- Added Python, CLI, benchmark, and NDJSON bridge interfaces.
- Added model, security, integration, and performance documentation.
- Added local validation and unit tests.
