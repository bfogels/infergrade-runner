# Third-Party License Audit

This is the public-release audit surface for vendored code and benchmark assets under `third_party/` and capability containers.

The goal is to make every vendored asset inspectable before the repository becomes public:

- identify the upstream source and exact revision
- confirm the upstream license is compatible with Apache-2.0 distribution
- copy required upstream license or notice files into the vendored subtree
- document any benchmark citation requirements
- flag datasets or assets that require access gates instead of vendoring

## Current Inventory

| Path | Source | Revision | Purpose | Status | Required before public release |
| --- | --- | --- | --- | --- | --- |
| `third_party/instruction_following_eval/` | Google Research `instruction_following_eval` | `fa55fe4af97c6756b6fe5b0639464f6b72f37c5a` | IFEval benchmark logic for the instruction-following capability container | Confirmed Apache-2.0; upstream `LICENSE` vendored in the subtree | Keep the vendored `LICENSE` and README citation visible alongside the code. |
| `containers/capability-gpqa/` | Official `idavidrein/gpqa` repository | `56686c06f5e19865c153de0fdb11be3890014df7`; dataset archive SHA-256 `461ae7329f15a3e35f8184d2dac24b990f34fdf12f366ca4062d8e6638cd08dc` | Builds a scorer image from the official 198-question GPQA Diamond split | Dataset confirmed CC BY 4.0; attribution copied to `LICENSE.dataset`; repository code is not vendored | Keep the revision, archive hash, dataset attribution, and strict diagnostic claim boundary pinned. |
| `containers/capability-bfcl/` | Official `ShishirPatil/gorilla` repository | `6ea57973c7a6097fd7c5915698c54c17c5b1b6c8`; individual BFCL V4 source-file and upstream-license SHA-256 digests in `build_snapshot.py` | Builds a 110-case, 11-category single-turn structured tool-use reference snapshot and local deterministic scorer | Upstream Apache-2.0; source rows and the full license are fetched only during image build after digest verification; `LICENSE.upstream` records attribution and the local-protocol boundary | Keep the commit, every source digest, full upstream license, selection policy, attribution, and non-official/non-agentic claim boundary pinned. |
| `containers/capability-longbench-v2/` | `zai-org/LongBench-v2` | Dataset revision `2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9`; source SHA-256 `15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2` | Builds and scores the pinned 23-row short-context local reference snapshot | Apache-2.0 dataset; the source is fetched and hash-verified at build time, and no prompt-bearing source rows are vendored in Git. The local reference and Runner manifest prove only the pinned selection/provenance boundary, not official LongBench results or empirical representativeness. | Keep the revision, source and snapshot hashes, attribution, raw `_id` digest convention, and local-reference claim boundary pinned. |
| `runtime/desktop_python_runtime.json` plus generated Desktop package resource | Astral `python-build-standalone` release `20260728` | CPython `3.12.13`; exact per-platform archive sizes and SHA-256 digests in the manifest | Self-contained Python runtime for packaged Runner-core bridge paths | Source build tooling is MPL-2.0; generated archives contain CPython and bundled dependency licenses. Archives are not checked into Git. | Preserve the target-specific CPython license path and all archive-provided package licenses; keep the source release and immutable archive identity in the generated receipt. |

## Audit Commands

Run from the repo root:

```bash
find third_party -maxdepth 3 -type f | sort
rg -n "license|copyright|notice|citation|arxiv|not an officially supported" third_party
```

These commands do not replace upstream review. They only show what is currently vendored and what attribution text is already present locally.

## Release Rule

Do not add new third-party benchmark code, fixtures, datasets, or generated assets without updating this audit file in the same PR.

Do not vendor access-gated datasets or private benchmark inputs. If a benchmark needs gated data, document the access requirement and make the Runner fail clearly until the user supplies the dataset through an explicit local path or credential flow.
