# InferGrade Runner 0.3.34

Runner 0.3.34 makes interrupted capability runs recoverable without changing
Capability protocol v3.1 or the Runner contract.

## Changed

- A paired run interrupted by the runner process is reported to the Hub as a
  retryable failure instead of remaining stranded in a running state.
- Every completed capability case is written to a fingerprinted, append-only
  checkpoint before progress is reported.
- An exact `--resume` reuses completed cases and reruns failed or incomplete
  cases. A torn final append is discarded safely; request, protocol, benchmark,
  case-set, or record-integrity mismatches fail closed.
- Capability checkpoints remain available through later bundle stages and are
  removed only after the entire bundle completes.

## Evidence boundary

The local runner-core suite passed all 551 tests from a clean committed tree.
Hosted GitHub Actions jobs for the feature PRs failed before executing any
steps and supplied no test logs, so they are not counted as validation.

This release does not change benchmark cases, weights, scoring, calibration,
the `0.3.22` contract, or model eligibility. It does not by itself claim
published container images, signed or notarized Desktop artifacts, Hub
adoption, or a successfully resumed production canary.
