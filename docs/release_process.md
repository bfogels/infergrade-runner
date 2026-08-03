# Runner Release Process

This is the current reproducible release-prep workflow for the InferGrade Runner pinned setup path.

The goal is to produce one versioned bundle that the Hub can pin to explicitly:

- release-tagged runtime images
- a release manifest with checksums
- the Runner-owned contract bundle

## Versioned Release Bundle

Pushing a `v*` release tag or deliberately dispatching
`.github/workflows/release-bundle.yml` builds the versioned bundle. The workflow:

1. installs the Runner package
2. checks all version declarations against `VERSION`
3. exports the Runner release bundle for `$(cat VERSION)`
4. uploads `dist/releases/$(cat VERSION)/` as a GitHub Actions artifact

The default tagged artifact includes the contract bundle and release manifest with image references. It does not build or upload Docker image archives unless a maintainer deliberately dispatches the workflow with `include_image_archives=true`. Ordinary `main` promotions do not create release-bundle artifacts.

Tag-triggered release, contract, and container workflows fail unless the tag is
exactly `v$(cat VERSION)` and the tagged commit belongs to fetched `main`
history. This prevents a mistyped tag from publishing container and bundle
artifacts under different versions. The manual portable-image bundle receives a
larger bounded timeout because it cold-builds and exports all canonical images;
the normal tagged bundle retains the shorter limit.

`VERSION` is the human-edited release version. Some package managers still require static manifest versions, so after changing `VERSION`, run:

```bash
python3 ./scripts/sync_versions.py
python3 ./scripts/sync_versions.py --check
```

CI runs the same check and fails if any required package manifest copy is stale.
Pull requests to `main` may be version-neutral source promotions. When such a PR
does change `VERSION`, CI still requires a forward version bump; an unchanged
`VERSION` does not turn an ordinary promotion into a release.

Every push to `main` also runs the trusted `sync-main-to-develop.yml`
workflow. If `develop` is simply behind, the workflow opens an ancestry-only
`main -> develop` PR and enables merge after the released commit's protected
checks pass. If both branches advanced, it creates a temporary integration
branch from `develop`, merges `main` there, dispatches the protected CI and
secret-scan workflows for that exact commit, and auto-merges only after those
checks pass. Conflicts create a visible maintenance issue; neither long-lived
branch is force-pushed, and unreleased `develop` work is never merged into
`main`. CI rejects new PRs into `develop` while this ancestry invariant is
unsatisfied.

Local equivalent:

```bash
./scripts/build_release_bundle.sh
```

After the exact promoted `main` commit receives its immutable `vX.Y.Z` tag, let the tag-triggered workflow publish all five canonical container tags, then verify that they are anonymously readable:

```bash
INFERGRADE_IMAGE_TAG="$(cat VERSION)" ./scripts/verify_release_images.sh
```

The verifier requests anonymous GHCR pull tokens directly, checks every runtime and capability image through the OCI Distribution API, and prints immutable index, Linux/amd64 manifest, and image-config digests for the release record. Do not distribute a Runner version whose matching images fail this check.

Before a public release candidate, also run the local readiness summary:

```bash
python3 ./scripts/check_public_release_readiness.py
```

The expected healthy local result from a clean Git worktree is `public_release_readiness=manual_required`, not `pass`. The command checks repository-local docs, scripts, workflow posture, Git state, and suspicious secret-looking filenames. It deliberately leaves GitHub settings, release-environment secrets, signing credentials, notarization credentials, and published artifact verification as manual gates.

## Desktop App Release

Maintainers deliberately dispatch `.github/workflows/desktop-runner-release.yml`
from `main` after the versioned source promotion and local release checks are
complete. Ordinary pushes and documentation promotions do not publish desktop
artifacts. The workflow:

1. resolves the desktop app version from `VERSION`
2. refuses a non-`main` dispatch, a version override that differs from the checked-out `VERSION`, or a `vX.Y.Z` tag that does not resolve to the dispatched commit, then anonymously verifies all matching GHCR image tags before spending signing or build time
3. builds the platform sidecar and desktop packages independently on macOS, Windows, and Linux hosts
4. Developer ID signs every Mach-O executable and library in the bundled macOS Python runtime with hardened runtime and a secure timestamp, reseals its integrity receipt, signs and notarizes the Apple Silicon app and updater, then verifies the bundle and DMG with `codesign`, Gatekeeper assessment, and stapled notarization-ticket checks
5. performs OS-native package acceptance: MSI administrative install plus NSIS install and launch on Windows, and `.deb` install plus AppImage extraction and launch under Xvfb on Linux; both lanes execute the packaged sidecar self-test with system-Python discovery blocked and require the pinned bundled runtime receipt
6. gives the verified packages stable public names and uploads each platform set as a short-lived workflow artifact
7. waits for every platform job, combines their checksums into one exact release manifest, and creates Sigstore-backed GitHub build-provenance attestations for the final asset set
8. verifies the attestation signer workflow and `main` source-ref policy, then creates or resumes the draft release for the exact `vX.Y.Z` tag
9. removes draft assets outside the exact checksummed set, redownloads and verifies the full draft, then publishes it as an immutable versioned GitHub release
10. redownloads the published versioned asset set, verifies checksums and provenance again, and probes the stable updater, macOS DMG, Linux `.deb`, Linux AppImage, and any explicitly published Windows preview through GitHub's `releases/latest` redirect

