# Metrics and evidence

NSFW Guard treats performance claims as versioned evidence, not README decoration.
Benchmark JSON files live in `benchmarks/`; the SVG history is generated from those
records without a plotting dependency.

```powershell
nsfw-guard chart --history benchmarks --output docs/assets/performance-history.svg
```

## What is measured

Every folder run records, where the host exposes the signal:

- UTC start and finish
- application, model, model hash, provider, and policy identity
- OS, architecture, Python, logical CPUs, total and available RAM
- GPU name, driver-visible utilization, and memory scope
- files, bytes, elapsed time, and images per second
- bounded distributions for read, decode, preprocess, inference, and total latency
- process peak RSS
- a bounded per-run timeline and automatically rendered light-mode `metrics.svg`
- worker count, maximum in-flight tasks, and advisory memory plan
- result counts and sanitized errors
- measurement-quality reasons and headline eligibility

Stage distributions use a bounded reservoir rather than retaining one sample per file.
Count, minimum, maximum, and mean remain exact; quantiles are exact only while all
samples fit in the reservoir and become sampled estimates for larger runs.

## Reference folder matrix

Date: 2026-09-13<br>
Host: Windows, Intel Core i9-12900K, NVIDIA GeForce RTX 3080<br>
Input: 200 deterministically selected PNG screenshots<br>
Cache state: warm<br>
Model batch: 1

| Provider | Workers | Images/s | p50 total | p95 total | Peak RSS | Start load |
|---|---:|---:|---:|---:|---:|---|
| CPU | 1 | 15.4728 | 60.3978 ms | 95.8602 ms | 366.9 MiB | comparison |
| CPU | 4 | 29.7227 | 127.6014 ms | 186.5602 ms | 453.5 MiB | CPU 10.6% |
| DirectML | 1 | 34.6506 | 24.9821 ms | not recorded | 575.4 MiB | GPU 32% |
| DirectML | 4 | 82.3740 | 39.9482 ms | 91.3277 ms | 609.7 MiB | GPU 32% |
| CUDA | 1 | 35.9795 | 23.8444 ms | not recorded | 994.2 MiB | GPU 11% |
| CUDA | 4 | 79.6828 | 38.5960 ms | 74.3083 ms | 928.9 MiB | GPU 7% |

Measured throughput gains from one to four workers:

- CPU: `1.92095x`
- DirectML: `2.37727x`, excluded from headline use because starting GPU load was 32%
- CUDA: `2.21467x`

Four workers increase folder throughput while increasing the latency seen by an
individual file. Choose one worker for latency-sensitive, one-at-a-time calls; keep
the automatic plan for collection throughput.

The aggregate public record is
[`benchmarks/2026-09-13-folder-pipeline-windows-i9-12900k-rtx3080.json`](../benchmarks/2026-09-13-folder-pipeline-windows-i9-12900k-rtx3080.json).
It contains no source paths, image names, or classifications.

## Single-image warm benchmark

The original package benchmark measured:

| Provider | Warm p50 | Derived throughput | Peak RSS |
|---|---:|---:|---:|
| CPU | 27.74 ms | 36.04 images/s | 148.6 MiB |
| DirectML | 11.08 ms | 90.12 images/s | 371.1 MiB |
| CUDA | 10.96 ms | 90.23 images/s | 773.2 MiB |

Single-image reciprocal throughput is not a folder-throughput claim. Folder numbers
include discovery, reads, decode, scheduling, evidence, and contention.

## Measurement quality

A run is not headline eligible when known starting contamination crosses the current
guardrail:

- CPU utilization above 25%
- host-total GPU utilization above 20% for a GPU provider

This does not invalidate a functional run. It prevents a noisy number from being
presented as clean comparative evidence. Windows WDDM can make per-process VRAM
unavailable; in that case NSFW Guard labels GPU values as host-total rather than
pretending they belong only to this process.

## Long-term history

Commit one sanitized benchmark JSON per meaningful release or hardware profile.
Never commit private paths, file labels, image hashes, or classifications. Re-render
the SVG after adding records. Over time this provides a versioned view of throughput,
latency, and RSS rather than overwriting the latest favorable number.

For fair comparisons:

- use the same corpus manifest and cache state
- record background CPU and GPU load
- record provider/runtime and driver changes
- keep model and policy identity fixed unless the comparison is about that change
- report failures and excluded runs
- distinguish direct model latency from end-to-end folder throughput

The graph is descriptive evidence, not an automatic release gate.
