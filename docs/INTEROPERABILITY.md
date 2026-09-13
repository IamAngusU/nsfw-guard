<!-- SPDX-License-Identifier: MIT -->

# Safety Bridge interoperability contract

The protocol text and JSON examples in this document are licensed under the MIT License in
`LICENSES/MIT.txt`. Implement it without importing NSFW Guard. That is the point.

`nsfw-guard bridge` is a persistent stdin/stdout JSONL service. Each input line is one request and
each output line is exactly one response. Version 1 accepts `health` and `scan` operations.

```json
{"protocol":"safety-bridge/v1","id":"job-1","operation":"scan","artifact":{"kind":"file","path":"C:\\images\\sample.jpg","sha256":"<lower-case SHA-256>"}}
```

```json
{"protocol":"safety-bridge/v1","id":"job-1","ok":true,"result":{"verdict":"ALLOW"}}
```

Consumers must validate `protocol`, correlate `id`, bound line length, avoid shell expansion and
treat `ok: false` as evidence rather than an invitation to retry. A model score is still evidence,
not write authority. Apparently this sentence remains necessary.

Polymorph `0.4.0a11` and newer auto-discover the executable and implement this contract with:

```powershell
polymorph guard --doctor
polymorph guard C:\images\sample.jpg
```
