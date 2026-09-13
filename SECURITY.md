# Security policy

## Security properties in 0.1

- The base classifier and folder scanner process images locally and do not upload them.
  Optional remote vision adapters can transmit image pixels to an external provider
  only after `remote-tls` and explicit image-disclosure acknowledgement are enabled.
  Remote images are sanitized by default; disabling sanitization can transmit the
  original verified encoded bytes, including metadata.
- The default model URL is commit-pinned and the downloaded bytes must match a
  hard-coded SHA-256 digest before loading.
- File inputs are read once with an encoded-byte limit and bound to the digest
  of the bytes that were actually scanned.
- Symbolic-link file inputs are rejected by the scanner.
- Decode dimensions are checked before full pixel processing.
- Unsupported, corrupt, and animated media cannot produce `ALLOW`.
- The bridge accepts files only below explicitly allowed roots.
- Bridge protocol output uses stdout; diagnostics use stderr.
- CPU is always the default provider.

## Important non-properties

- A model prediction is not proof that content is safe or unsafe.
- `local-only` restricts NSFW Guard's HTTP adapter destinations, but a trusted
  command adapter is arbitrary local code and is not sandboxed from networking.
- The bridge root check is not an operating-system sandbox.
- `cuda_arena_limit_mib` maps to ONNX Runtime's `gpu_mem_limit`. It limits the
  CUDA arena, not total process or device VRAM.
- The bridge has no transport authentication. Run it as a child process or
  behind an authenticated local service boundary.
- Result JSON is evidence-bearing but not digitally signed in this release.

## Reporting

Do not attach sensitive images to a public issue. Report a minimal reproducer
that contains no private or illegal content. Use the GitHub security advisory
flow for vulnerabilities once the repository is public.
