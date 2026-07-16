# InferGrade Runner 0.3.32

Runner 0.3.32 keeps contract `0.3.21` and corrects the recorded wall time on
future result bundles.

## Changed

- `execution.benchmark_job_runtime_seconds` now comes from the recorded
  start-to-completion interval instead of a synthetic 30-second placeholder.
- Invalid, reversed, or timezone-incompatible timestamp pairs fail closed to
  zero rather than inventing a duration.
- Runtime-derived cost fields consume the same recorded interval when a user
  explicitly supplies an hourly rate.

## Claim boundary

This release does not rewrite existing corpus rows, change capability scores,
alter benchmark selection, or modify evidence and publication policy. Existing
results remain auditable from their recorded timestamps; Hub's public aggregate
benchmark-hours metric already uses those timestamps and was not undercounted.
