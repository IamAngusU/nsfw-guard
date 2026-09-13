# Integration guide

## Child-process bridge

The recommended first integration launches one long-lived `nsfw-guard bridge`
process. Keeping the process warm avoids repeated model loading.

Configure the smallest possible `--allow-root`. Generate a unique request ID
and, when the caller already knows the source digest, include `artifact.sha256`.
Read exactly one response for each request.

The caller must apply these rules:

- Unknown protocol or result schemas are errors.
- Timeout, process exit, invalid JSON, and `ok: false` are not safe outcomes.
- `REVIEW` remains review; it must not be silently converted to `ALLOW`.
- Store model, policy, artifact digest, and timing evidence together if audit
  history is required.
- Do not persist source paths unless the surrounding product explicitly needs
  them.

## Polymorph integration

Polymorph `0.4.0a11` and newer can auto-discover the bridge and use the
`safety-bridge/v1` contract without an adapter package. See
[`INTEROPERABILITY.md`](INTEROPERABILITY.md) for the current commands and wire
contract. When correlating evidence across the two products, use the exact
source SHA-256 as the join key. Polymorph remains a separate product; this
repository does not control its admission behavior.

## Future hub

A general hub should route typed capabilities rather than know model details.
For example, `image.scan` can be provided by NSFW Guard while another process
provides metadata sanitation. The hub should supervise processes, enforce
timeouts and quotas, validate schemas, and preserve partial outcomes.

The hub must not invent stronger semantics than a provider returns.
