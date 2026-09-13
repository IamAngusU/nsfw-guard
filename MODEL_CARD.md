# Default model card

## Identity

- Runtime model: `marqo-nsfw-image-detection-384-onnx`
- Architecture: `vit_tiny_patch16_384`
- Input: one RGB image resized to 384 x 384
- Output order: index 0 `nsfw`, index 1 `safe`
- Source model: `Marqo/nsfw-image-detection-384`
- Conversion repository: `KanariKanaru/nsfw-image-detection-384-onnx`
- Conversion revision: `8edc47eedf74b30fd379673bc202fe3b754b1538`
- ONNX SHA-256:
  `e9350e576608afe4b57a089ffeb0ebafa1389cdcea4882dd61df28c45f1c24d2`
- License declared by the source and conversion repositories: Apache-2.0

## Intended use

The model is a triage signal for static image moderation. NSFW Guard places an
independent policy layer around the score so uncertain cases can be reviewed.

## Out-of-scope conclusions

The model does not establish legality, age, consent, identity, exploitation,
intent, or policy compliance in every jurisdiction. It must not be the only
evidence for an irreversible high-impact action.

## Published evaluation versus local evidence

The source model card reports 98.56 percent accuracy on its proprietary,
balanced 20,000-image test set. NSFW Guard has not independently reproduced
that accuracy claim because the dataset is not public. The included benchmark
measures runtime only. `nsfw-guard evaluate` can compare folder evidence with
private, human-labeled SHA-256 manifests without opening the images again; no
representative corpus is bundled. Two user-confirmed harmless diagram screenshots
were sent to `REVIEW` around score 0.55. This demonstrates a false-review
burden but does not estimate its population frequency.

## Policy threshold limitations

The neutral `low-threshold-v1`, `medium-threshold-v1`, and `high-threshold-v1`
profiles use fixed review/block score cutoffs of 0.15/0.65, 0.35/0.80, and
0.60/0.93 respectively. Historical names `safety-first-v1`, `balanced-v1`, and
`high-precision-v1` remain compatible aliases with the same cutoffs; their names
do not imply measured safety or precision. None of these profiles has been
calibrated or validated here on a
representative, independently labeled corpus for a particular deployment. Their
names do not establish measured precision, recall, false-positive or
false-negative rates, or score calibration. Before relying on verdicts, choose
thresholds using a separate calibration split and evaluate the resulting
ALLOW, REVIEW, and BLOCK outcomes on held-out data relevant to the use case.

## Known risks

- Domain shift can affect illustrations, medical images, cultural contexts,
  screenshots, crops, adversarial overlays, and transparent assets.
- A binary classifier cannot explain all policy-relevant context.
- Exact resize changes aspect ratio for non-square images.
- Thresholds trade false positives against false negatives.
- Bias cannot be responsibly characterized without representative evaluation.

## NudeNet comparison

NudeNet v3 can be executed as a separate AGPL-3.0 reference during local
research. It is not a dependency or source-code input to this project.
Comparative speed alone cannot establish superior moderation quality.
