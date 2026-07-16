# InferGrade Runner 0.3.30

Runner 0.3.30 keeps contract `0.3.20` and completes the Hub-facing diagnostic
path for the strict MMLU-Pro scoring correction introduced in Runner 0.3.29.

## Changed

- Carries the MMLU-Pro malformed-output count in the compact capability
  component report consumed by Hub.
- Omits the field from unrelated benchmark components instead of expanding
  compact payloads with null diagnostics.

## Claim boundary

This release does not change the 0.3.29 scoring semantics. It makes the format-
miss diagnostic visible to downstream evidence surfaces so a scored incorrect
answer is not confused with a generation or runtime failure.
