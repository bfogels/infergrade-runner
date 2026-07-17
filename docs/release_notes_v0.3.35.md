# InferGrade Runner 0.3.35

Runner 0.3.35 makes the paired command-line path usable as a first-run product
without changing Capability protocol v3.1 or the Runner contract.

## Changed

- `infergrade start` now fails fast when no pairing profile exists and points to
  the Hub pairing flow instead of polling forever.
- The listener prints one connected/waiting status rather than repeating an idle
  message on every poll.
- `doctor`, `cache`, `install-runtime`, `pair`, `unpair`, and `start` now print
  concise human summaries by default. Their complete payloads remain available
  through `--json` for scripts and diagnostics.
- Zero-config `doctor` checks the canonical native runtime on Apple Silicon or
  the container runtime elsewhere, and its help hides internal run-request
  plumbing.
- `pair` uses the machine hostname as its label unless the user supplies one.

## Evidence boundary

The local Runner suite passed all 561 tests from a clean committed tree. Hosted
GitHub Actions jobs for the feature PR failed before executing any steps and
supplied no test logs, so they are not counted as validation.

This release does not change benchmark cases, scoring, calibration, Capability
protocol v3.1, or the `0.3.22` contract. It does not by itself claim published
container images, signed or notarized Desktop artifacts, Hub adoption, or a
clean-machine pairing and benchmark smoke.
