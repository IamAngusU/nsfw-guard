# Security policy

## Security properties in 0.1

- User images are processed locally and are never uploaded by NSFW Guard.
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
