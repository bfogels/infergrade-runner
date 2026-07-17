# Public Release Checklist

Use this checklist before making `infergrade-runner` public and again before major public releases.

## Local Repository Checks

Run from the Runner repo root:

```bash
git fetch origin --prune
python3 ./scripts/check_public_release_readiness.py
gitleaks detect --source=. --redact --no-banner --exit-code 1
git log --all --name-only --pretty=format: | sort -u | rg '(^|/)(\.env|\.env\.|.*\.(pem|p12|pfx|cer|crt|key|mobileprovision|provisionprofile)|AuthKey_.*\.p8|.*signing.*|.*notary.*|secrets?/)($|/)'
rg -n 'pull_request_target|secrets\.|TAURI_SIGNING_PRIVATE_KEY|APPLE_CERTIFICATE|APPLE_API_PRIVATE_KEY|APPLE_PASSWORD' .github/workflows
./scripts/test_all.sh
```

Expected results:

- `gitleaks` finds no leaks.
- `check_public_release_readiness.py` runs from a clean Git worktree and returns `manual_required`, not `fail`; its manual gates are expected because local checks cannot inspect GitHub release-environment settings, Apple Developer ID credentials, notarization credentials, or published artifacts.
- The filename-history scan finds no committed secrets, certs, keys, `.env` files, Apple signing materials, or notary materials.
- Secret references appear only in trusted release or publishing workflows that do not run on untrusted pull-request code.
- Tests pass or failures are documented as unrelated release blockers.

## GitHub Settings

Verify after the repository is public:

- Actions default workflow token permissions are read-only.
- Fork pull requests require approval before running workflows.
- Secret scanning and push protection are enabled if available.
- `main` has branch protection or a ruleset that requires review and passing checks.
- The `release` environment is restricted to deployments from `main`.
- The `release` environment requires maintainer review before jobs can access signing or notarization secrets.
- Apple signing, App Store Connect, and Tauri updater secrets exist only in the `release` environment, not as broad repository secrets.

GitHub required reviewers may be unavailable for private repositories on some plans. If GitHub rejects the rule before the public flip, configure it immediately after the repository becomes public.

Local readiness automation intentionally reports GitHub settings as a manual gate. Do not treat a local `manual_required` result as public-release proof until the release environment restrictions, required reviewers, branch protection, secret scanning, and published-artifact verification have been checked in GitHub.

## Documentation And Policy

Confirm these files exist and match the release posture:

- `LICENSE`
- `SECURITY.md`
- `CONTRIBUTING.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/benchmark_methodology.md`
- `.github/ISSUE_TEMPLATE/security.md`
- `docs/third_party_license_audit.md`

The README should distinguish what works today from what is preview, planned, or limited. It should also state that the Desktop first-run path is being built to avoid Docker, while Docker may still be needed for advanced sandboxed or container-friendly benchmark lanes.

## Credential Rotation

Before the first public release, rotate or reissue credentials that previously existed as broad repository secrets:

- Tauri updater signing key or password
- App Store Connect API key
- Apple certificate password, and preferably the exported certificate if practical

Do not paste replacement values into issues, PRs, docs, screenshots, or local committed files.

## Published Artifact Verification

After the protected desktop workflow publishes `desktop-runner-latest`, download the DMG, updater archive, updater `.sig`, updater manifest, and `SHA256SUMS` into one directory and run:

```bash
python3 ./scripts/verify_desktop_release_artifacts.py \
  --directory /path/to/downloaded/desktop-runner-latest \
  --require-dmg \
  --required-dmg-name InferGrade.Runner.macOS-arm64.dmg \
  --require-updater
```

This proves local artifact-manifest consistency only. It does not replace Developer ID signing, notarization, Gatekeeper assessment, stapled-ticket checks, or a clean-machine launch smoke. Windows and Linux package smoke artifacts are not supported public installers.
