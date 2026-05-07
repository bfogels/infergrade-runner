# Codex v0.2.5 Sprint Planning

Date: 2026-05-07

## Branch State

- Runner `origin/main`: v0.2.4 at `a8528ca`.
- Runner `origin/develop`: one reviewed public-release hardening PR ahead of `origin/main` at `b5078d6`.
- Runner open PRs at sprint start: none.
- Hub open PRs at sprint start: none observed from the Hub checkout.

## Release Goal

v0.2.5 should make the public macOS Desktop release process safer and easier to verify without claiming that public distribution is complete when signing or notarization credentials are unavailable.

Target maintainer promise:

> A maintainer can tell whether a Desktop release artifact set is internally consistent, what signing/notarization gates remain, and what evidence is safe to publish.

## Planned PR Sequence

1. PR A: desktop artifact verification ergonomics.
   - Add a post-download artifact verifier for `SHA256SUMS`, updater archives, updater signatures, and updater manifest consistency.
   - Document that this verifier does not replace Developer ID signing, notarization, Gatekeeper, stapled-ticket checks, or clean-machine launch smoke.
   - Add release CI unit coverage for positive and negative verifier paths.

2. PR B: release checklist automation and docs hardening.
   - Add a consolidated local release evidence command.
   - Tighten public release checklist wording around unavailable credentials and GitHub Actions infra/pre-run failures.

3. PR C: v0.2.5 release promotion if PR A/B produce a coherent public-release hardening slice.
   - Bump version only after reviewed feature PRs land in `develop`.

## Reviewer Checklist

- No signing, notarization, Gatekeeper, Windows/Linux, CUDA/ROCm, or public-distribution claims are added without corresponding gates.
- Local artifact manifest verification is clearly separated from macOS signing/notarization verification.
- Scripts reject malformed checksum manifests, missing artifacts, missing updater signatures, and insecure updater URLs.
- No secrets, certificates, keys, or notarization materials are introduced.
- GitHub Actions failure notes distinguish repo infrastructure/pre-run failures from diff failures.

## Validation Plan

Use the relevant subset per PR:

```bash
python3 -m unittest python/runner-core/tests/test_release_ci.py
python3 ./scripts/check_public_release_readiness.py
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```

For release promotion, run the full v0.2.4 release validation set plus any new release-hardening script smoke.

## Evidence Honesty Notes

- v0.2.5 is public-release hardening, not a new benchmark/capability release.
- A checksum/updater manifest verifier proves artifact-set consistency, not public macOS trust.
- Public macOS distribution still requires Developer ID signing, notarization, Gatekeeper assessment, stapled-ticket checks, and clean-machine smoke.
- Windows and Linux package smoke artifacts remain maintainer-inspection artifacts, not supported public installers.

## Release Criteria

v0.2.5 can promote when maintainers have clearer artifact verification and release-checklist evidence without expanding the product's public distribution claims.

## Current Blockers

- Apple Developer ID signing and notarization credentials are not available in the local workspace.
- GitHub Actions for recent Runner PRs have failed before executing workflow steps with `steps: []` and `log not found`; release evidence must distinguish this infrastructure shape from local validation.

## PR A Local Evidence

Branch: `codex/runner-v025-release-hardening`
PR: pending

Implemented:

- `scripts/verify_desktop_release_artifacts.py` verifies downloaded Desktop release artifact sets against `SHA256SUMS`.
- The verifier confirms updater manifest version/platform shape, HTTPS artifact URLs, local updater archives, and non-empty sibling signature artifacts.
- Reviewer P1 fixes require the updater manifest signature to match the sibling `.sig` file and require the updater archive, `.sig`, and updater manifest itself to be covered by `SHA256SUMS`.
- The verifier can require a DMG and updater set, and prints stable evidence lines including `desktop_release_notarization=not_checked_by_artifact_manifest`.
- Release docs now explain when to use the verifier and explicitly state that it does not replace Developer ID signing, notarization, Gatekeeper, stapled-ticket checks, or clean-machine launch smoke.

Validation passed locally:

```bash
python3 -m unittest python/runner-core/tests/test_release_ci.py
python3 scripts/verify_desktop_release_artifacts.py --help
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```

PR: #161, merged to `develop` as `b5078d6`.

## PR B Local Evidence

Branch: `codex/runner-v025-release-checks`
PR: pending

Implemented:

- `scripts/check_public_release_readiness.py` emits a repository-local public-release readiness report.
- The readiness report checks clean Git state, required policy/docs/scripts, protected Desktop release workflow posture, absence of `pull_request_target`, suspicious local secret-looking filenames, and release-doc honesty.
- The report deliberately returns `manual_required` when local checks pass because GitHub settings, release-environment secrets, Apple Developer ID credentials, notarization credentials, and published artifact verification must still be checked outside the local workspace.
- `docs/public_release_checklist.md` and `docs/release_process.md` now tell maintainers to expect `manual_required`, not a false all-clear, before public macOS distribution.

Validation passed locally:

```bash
python3 -m unittest python/runner-core/tests/test_release_ci.py
python3 ./scripts/check_public_release_readiness.py
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 0
```
