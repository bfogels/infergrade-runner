# Runner Release Process

This is the current local, reproducible release-prep workflow for the InferGrade Runner pinned first-user path.

The goal is to produce one versioned bundle that the Hub can pin to explicitly:

- release-tagged runtime images
- a release manifest with checksums
- the Runner-owned contract bundle

## Prepare The Release Images

Build the release-tagged local images:

```bash
./scripts/build_alpha_images.sh
```

Export the resulting OCI archives:

```bash
./scripts/export_alpha_images.sh
```

This writes archives under `dist/images/0.1.0-alpha/`.

## Export The Release Bundle

Generate the local release bundle:

```bash
python3 ./scripts/export_release_bundle.py --release-version 0.1.0-alpha
```

This writes the pinned bundle under:

```text
dist/releases/0.1.0-alpha/
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
  --release-dir /Users/brianfogelson/Desktop/Code/infergrade/infergrade-runner/dist/releases/0.1.0-alpha
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
