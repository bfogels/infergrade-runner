# InferGrade Runner 0.3.31

Runner 0.3.31 advances the contract to `0.3.21` and makes bounded autonomous
benchmark work executable without owner-side manual enqueueing.

## Changed

- Adds `infergrade start --autopilot --execution-mode local_native` for paired
  `agent_dogfood` runners. Hub remains authoritative for the immutable model,
  quant, artifact, task, machine, expiry, job, and download bounds.
- Reuses one idempotency key while retrying transient Hub materialization
  contention, claims only the returned run ID, and stops at the grant or a
  narrower local `--max-jobs` cap.
- Adds independent Runner-owned distribution-readiness policies for Coding and
  Reasoning. Their cohorts no longer need to borrow Assistant calibration
  semantics.

## Claim boundary

Autopilot does not issue pairing codes, widen grants, select arbitrary
artifacts, rent hardware, change result visibility, or grant direct publication
authority. Coding and Reasoning remain task-scoped, not psychometrically
calibrated, and provisional pending their own distribution audits. No raw score,
benchmark weight, or individual score-eligibility rule changed in this release.
