# NSFW Guard

Fast, local-first image safety decisions with a stable bridge for other tools.

NSFW Guard reads an image once, applies strict byte and pixel limits, runs a
pinned ONNX classifier locally, and turns its score into one of four explicit
outcomes:

- `ALLOW`: below the configured review threshold.
- `REVIEW`: uncertain or unsupported for automatic handling.
- `BLOCK`: at or above the configured block threshold.
- `ERROR`: no safety claim could be produced.

It does not upload images, silently enable a GPU, or turn a model score into a
claim of certainty.

## Quick start on Windows

```powershell
git clone https://github.com/IamAngusU/nsfw-guard.git
cd nsfw-guard
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[cpu]"
.venv\Scripts\nsfw-guard model install
.venv\Scripts\nsfw-guard scan path\to\image.jpg
```

`Install.cmd` performs the setup locally. The default model is downloaded from
a commit-pinned HTTPS URL and accepted only when its SHA-256 matches the
published contract.

## Why this is not just a boolean

NSFW is contextual. A classifier can be wrong, thresholds depend on the input
population, and an unavailable detector is not evidence that content is safe.
The default `balanced-v1` policy therefore has an explicit review band:

```text
score < 0.35          ALLOW
0.35 <= score < 0.80 REVIEW
score >= 0.80         BLOCK
```

These are operational defaults, not universal accuracy guarantees. Calibrate
them against a lawful, representative dataset before production use.

## Python API

```python
from nsfw_guard import OnnxBackend, Scanner, get_policy

backend = OnnxBackend(provider="cpu")
scanner = Scanner(backend=backend, policy=get_policy("balanced-v1"))
result = scanner.scan_path("image.jpg")
print(result.verdict.value, result.scores)
```

## Integration bridge

The bridge consumes one bounded JSON request per line and writes one JSON
response per line. Logs never share stdout with protocol messages.

```powershell
.venv\Scripts\nsfw-guard bridge --allow-root D:\incoming
```

```json
{"protocol":"safety-bridge/v1","id":"job-42","operation":"scan","artifact":{"kind":"file","path":"D:\\incoming\\image.jpg"},"policy":{"profile":"balanced-v1"}}
```

The process-neutral contract can later connect Polymorph, a web service, a
desktop app, or another language without importing this package. No Polymorph
integration is enabled in this initial release.

See [the bridge contract](docs/BRIDGE_PROTOCOL.md) and
[integration guidance](docs/INTEGRATION.md).

## Measured development-host performance

The reproducible 2026-09-13 baseline used Windows 11, an Intel i9-12900K,
Python 3.11, a GeForce RTX 3080, and one synthetic 1280x720 JPEG. Each NSFW
Guard result contains 40 measured runs after 5 warmups:

| Backend | End-to-end p50 | End-to-end p95 | Throughput | Peak process RSS |
| --- | ---: | ---: | ---: | ---: |
| CPU, auto threads | 27.74 ms | 29.70 ms | 36.04 images/s | 148.6 MiB |
| DirectML | 11.08 ms | 11.33 ms | 90.12 images/s | 371.1 MiB |
| CUDA, 256 MiB arena | 10.96 ms | 12.26 ms | 90.23 images/s | 773.2 MiB |
| NudeNet 3.4.2 CPU, external reference | 14.00 ms | 15.24 ms | 71.38 images/s | 131.7 MiB |

NudeNet performs object detection while NSFW Guard's current model classifies
the whole image, so this row is a runtime reference, not an accuracy ranking.
CPU, CUDA, and DirectML produced the same verdict on the parity fixture; the
largest absolute score difference from CPU was `1.1e-5`.

This is a synthetic local measurement, not an SLA or an accuracy benchmark.
Run `nsfw-guard benchmark` on the deployment host. Machine-readable history is
kept in `benchmarks/`; detailed methodology is in
[the performance notes](docs/PERFORMANCE.md).

## Resource behavior

- CPU is the default even when a GPU exists.
- CUDA and DirectML must be requested explicitly.
- CUDA requires `--cuda-arena-limit-mib`. This limits only the ONNX Runtime
  CUDA arena, not total process or device memory.
- On this host, 64, 128, 256, and 512 MiB CUDA arena settings all used an
  approximate 270-276 MiB host-total VRAM delta. WDDM did not expose reliable
  per-process VRAM, so no per-process value is claimed.
- Compressed input defaults to 25 MiB maximum.
- Decoded images default to 40 million pixels maximum.
- Animated images return `REVIEW` until frame-aware scanning is implemented.
- No source image or persistent content hash is retained by default.

## Model and license choices

The default model is a small Apache-2.0 `vit_tiny_patch16_384` classifier based
on `Marqo/nsfw-image-detection-384`. The ONNX conversion revision and artifact
digest are pinned. The model is not bundled in this repository.

NudeNet v3 is useful as an external comparison, but its repository is
AGPL-3.0. It is deliberately not copied, vendored, or installed as a dependency
of this MIT project. Speed comparisons do not transfer ownership or licensing.
An independently trained NSFW Guard model must first beat candidates on a
lawful, age-safe held-out corpus; see [the own-model plan](docs/OWN_MODEL.md).

## Scope and limitations

This release scans static JPEG, PNG, and WebP images. It is not a detector for
illegal content, age, consent, identity, or intent. It must not be used as the
sole basis for reporting a person, making a legal conclusion, or taking an
irreversible high-impact action. Video, animated frame scanning, text
moderation, and independent real-world accuracy evaluation remain future work.
