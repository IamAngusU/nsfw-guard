# Safety Bridge Protocol v1

Protocol identifier: `safety-bridge/v1`

The bridge is newline-delimited JSON over stdin and stdout. Each request gets
exactly one response. A process can therefore be supervised by any language
without coupling the caller to Python or ONNX Runtime.

## Request envelope

```json
{
  "protocol": "safety-bridge/v1",
  "id": "caller-generated-id",
  "operation": "scan",
  "artifact": {
    "kind": "file",
    "path": "D:\\incoming\\image.jpg",
    "sha256": "optional-lowercase-or-uppercase-sha256"
  },
  "policy": {
    "profile": "medium-threshold-v1"
  }
}
```

The request ID is bounded to 128 printable characters. A request line is
bounded to 1,048,576 characters. Protocol v1 accepts only file artifacts.
Paths may be absolute or relative to the first configured allowed root.

## Success response

```json
{
  "protocol": "safety-bridge/v1",
  "id": "caller-generated-id",
  "ok": true,
  "result": {
    "schema_version": 1,
    "verdict": "ALLOW",
    "reason_codes": ["nsfw_score_below_review_threshold"],
    "scores": {"nsfw": 0.02, "safe": 0.98},
    "artifact": {},
    "model": {},
    "policy": {},
    "timing": {}
  }
}
```

The result intentionally does not echo the local file path.

## Error response

```json
{
  "protocol": "safety-bridge/v1",
  "id": "caller-generated-id-or-null",
  "ok": false,
  "error": {
    "code": "artifact_digest_mismatch",
    "message": "The image bytes do not match the claimed SHA-256.",
    "retryable": false,
    "details": {}
  }
}
```

Callers must treat `ok: false` as no safety decision. They must never map a
bridge failure, timeout, malformed response, or unknown schema to `ALLOW`.

## Health operation

```json
{"protocol":"safety-bridge/v1","id":"health-1","operation":"health"}
```

Health returns capabilities and the loaded model identity. It is not a promise
that every future input is valid or classifiable.

## Compatibility rules

- Unknown protocol identifiers fail closed.
- New fields may be added within version 1 and must be ignored by tolerant
  consumers.
- Existing field meaning cannot change within version 1.
- Breaking changes require a new protocol identifier.
