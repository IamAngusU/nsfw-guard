# Changelog

## Unreleased

## 0.1.0a4 - 2026-09-13

- Correct the combined GitHub wheel example to request the CPU runtime extra explicitly.
- Bind vision enrichment to the base artifact digest and give each adapter its own
  verified temporary image copy.
- Bound folder discovery, report explicit partial selections, and add portable HTML
  review links alongside Windows shortcuts.
- Derive unsanitized vision MIME types and temporary suffixes from image bytes rather
  than filenames; clarify the opt-in remote-upload privacy boundary.
- Add neutral threshold-profile aliases while retaining historical profile names.
- Use `medium-threshold-v1` for new CLI and folder runs by default; keep legacy
  names and their decision boundaries unchanged.
- Add a manual release-evidence manifest and checklist; GitHub Actions remain disabled.

## 0.1.0a3 - 2026-09-13

- Add versioned persistent command and HTTP vision adapters.
- Add explicit local-only and remote-TLS privacy modes with disclosure acknowledgement.
- Sanitize and bound remote image payloads and bound all adapter responses.
- Add streaming outcome routing and atomic vision JSONL evidence.
- Record adapter process-tree RSS and bounded CPU/GPU timelines with an automatic SVG.
- Add `vision init`, `vision doctor`, `vision enrich`, an example adapter, and user docs.
- Auto-tune CPU folder inference threads to avoid nested ONNX worker oversubscription.
- Publish the permissive `safety-bridge/v1` contract and zero-glue Polymorph integration.
- License releases from a3 under AGPL-3.0-only while preserving the published a1 MIT grant.

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

## 0.1.0a1 - 2026-09-13

- Added a local ONNX image classifier with CPU-first execution.
- Added commit-pinned, SHA-256-verified model installation.
- Added bounded image decoding and conservative animated-media handling.
- Added configurable policy profiles with an explicit review band.
- Added Python, CLI, benchmark, and NDJSON bridge interfaces.
- Added model, security, integration, and performance documentation.
- Added local validation and unit tests.
