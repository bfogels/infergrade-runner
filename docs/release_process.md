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
2. builds the macOS Apple Silicon desktop app
3. verifies the protected release signing and notarization inputs before building user-downloadable artifacts
4. signs and notarizes the Tauri updater archive and macOS bundle with the configured release credentials
5. publishes the DMG, updater archive, updater signature, and updater manifest to the `desktop-runner-latest` GitHub release

The protected GitHub workflow must not fall back to ad-hoc macOS signing or skip notarization. Local developer builds can still use ad-hoc signing, but any DMG published for users must be Developer ID signed, notarized, and verified on a clean macOS machine before external distribution.

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
