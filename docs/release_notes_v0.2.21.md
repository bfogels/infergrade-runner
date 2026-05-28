# InferGrade Runner v0.2.21

v0.2.21 closes the Runner side of the paired-runner identity, recovery, and support-export sweep that follows v0.2.20.

## Highlights

- Safer pairing flow: pair codes can be supplied through environment variables or stdin so they do not need to appear in shell history.
- Runner identity hygiene: paired Runner labels, runner kinds, and evidence-source tagging are explicit for Hub-owned local execution.
- Recovery surface: support export redaction, artifact-path copy guidance, runtime repair/remove/install notes, upload retry guidance, and re-pair guidance are documented.
- Support export hardening: raw prompts, raw model outputs, pair codes, tokens, signed URLs, and secret-shaped fields are recursively redacted.
- Runtime-selector planning: v0.3 runtime selector design is documented with platform, accelerator, API, delivery, binary, probe, support-tier, fallback, and claim-boundary fields.

## Validation

- `./scripts/test_all.sh`
- `gitleaks detect --source=. --redact --no-banner --exit-code 1`
- `python3 ./scripts/check_versions.py`

## Release Boundary

This is a source version and preview-channel release snapshot update. It does not claim notarized public macOS artifact publication by itself.