The desktop release deliberately does not fall back to older capability images. Scorer and dataset containers are part of the benchmark protocol identity; publishing an app whose matching tags are missing would either break selected benchmarks or silently change their evidence basis.

Linux x86_64 `.deb` and AppImage packages are published only after their install,
sidecar, and launch smoke passes. Windows MSI and NSIS packages pass the same
class of hosted-runner smoke but remain short-lived workflow artifacts by
default because they are not Authenticode signed. A protected dispatch may opt
into publishing them only under filenames containing
`UNSIGNED-PREVIEW`; release notes must preserve the SmartScreen warning. Neither
hosted lane proves CUDA, GPU detection, model execution, Hub upload, or a full
Windows/NVIDIA contribution loop.

The path-filtered `Desktop Platform Smoke` workflow runs the Windows and Linux
package acceptance on relevant pull requests, while the normal Rust CI matrix
compiles and tests Windows-specific code on every pull request. Standard hosted
runners prove operating-system compatibility and packaging, not accelerator
support. After successful package acceptance, the workflow retains the
checksummed Linux candidates and clearly named unsigned Windows candidates for
seven days so maintainers can inspect or install the exact bytes CI tested.
Every candidate bundle contains a checksummed
`CI-CANDIDATE-NOT-A-RELEASE.txt` recording its source ref and commit. Pull
request candidates are untrusted proposed code; they are not signed, attested,
or suitable for ordinary user distribution.

The protected release publisher creates GitHub artifact attestations with the
official `actions/attest` action and verifies each asset against the exact
Runner repository, desktop release workflow, and `refs/heads/main`. These
Sigstore-backed provenance statements make the producing workflow and source
ref independently inspectable. They complement checksums and platform signing;
they do not replace Apple notarization, Windows Authenticode, SmartScreen
acceptance, or real GPU execution.

The protected GitHub workflow must not fall back to ad-hoc macOS signing or skip notarization. Local developer builds can still use ad-hoc signing, but any DMG published for users must be Developer ID signed, notarized, and verified on a clean macOS machine before external distribution.

Bundled interpreters are nested code, not inert resources. The protected macOS
lane imports the Developer ID certificate into an ephemeral keychain, signs
each unique Mach-O file in `python-runtime` before Tauri bundles the app, and
refreshes the runtime receipt after that reviewed transform. Apple notarization
must reject the candidate if any embedded executable or library lacks a valid
Developer ID signature, hardened runtime, or secure timestamp.

Release signing and notarization secrets must live in the GitHub `release` environment, not as broad repository secrets. The `release` environment should be restricted to deployments from `main`. When the repository plan supports it, add required maintainer review to the environment before jobs can access the signing secrets.

The release workflow accepts either Apple ID app-specific password notarization credentials or App Store Connect API-key credentials. The API-key lane uses `APPLE_API_KEY`, `APPLE_API_ISSUER`, and `APPLE_API_PRIVATE_KEY`; the workflow writes the private key into the runner temp directory as `APPLE_API_KEY_PATH` before invoking Tauri. The signing identity can come from `INFERGRADE_MACOS_SIGNING_IDENTITY` as a release environment variable or from the `APPLE_SIGNING_IDENTITY` secret.

Before the full Tauri build starts, CI decodes `APPLE_CERTIFICATE` as a `.p12` file and verifies that it opens with `APPLE_CERTIFICATE_PASSWORD`. If that preflight fails, re-export the Developer ID Application certificate and update both GitHub release-environment secrets together.

If a downloaded DMG produces the macOS "`InferGrade Runner.app` is damaged and can't be opened" dialog, discard that artifact. Do not ask users to bypass Gatekeeper. Rebuild through the protected release workflow, confirm Developer ID signing and notarization completed, and re-test the DMG on a clean macOS machine.

### Recover A Certificate Secret Failure

When the workflow fails at `Validate Apple signing certificate password`, fix the certificate and password as a pair. Do not rotate only one of the two secrets.

1. Export the Developer ID Application certificate from Keychain Access as a password-protected `.p12`.
2. Verify that the exported file opens locally with the same password you will store in GitHub:

   ```bash
   APPLE_CERTIFICATE_PASSWORD='the-p12-password' \
     openssl pkcs12 -in ~/Desktop/infergrade-developer-id-application.p12 \
       -nokeys -passin env:APPLE_CERTIFICATE_PASSWORD >/dev/null
   ```

