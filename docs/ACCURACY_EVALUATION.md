# Accuracy evidence and model changes

The `evaluate` command is available from the current source checkout. It is not
in the pinned `0.1.0a4` one-line trial wheel yet.

NSFW Guard currently ships Marqo's small ONNX classifier as a **triage signal**.
Its published accuracy was measured by its author on a proprietary dataset, not
independently reproduced here. Two user-confirmed harmless diagram screenshots
received `REVIEW` scores of about 0.55 under the 0.35 review threshold. This is
an observed false-positive case, **not** an estimated false-positive rate.
Nothing currently establishes how often the scanner misses actual NSFW images.

The [Freepik four-level detector](https://huggingface.co/Freepik/nsfw_image_detector/blob/main/README.md)
is a plausible comparison candidate, but its reported gains are from its own
evaluation. We will not install it in the one-line try flow or silently replace
the default based on those claims or on two images. No local user image needs to
be uploaded to a model provider for a comparison.

## Local evaluation without reading images again

`nsfw-guard evaluate` joins human labels to an existing folder scan's
`all-results.jsonl` by the image SHA-256. The command reads **only JSONL**, not
the image pixels. Keep both files private: hashes, domains, and result evidence
can still reveal information about a collection.

Each line of a private label manifest is one JSON object:

```json
{"sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","label":"safe","label_source":"human","domain":"screenshots","split":"calibration"}
```

`label` is `safe` or `nsfw`; `domain` is a short non-identifying slug such as
`screenshots`, `photos`, or `drawings`. `split` is `calibration` or `test`.
Do **not** copy the model's `ALLOW`/`REVIEW`/`BLOCK` output into the label field.
Use lawful, independently reviewed material with verified adults for explicit
classes. Deduplicate and separate near-duplicates before assigning splits.
Freeze the test split before choosing models or thresholds.

```powershell
nsfw-guard evaluate --labels private-labels.jsonl --results path\to\all-results.jsonl
```

The report gives SHA-256 digests of both input files, distinct matched-image
counts, unmatched/error coverage, model and policy identity, and rates by split
and domain. `safe_attention_rate` means safe images sent to `REVIEW` or `BLOCK`;
`nsfw_false_allow_rate` means NSFW images sent to `ALLOW`. Errors are counted
separately and excluded from scored-rate denominators. Pre-read errors have no
image digest, so they appear as `unlabelled_error_records` and cannot be
assigned a ground-truth label by this evaluator. Missing classes yield
`null`, never a fabricated zero. Duplicate image hashes cannot inflate counts.

These are **sample rates**, not universal accuracy guarantees. For promotion,
compare candidates on exactly the same legally sourced, representative, frozen
test set; include false-allow, false-block/review burden, subgroup/domain
breakdowns, confidence intervals, calibration, and measured CPU/GPU cost.
Require an explicit safety target before changing a shipped policy. A second
model may be tried in shadow mode first, but disagreement alone is not grounds
to turn `REVIEW` into `ALLOW`.
