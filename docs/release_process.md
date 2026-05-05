# Runner Release Process

This is the current reproducible release-prep workflow for the InferGrade Runner pinned setup path.

The goal is to produce one versioned bundle that the Hub can pin to explicitly:

- release-tagged runtime images
- a release manifest with checksums
- the Runner-owned contract bundle

## CI Bundle On Main

Every push to `main` runs `.github/workflows/release-bundle.yml`. That workflow:

1. installs the Runner package
2. checks all version declarations against `VERSION`
3. exports the Runner release bundle for `$(cat VERSION)-preview`
4. uploads `dist/releases/$(cat VERSION)-preview/` as a GitHub Actions artifact

The default main-branch artifact includes the contract bundle and release manifest with image references. It does not build or upload Docker image archives on every commit, which keeps main CI fast and avoids very large per-commit artifacts. Maintainers can run the same workflow manually with `include_image_archives=true` when they need a fully portable archive bundle.

Local equivalent:

```bash
./scripts/build_release_bundle.sh
```

## Desktop App On Main

Every push to `main` also runs `.github/workflows/desktop-runner-release.yml`. That workflow:

1. resolves the desktop app version from `VERSION`
2. builds the source sidecar wrapper for the CI host's Rust target triple
3. builds the macOS Apple Silicon desktop app
4. verifies the protected release signing and notarization inputs before building user-downloadable artifacts
5. signs and notarizes the Tauri updater archive and macOS bundle with the configured release credentials
6. verifies the app bundle and DMG with `codesign`, Gatekeeper assessment, and stapled notarization-ticket checks
7. publishes the DMG, updater archive, updater signature, and updater manifest to the `desktop-runner-latest` GitHub release

The protected GitHub workflow must not fall back to ad-hoc macOS signing or skip notarization. Local developer builds can still use ad-hoc signing, but any DMG published for users must be Developer ID signed, notarized, and verified on a clean macOS machine before external distribution.

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

After you update the certificate and password secrets together, rerun the `Desktop Runner Release` workflow from `main`. A passing preflight only proves the certificate opens; the workflow must still complete signing, notarization, Gatekeeper assessment, and stapled-ticket checks before the DMG is user-ready.

## Prepare The Release Images

Build the release-tagged local images:

```bash
bash ./scripts/build_release_images.sh
```

Export the resulting OCI archives:

```bash
bash ./scripts/export_release_images.sh
```

By default this uses `$(cat VERSION)-preview`; set `INFERGRADE_IMAGE_TAG` to override it.

This writes archives under:

```text
dist/images/$(cat VERSION)-preview/
```

## Export The Release Bundle

Generate the local release bundle:

```bash
./scripts/build_release_bundle.sh
```

This writes the pinned bundle under:

```text
dist/releases/$(cat VERSION)-preview/
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
  --release-dir /Users/brianfogelson/Desktop/Code/infergrade/infergrade-runner/dist/releases/$(cat /Users/brianfogelson/Desktop/Code/infergrade/infergrade-runner/VERSION)-preview
```

That updates the Hub snapshot to include:

- `schemas/contract_manifest.json`
- `schemas/contract_source.json`
- `schemas/release_manifest.json`
- `schemas/release_source.json`

## Verify The Golden Path

At minimum, verify:

1. Runner tests pass.
2. Hub tests pass after importing the release.
3. The Hub exposes the pinned release through `/releases/current` and `/client-config`.
4. The generated local listener command defaults to the pinned release image instead of `:local`.

## Notes

- `:local` images remain a development convenience, not the product golden path.
- Apple Silicon native benchmarking remains an explicit separate lane because Metal is not exercised by the containerized local path.
