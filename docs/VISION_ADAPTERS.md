# Vision adapters

NSFW Guard can enrich a completed safety run with optional vision models without
making those models part of its trusted classifier or base installation. Adapters may
describe content, assign domain labels, run OCR, inspect logos, or expose a custom task.

The output is NDJSON because it can be streamed, resumed by external tooling, diffed,
and written atomically without holding a collection in memory. JSON5 would improve
comments in configuration but would weaken interoperability and bounded output.

## Fast start

Create a disabled configuration:

```powershell
nsfw-guard vision init --output vision.toml
```

Review one adapter, set `enabled = true`, and for a command adapter set
`trusted = true`. Then validate process startup and protocol capabilities:

```powershell
nsfw-guard vision doctor --config vision.toml
```

Enrich a completed folder run:

```powershell
nsfw-guard vision enrich "C:\Pictures\.nsfw-guard\latest-summary.json" --config vision.toml
```

The result is a separate `vision/runs/<run-id>/vision-results.jsonl` plus
`summary.json`. Original NSFW evidence and source images are unchanged.

## Privacy modes

| Mode | Core behavior | What it does not guarantee |
|---|---|---|
| `local-only` | NSFW Guard permits trusted command adapters and loopback endpoints only | An arbitrary trusted child process can still implement its own networking |
| `remote-tls` | Non-loopback adapters must use HTTPS and require explicit image-disclosure acknowledgement | The remote model provider receives decryptable pixels; this is not E2EE against that provider |

TLS encryption is normally cheap compared with vision inference. The major compute
choice is local versus remote model execution, model size, image resolution, and task
count, not a fictional E2EE switch.

Remote images are sanitized by default:

- orientation is applied
- the first frame is used
- pixels are converted to RGB
- the longest edge is bounded
- content is re-encoded as JPEG without original metadata
- serialized upload bytes are bounded before a request begins

Set `sanitize_remote_images = false` only when the remote model needs the exact source
encoding or metadata. The evidence then records `metadata_removed = false`.

## Routing

Each model selects one or more base outcomes:

```toml
tasks = ["describe", "classify", "ocr"]
when = ["REVIEW", "BLOCK"]
```

Use `when = ["ALL"]` for every record. Routing happens after the pinned NSFW policy,
so an optional caption model cannot rewrite the base verdict. Adapter failure is
recorded per model and per image rather than silently becoming an `ALLOW`.

## Local command adapter

```toml
[[models]]
id = "my-local-model"
adapter = "command"
enabled = true
trusted = true
command = ["{python}", "adapters/my_model.py"]
tasks = ["describe", "classify"]
when = ["REVIEW", "BLOCK"]
timeout_seconds = 30
```

Relative command paths resolve from the configuration directory. The process is
started once and kept alive for the run, which avoids loading a model for every image.
Only stdout is the protocol channel; diagnostics belong on stderr.

`{python}` expands to the exact interpreter running NSFW Guard, including its virtual
environment. This makes module-based adapters work without shell activation.

Command adapters receive an absolute local path. They are code execution and must be
reviewed like any other local plugin. `trusted = true` is an explicit acknowledgement,
not a sandbox.

## Remote JSON adapter

```toml
[privacy]
mode = "remote-tls"
acknowledge_remote_image_disclosure = true
sanitize_remote_images = true
remote_max_edge = 1280
remote_jpeg_quality = 85
max_upload_mib = 8
max_response_kib = 256

[[models]]
id = "my-remote-model"
adapter = "http-json"
enabled = true
url = "https://vision.example.com/v1/analyze"
auth_env = "VISION_API_TOKEN"
tasks = ["describe"]
when = ["ALL"]
timeout_seconds = 60
```

Secrets come only from environment variables and are never copied into result evidence.
Connections are persistent when the server supports HTTP/1.1 keep-alive. Redirects are
not followed, and requests are not automatically retried because a timed-out write may
already have reached the model endpoint.

## Protocol v1

Transport is one compact JSON object per line for command adapters and one JSON object
per POST for HTTP adapters. Every request contains:

```json
{
  "protocol": "nsfw-guard.vision-adapter",
  "version": 1,
  "type": "analyze",
  "request_id": "unique-id",
  "tasks": ["describe"],
  "input": {"kind": "local-path", "path": "C:\\Pictures\\one.png"},
  "context": {"base_verdict": "REVIEW", "scores": {"nsfw": 0.48}}
}
```

Remote input uses `kind = "inline-image"`, a MIME type, Base64 data, byte length, and
an explicit metadata-removal flag.

A successful response is:

```json
{
  "protocol": "nsfw-guard.vision-adapter",
  "version": 1,
  "type": "result",
  "request_id": "unique-id",
  "ok": true,
  "outputs": {
    "description": "A person standing beside a red vehicle.",
    "labels": [{"name": "vehicle", "score": 0.94}]
  },
  "usage": {"input_tokens": 0, "output_tokens": 0}
}
```

`outputs` is intentionally extensible. The envelope, request ID, size boundary, and
terminal `ok` state remain stable. A `hello` request uses the same envelope and lets an
adapter return supported tasks and model identity before image processing begins.

The repository includes [`examples/mock_vision_adapter.py`](../examples/mock_vision_adapter.py)
as an executable protocol example. It proves persistence and routing but deliberately
does not pretend to be a semantic vision model.

## Efficiency and evidence

- the source NSFW JSONL is read record by record
- each configured model is loaded or connected once
- adapters only run for selected verdict groups
- remote pixels are resized before Base64 encoding
- responses have a strict byte ceiling
- outputs are flushed, synchronized, and atomically replaced
- per-model calls, failures, mean latency, maximum latency, and total runtime are saved
- a one-second bounded timeline captures host CPU/GPU and parent-plus-adapter RSS
- every run renders a light-mode `metrics.svg` beside its JSON evidence

The initial adapter pipeline is intentionally sequential per adapter. This preserves
stable ordering and avoids accidental duplicate remote writes. A future protocol
revision may add declared native batching or independent adapter pools, but it must not
label thread concurrency as model batching.

## E2EE boundary

True end-to-end encryption protects plaintext from every intermediary except the
intended endpoint. A conventional remote vision endpoint is the intended processor and
must see pixels to infer over them, so claiming that the provider cannot see the image
would be false. A future user-controlled confidential-compute adapter can expose
attestation and key negotiation as capabilities, but NSFW Guard will only label that
boundary E2EE when it can verify the complete protocol evidence.
