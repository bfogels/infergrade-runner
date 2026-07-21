# Signed Runtime Catalog Operations

Status: review-candidate implementation. The checked-in metadata proves the
mechanism and pins llama.cpp b10069; it is not a production key ceremony.

## Security model

- Runner embeds the initial root and verifies root, timestamp, snapshot, and
  targets roles with Ed25519 threshold signatures.
- Root is 2-of-2. Timestamp, snapshot, and targets use distinct online keys.
- Metadata has explicit size ceilings, monotonic versions, expiries, and exact
  length/SHA-256 references. Target archives also have exact length/SHA-256.
- Publisher namespaces and allowed origins are root policy. A specialized
  publisher cannot replace an InferGrade target or claim an unauthorized
  origin.
- One target records build identity, receipt-manifest identity, distribution
  origin, distribution maturity, provenance strength, compatibility assertions,
  and support policy as separate fields.
- Catalog signing authenticates InferGrade's assertion. It is not evidence that
  upstream independently signed a checksum-only archive.

## Promotion

1. Prove the exact archive and full immutable build on supported hardware.
2. Record model-specific compatibility assertions with exact artifact digests
   and evidence bundle ids. Keep the corresponding bounded qualification record
   under `runtime/qualification/`. Do not create generic runtime-equivalence
   cohorts.
3. Edit `runtime/catalog/catalog-source.json`. Bump targets, snapshot, and
   timestamp versions; never rewrite an existing version.
4. Build metadata with `scripts/build_runtime_catalog.py`, keeping all private
   keys outside the repository. Generate `schemas/runtime_trust_catalog.json`
   in the same command.
5. Verify the role chain and install in a clean cache. Exercise tamper, expiry,
   rollback, wrong-platform, oversized-target, consent, and rollback tests.
6. Publish all four role files as one reviewed generation. Hub serves the exact
   imported files with ETags; partial publication is not a valid release.

## Offline and rollback behavior

Runner activates a complete verified generation atomically. Network failure may
use an unexpired last-known-good generation. Expired metadata cannot authorize
a new download, while installed immutable builds and existing run locks remain
usable offline. A catalog target names an exact installed rollback build. A
failed post-install identity check restores that selection; active run locks are
never rewritten.

## Revocation

Set `revoked: true`, add a bounded reason, and publish higher targets, snapshot,
and timestamp versions. Revocation blocks new installs, new run locks, and Hub
catalog trust matching. It does not delete bytes or mutate an already-active
attempt. Recovery is an explicit selection of a different reviewed build.

## Root rotation and compromise

A new root must be signed to the embedded root threshold and its own new
threshold, with exactly the next version. This deliberately bounded client
accepts the rotation only after both checks. A later root generation requires a
Runner release carrying the next trust anchor; the current implementation does
not skip or reconstruct intermediate roots. A compromised online role is replaced through a new root and new role
metadata. Root compromise requires a Runner release with a new trust anchor and
an explicit incident note; metadata alone cannot safely repair a lost root.

## Production gate

Before serving this catalog to released Runners:

- rotate or formally back up the review-candidate root keys using two separate
  offline custody locations;
- assign an automated timestamp refresh and expiry monitor;
- record the public catalog base URL and atomic upload owner;
- run the release acceptance matrix from the architecture decision;
- import the resulting exact trust projection into Hub and verify a real Result
  shows one compact “InferGrade-pinned runtime” indicator.

The current b10069 candidate is qualified by two local, unpublished,
standard-depth bundles: exact MiniCPM5-1B Q4_K_M and Gemma 4 E4B Q4_0
artifacts on Apple M1 Pro Metal. The machine-readable record is
`runtime/qualification/llama-cpp-b10069-macos-arm64.json`; it deliberately
does not claim family-wide or cross-platform compatibility.
