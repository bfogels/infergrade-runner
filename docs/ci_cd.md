# CI/CD: what runs when

GitHub Actions runs normally for this public repository. This page lists what each event triggers and the rules that keep that work proportional to what changed.

## Per event

| Event | Workflows | Notes |
|---|---|---|
| PR to `develop`/`main` | CI, Secret Scan, CodeQL (default setup); Desktop Platform Smoke and Managed Native Runtime Smoke only when their paths change | Required on `develop`: CI jobs + Gitleaks. Required on `main`: those + CodeQL. |
| Push to `main` | CI, Secret Scan, CodeQL, Sync main back to develop | The sync opens one integration PR into `develop` and closes older sync PRs it supersedes. |
| Automated sync PR (`automation/sync-main-to-develop-*`) | CI + Secret Scan (dispatched, required) | Optional smokes skip: every commit on it already passed them on the way to `main`. |
| `v*` tag | Publish Containers, Release Bundle, Contract Bundle | Containers are rebuilt only when their inputs changed (below). |
| Manual | Desktop Runner Release, managed runtime builds, runtime catalog | Long native builds never run on ordinary pushes. |

## Container reuse

`scripts/container_input_digest.py` fingerprints each image: Dockerfile text (including `ARG` pins), every path its `COPY`/`ADD` instructions read (contents, permission bits, symlink targets and empty directories), both build-context and Dockerfile-specific ignore rules, target platforms, and the current manifest of each `FROM` base image. Publishing tags every build `inputs-<fingerprint>`. When a later release produces the same fingerprint, `docker buildx imagetools create` re-tags the existing manifest list under the new version instead of rebuilding it. Unchanged images (EvalPlus, MMLU-Pro, …) therefore keep identical digests across Runner versions, which also strengthens benchmark reproducibility. Changed images build with a per-image GitHub Actions layer cache.

Base images are unpinned tags (`python:3.11-slim`, `ubuntu:22.04`), so an upstream base refresh changes the fingerprint and triggers a rebuild. Builds explicitly pull base images. Use `workflow_dispatch` with `force_rebuild: true` to rebuild everything without layer-cache reuse, including refreshing unpinned apt/pip dependencies. Ordinary input reuse intentionally retains those dependencies until an input changes or a forced refresh is requested. The fingerprint conservatively includes ignored files under COPY sources, so it can rebuild unnecessarily but never relies on a partial Docker ignore parser.

## Habits that matter more than workflow tuning

- **Batch releases.** Each `v*` tag republishes every container tag and release bundle. Cut a release when a set of changes is ready, not after each merged PR.
- **Never trigger long native builds (CUDA, desktop packaging) per push.** Build once per pinned upstream version, publish the artifact, and reuse it by checksum.
- **CodeQL** uses GitHub's default setup (repository Settings → Code security). It is required on `main`. If its cost becomes noticeable, switch to an advanced setup that runs on PRs to `main` plus a weekly schedule.
