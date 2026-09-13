# Building an independent NSFW Guard model

The application, policy layer, bridge, resource controls, evidence format, and
benchmark tooling are NSFW Guard code. The initial classifier weights are an
Apache-2.0 reference model. Calling those weights an independently trained NSFW
Guard model would be misleading.

## Non-negotiable data rules

- Use only datasets with documented redistribution or training rights.
- Include only verified adults in explicit-content classes.
- Do not collect private, leaked, exploitative, or illegal material.
- Keep source, license, consent/age assurance, acquisition date, and content
  hash in a private data ledger.
- Deduplicate before splitting so near-identical images cannot leak between
  train, calibration, and test sets.
- Keep the final test set frozen and inaccessible to training decisions.
- Publish dataset composition and limitations without publishing unsafe media.

## Candidate path

1. Establish a lawful, independently labeled evaluation manifest.
2. Measure the pinned Marqo classifier and isolated NudeNet reference.
3. Train small mobile CNN and tiny vision-transformer candidates from permitted
   initialization, then export deterministic ONNX artifacts.
4. Compare FP32, FP16, and INT8 candidates on CPU, DirectML, and CUDA.
5. Calibrate scores on a separate calibration split.
6. Choose policy thresholds from explicit false-allow and review-load targets.
7. Verify framework-to-ONNX score parity and provider parity.
8. Recheck licenses, sign the model manifest, pin its digest, and publish a
   complete model card.
9. Promote only if the candidate passes every quality and resource gate.

## Minimum promotion gates

A candidate must be evaluated on the same frozen corpus and report:

- Per-class precision, recall, F1, false-positive rate, and false-negative rate.
- PR-AUC and ROC-AUC, with class prevalence disclosed.
- Calibration error and reliability buckets.
- ALLOW, REVIEW, and BLOCK rates for every shipped policy.
- False-allow rate below the agreed safety ceiling.
- No increase in automatic uncertain decisions hidden as ALLOW.
- Static-image p50, p95, throughput, cold load, model bytes, process peak RSS,
  and host-witnessed VRAM where available.
- Breakdown by source domain and documented demographic or cultural slices
  where lawful labels exist.
- Repeated-run confidence intervals, not only the best seed.

Faster alone is not better. The first independent model should beat the current
reference on the chosen safety objective while remaining small enough for local
CPU use. Until those gates are met, the pinned Apache-2.0 model remains clearly
identified as the runtime model.