3. Base64-encode the verified `.p12` without line wrapping:

   ```bash
   base64 -i ~/Desktop/infergrade-developer-id-application.p12 | tr -d '\n' > ~/Desktop/infergrade-developer-id-application.p12.b64
   ```

4. Update the protected GitHub release environment secrets together:

   - `APPLE_CERTIFICATE`: contents of the `.p12.b64` file
   - `APPLE_CERTIFICATE_PASSWORD`: the password used by the local `openssl pkcs12` check

After you update the certificate and password secrets together, deliberately dispatch the `Desktop Runner Release` workflow from `main`. A passing preflight only proves the certificate opens; the workflow must still complete signing, notarization, Gatekeeper assessment, stapled-ticket checks, and anonymous updater verification before the DMG is user-ready.

## Actions Budget And Public-Fork Boundary

Validation workflows run for pull requests targeting `develop` or `main` and
for pushes to those two integration branches. Feature-branch pushes do not
duplicate the pull-request run. Superseded validation runs are cancelled by a
workflow-level concurrency group.

All workflow jobs have explicit timeouts. Temporary release, package-smoke, and
runtime-intake artifacts have bounded retention. Third-party and GitHub-owned
actions are pinned to immutable commit SHAs, and validation checkouts do not
persist Git credentials. Pull-request jobs remain read-only and must never
receive release, package-publishing, signing, notarization, Hub, or model-registry
secrets.

### Verify Published Desktop Artifacts

After the protected workflow publishes the immutable versioned Desktop release,
download its files into one directory and verify the local manifests:

```bash
scripts/verify_desktop_release_artifacts.py \
  --directory /path/to/downloaded/vX.Y.Z \
  --require-dmg \
  --require-updater
```

This check verifies `SHA256SUMS`, confirms the updater manifest points at a local updater archive, and confirms the updater signature artifact exists and is non-empty. It is a manifest consistency check only. It does not replace Developer ID signing, notarization, Gatekeeper assessment, stapled-ticket checks, or clean-machine launch smoke.

Verify the published build provenance for an individual downloaded asset with:

```bash
gh attestation verify /path/to/InferGrade.Runner.Linux-x86_64.AppImage \
  --repo bfogels/infergrade-runner \
  --signer-workflow bfogels/infergrade-runner/.github/workflows/desktop-runner-release.yml \
  --source-ref refs/heads/main
```

## Prepare The Release Images

Build the release-tagged local images:

```bash
bash ./scripts/build_release_images.sh
```

Export the resulting OCI archives:

```bash
bash ./scripts/export_release_images.sh
```

By default this uses `$(cat VERSION)`; set `INFERGRADE_IMAGE_TAG` to override it.

This writes archives under:

```text
dist/images/$(cat VERSION)/
```

## Export The Release Bundle

Generate the local release bundle:

```bash
./scripts/build_release_bundle.sh
```

This writes the pinned bundle under:

```text
dist/releases/$(cat VERSION)/
```

The release bundle includes:

- `release_manifest.json`
- `contract/contract_manifest.json`
- vendored schemas/examples/docs from the Runner contract bundle
- copied OCI image archives when they were exported locally
- checksums for bundled contract files and image archives

## Import The Pinned Release Into The Hub

From the Hub repo, import that exact release:

```bash
cd /Users/brianfogelson/Desktop/Code/infergrade/infergrade-hub
PYTHONPATH=services/api/src python3 ./scripts/import_runner_release.py \
  --release-dir /Users/brianfogelson/Desktop/Code/infergrade/infergrade-runner/dist/releases/$(cat /Users/brianfogelson/Desktop/Code/infergrade/infergrade-runner/VERSION)
```

That updates the Hub snapshot to include:

- `schemas/contract_manifest.json`
- `schemas/contract_source.json`
- `schemas/release_manifest.json`
- `schemas/release_source.json`

## Verify The Golden Path

At minimum, verify:

1. Runner tests pass.
2. A real, non-simulated capability canary produced by the release candidate has complete benchmark coverage and exact Runner-authored protocol identity:

   ```bash
   PYTHONPATH=python/runner-core/src \
     python3 scripts/verify_benchmark_protocol_identity.py /path/to/canary/bundle
   ```

   The verifier recomputes every per-check fingerprint and the aggregate fingerprint. It fails closed on missing identity, partial coverage, non-completed checks, a bundle without capability evidence, or any mismatch between the manifest's result files and their scored benchmark identities. A passing check proves the bundle is internally bound to its exact benchmark inputs, scoring policy, generation contract, and Runner registry version; it does not prove benchmark quality, model capability, cross-hardware equivalence, or repeatability.
3. Hub tests pass after importing the release.
4. The Hub exposes the pinned release through `/releases/current` and `/client-config`.
5. The generated local listener command defaults to the pinned release image instead of `:local`.

## Notes

- `:local` images remain a development convenience, not the product golden path.
- Apple Silicon native benchmarking remains an explicit separate lane because Metal is not exercised by the containerized local path.
