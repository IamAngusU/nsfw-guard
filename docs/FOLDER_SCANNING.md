# Folder scanning

`nsfw-guard folder` is a bounded, recursive collection pipeline. It is intended to be
safe enough for unattended evidence generation while keeping policy decisions visible
to a human or calling application.

## Supported input

- `.jpg` and `.jpeg`
- `.png`
- `.webp`

Discovery is deterministic and recursive. Any directory component named
`.nsfw-guard`, regardless of case, is excluded so generated evidence cannot feed back
into later runs.

## Pipeline design

The scanner does not materialize all image bytes, decoded tensors, or completed
results. It keeps a bounded number of futures in flight and emits records in stable
discovery order.

```text
paths on disk
    |
deterministic iterator
    |
at most max_in_flight tasks
    |
bounded file read and pixel validation
    |
decode and preprocess on workers
    |
locked DirectML/CUDA session.run
    |
ordered JSONL writer
    |
flush + fsync + atomic replace
```

GPU calls are serialized because concurrent calls against one provider session did not
provide a trustworthy portability contract. Parallel workers still improve collection
throughput by overlapping reads, decoding, preprocessing, lock wait, and result
serialization. The recorded per-file inference stage therefore includes GPU lock wait
when more than one GPU worker is active.

## Automatic worker plan

The planner considers:

- requested provider
- logical CPU count
- available system memory
- advisory memory budget
- an empirically chosen automatic ceiling of four workers

`--workers` overrides the recommendation and records a warning in evidence. The
memory budget is planning input, not an OS-enforced RSS quota. Separate byte and pixel
limits are hard input boundaries.

## Review-link mode

`--links` creates one run-local collection each for `BLOCK`, `REVIEW`, and `ERROR`.
Entries are standard Windows Internet Shortcut files whose URL points to a local
`file:///` URI. Names are sanitized and collision-resistant.

This design was chosen over metadata mutation because embedding a flag into an image:

- changes the original byte stream and hash
- can trigger cloud-sync uploads
- may strip or rewrite unrelated metadata
- has inconsistent JPEG, PNG, and WebP behavior
- makes reclassification and policy versioning harder

The generated `index.html` is local, dependency-free, light-mode, and contains only
run counts and navigation to collections. It does not embed image bytes.

## Output contract

`all-results.jsonl` contains one terminal record per discovered supported image.
`flags.jsonl` contains the subset whose terminal outcome is not `ALLOW`.

`summary.json` contains:

- schema and application version
- run ID and UTC timestamps
- model identity and provider evidence
- source counts and total bytes
- outcome counts
- worker and queue plan
- configured byte, pixel, and memory limits
- throughput and bounded stage distributions
- peak process RSS
- sampled CPU and GPU observations with measurement scope
- contamination checks and headline-eligibility reasons
- output paths and non-destructive behavior statement

`metrics.svg` visualizes the bounded timeline recorded in the summary. GPU utilization
and GPU memory remain labeled host-total on Windows WDDM. With `--links`, the review
folder also contains `00-RUN-METRICS.url` for direct access.

`status.json` is a compact machine-facing status. `latest-summary.json` and
`latest-flags.jsonl` are atomically replaced pointers to the newest completed evidence.

## Exit policy

| Value | Nonzero when |
|---|---|
| `never` | never, after a completed report |
| `error` | one or more `ERROR` outcomes exist |
| `block` | `BLOCK` or `ERROR` exists |
| `review` | `REVIEW`, `BLOCK`, or `ERROR` exists |

The default is `error`. A nonzero exit does not mean evidence was lost; consumers
should read `status.json` and `summary.json` rather than infer write state from the
exit code alone.

## Operational examples

```powershell
# Recommended CPU scan
nsfw-guard folder "D:\incoming" --provider cpu --links

# Evidence outside the source collection
nsfw-guard folder "D:\incoming" --provider directml --output-dir "E:\guard-evidence" --links

# Deliberately low-concurrency shared-host run
nsfw-guard folder "D:\incoming" --provider cpu --workers 1 --memory-budget-mib 384

# CI or ingest gate where REVIEW must remain visible
nsfw-guard folder "D:\incoming" --provider cuda --cuda-arena-limit-mib 64 --fail-on review
```

Use `nsfw-guard folder --help` for the complete current option set.
