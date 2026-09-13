# Architecture

NSFW Guard separates model execution, policy, collection orchestration, evidence, and
integration so each boundary can be tested without turning the product into a hosted
platform.

## Components

| Component | Responsibility |
|---|---|
| backend | provider selection, pinned ONNX session, preprocessing, raw detections |
| policy | deterministic mapping from detections to `ALLOW`, `REVIEW`, or `BLOCK` |
| scanner | per-image byte/pixel limits, decoding, result and error records |
| folder scanner | bounded scheduling, stable order, metrics, atomic run evidence |
| link collection | non-destructive reviewer navigation to original files |
| bridge | line-oriented machine protocol for future products such as Polymorph |
| chart | dependency-free rendering of sanitized benchmark history |
| vision adapters | optional persistent local or HTTPS model enrichment |

## Trust boundaries

The application assumes the local checkout and installed Python dependencies are
trusted. It does not claim to sandbox decoders, ONNX Runtime, GPU drivers, or the
operating system. Byte and pixel quotas reduce accidental resource exhaustion but are
not a substitute for process isolation when inputs are hostile.

The model is a pinned artifact with explicit hash and license evidence. A model output
does not directly mutate, delete, upload, quarantine, or publish a source image.

## Integration boundary

The bridge is deliberately narrow. A caller sends a versioned request and receives a
versioned result with explicit errors and policy evidence. This allows NSFW Guard to
remain independently installable while another product can consume its decisions.

Polymorph is not a runtime dependency. A future hub can launch the bridge as an
external capability, negotiate protocol versions, and preserve NSFW Guard's resource
and privacy boundaries without importing private implementation details.

Vision adapters use a second versioned boundary and produce separate evidence. This
keeps third-party captions and labels from silently changing the pinned safety policy.

See [`BRIDGE_PROTOCOL.md`](BRIDGE_PROTOCOL.md) for the wire contract.

## Persistence boundary

Run files are written to temporary siblings, flushed, synchronized, and atomically
replaced. The latest files are convenience snapshots; run-specific evidence is the
durable audit source. Partial or failed inputs become records rather than disappearing
from aggregate counts.

The optional review links are derived artifacts. They point to originals and can be
recreated from evidence; they are not the source of truth.

## Deliberate non-goals

- no cloud upload service
- no browser UI dependency
- no modification of image metadata
- no automatic deletion or quarantine
- no assertion that advisory memory planning is a hard OS quota
- no assertion that thread concurrency is tensor batching
- no active GitHub Actions workflow
- no E2EE claim for a conventional provider that must decrypt pixels for inference
