# Public Release Checklist

Use this checklist before making `infergrade-runner` public and again before major public releases.

## Local Repository Checks

Run from the Runner repo root:

```bash
git fetch origin --prune
gitleaks detect --source=. --redact --no-banner --exit-code 1
git log --all --name-only --pretty=format: | sort -u | rg '(^|/)(\.env|\.env\.|.*\.(pem|p12|pfx|cer|crt|key|mobileprovision|provisionprofile)|AuthKey_.*\.p8|.*signing.*|.*notary.*|secrets?/)($|/)'
rg -n 'pull_request_target|secrets\.|TAURI_SIGNING_PRIVATE_KEY|APPLE_CERTIFICATE|APPLE_API_PRIVATE_KEY|APPLE_PASSWORD' .github/workflows
./scripts/test_all.sh
```

Expected results:

- `gitleaks` finds no leaks.
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
