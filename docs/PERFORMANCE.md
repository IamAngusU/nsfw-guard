# Performance and resource measurement

## Current baseline

The 2026-09-13 development-host baseline used Windows 11, an Intel Core
i9-12900K with 24 logical processors, 32 GiB RAM, a GeForce RTX 3080 with
10,240 MiB VRAM, Python 3.11.9, and a synthetic 1280 x 720 JPEG. NSFW Guard
measurements use 40 runs after 5 warmups.

| Runtime | Configuration | Inference p50 | End-to-end p50 | End-to-end p95 | Throughput | Peak RSS |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| ONNX Runtime 1.30 | CPU auto | 18.71 ms | 27.74 ms | 29.70 ms | 36.04/s | 148.6 MiB |
| ONNX Runtime 1.24.4 | DirectML | 4.02 ms | 11.08 ms | 11.33 ms | 90.12/s | 371.1 MiB |
| ONNX Runtime 1.30 | CUDA, 256 MiB arena | 3.95 ms | 10.96 ms | 12.26 ms | 90.23/s | 773.2 MiB |
| NudeNet 3.4.2 | CPU reference | n/a | 14.00 ms | 15.24 ms | 71.38/s | 131.7 MiB |

NudeNet is an isolated AGPL-3.0 object-detection reference with a different
contract. It is not a dependency, and its speed row is not an accuracy claim.

### CPU thread matrix

| Intra-op threads | End-to-end p50 | Throughput | Peak RSS |
| ---: | ---: | ---: | ---: |
| auto (`0`) | 27.74 ms | 36.04/s | 148.6 MiB |
| 1 | 97.48 ms | 10.23/s | 138.8 MiB |
| 2 | 57.49 ms | 17.32/s | 139.3 MiB |
| 4 | 37.56 ms | 26.36/s | 139.7 MiB |
| 8 | 28.33 ms | 35.09/s | 140.5 MiB |

Auto threading was fastest on this host. Explicitly reducing threads can save
a small amount of RSS but substantially reduced sequential throughput.

This baseline is not an accuracy test or SLA. Use the built-in command:

```powershell
nsfw-guard benchmark --runs 30 --warmups 3 --output benchmark.json
```

Install exactly one runtime in each environment:

```powershell
pip install ".[cpu]"
pip install ".[directml]"       # Windows GPU path
pip install ".[cuda]"           # Existing compatible CUDA/cuDNN runtime
pip install ".[cuda-bundled]"   # NVIDIA runtime wheels; over 1 GiB here
```

CUDA additionally requires `--cuda-arena-limit-mib`. Tests at 64, 128, 256,
and 512 MiB produced nearly identical speed. The approximate host-total VRAM
delta was 270-276 MiB for every setting. WDDM did not provide a trustworthy
per-process VRAM value, so the report keeps that measurement unavailable.

## Profiles to compare

- CPU: Pillow preprocessing and ONNX CPU inference.
- GPU: Pillow preprocessing and explicit CUDA or DirectML inference.
- Hybrid: CPU file I/O, decode, and preprocessing plus GPU inference. This is
  the normal GPU path, not a claim that the ONNX graph is split optimally.
- Cache: repeat requests served by digest from bounded process memory.

Compare cold model load, warm p50, p95, throughput, process peak RSS, and
host-witnessed peak VRAM. Do not compare only the fastest single run.

## Accuracy evaluation

Speed cannot choose a moderation model by itself. A meaningful model comparison
requires the same independently licensed, age-safe, labeled corpus and reports
per-class precision, recall, false-positive rate, false-negative rate,
calibration, and subgroup limitations. No such corpus is bundled.

## Reproducibility

Versioned results live in `benchmarks/`. Keep raw local reports in
`.artifacts/`; do not commit sensitive inputs or claim that synthetic speed
tests establish model quality. Future charts should consume the versioned JSON
records rather than scrape rounded README values.
