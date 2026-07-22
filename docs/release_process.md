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
2. refuses a non-`main` dispatch, a version override that differs from the checked-out `VERSION`, or a `vX.Y.Z` tag that does not resolve to the dispatched commit, then anonymously verifies all five matching GHCR image tags before spending signing or build time
3. builds the source sidecar wrapper for the CI host's Rust target triple
4. builds the macOS Apple Silicon desktop app
5. verifies the protected release signing and notarization inputs before building user-downloadable artifacts
6. signs and notarizes the Tauri updater archive and macOS bundle with the configured release credentials
7. verifies the app bundle and DMG with `codesign`, Gatekeeper assessment, and stapled notarization-ticket checks
8. renames the notarized DMG to the stable public asset `InferGrade.Runner.macOS-arm64.dmg`, creates or resumes the draft release for the exact `vX.Y.Z` tag, and uploads the DMG, updater archive, updater signature, updater manifest, and checksums
9. removes draft assets outside the exact checksummed set, redownloads and verifies the draft, then publishes it as an immutable versioned GitHub release and anonymously probes the updater and installer through GitHub's `releases/latest` redirect

The desktop release deliberately does not fall back to older capability images. Scorer and dataset containers are part of the benchmark protocol identity; publishing an app whose matching tags are missing would either break selected benchmarks or silently change their evidence basis.

The same workflow also runs unsigned Windows and Linux package smoke jobs. Those jobs build NSIS/MSI artifacts on `windows-latest` and AppImage/`.deb` artifacts on `ubuntu-22.04`, write `SHA256SUMS` manifests for the emitted packages, then upload them as GitHub Actions artifacts for maintainer inspection. They are package-readiness gates only; they do not publish to the desktop release tag and they do not replace Windows Authenticode signing, Linux install/launch validation, or platform-specific support notes.

The protected GitHub workflow must not fall back to ad-hoc macOS signing or skip notarization. Local developer builds can still use ad-hoc signing, but any DMG published for users must be Developer ID signed, notarized, and verified on a clean macOS machine before external distribution.

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
