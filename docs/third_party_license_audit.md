# Third-Party License Audit

This is the public-release audit surface for vendored code and benchmark assets under `third_party/`.

The goal is to make every vendored asset inspectable before the repository becomes public:

- identify the upstream source and exact revision
- confirm the upstream license is compatible with Apache-2.0 distribution
- copy required upstream license or notice files into the vendored subtree
- document any benchmark citation requirements
- flag datasets or assets that require access gates instead of vendoring

## Current Inventory

| Path | Source | Revision | Purpose | Status | Required before public release |
| --- | --- | --- | --- | --- | --- |
| `third_party/instruction_following_eval/` | Google Research `instruction_following_eval` | `fa55fe4af97c6756b6fe5b0639464f6b72f37c5a` | IFEval benchmark logic for the instruction-following capability container | Needs license-file confirmation | Confirm upstream license, add the upstream license/notice file to the vendored subtree if required, and keep the README citation visible. |

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

