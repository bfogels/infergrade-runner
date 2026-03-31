# InferGrade Runner Contract Ownership

## Purpose

InferGrade Runner is the authoritative source of truth for the InferGrade execution contract.

That contract includes:

- the model ontology
- run-request and run-config schemas
- bundle and result schemas
- example payloads that demonstrate the intended wire format

The hosted Hub may consume, validate, and present these contracts, but it should not silently redefine them.

## Why Runner Owns The Contract

The Runner is the open execution surface.

That makes it the right long-term home for:

- the ontology that identifies benchmark subjects
- the bundle shape emitted by real runs
- the schema versions external users and future agents should trust

If the Hub owns those definitions independently, the system will drift.

## Ownership Rules

### Runner Owns

- `schemas/json/*.json`
- `schemas/examples/*`
- the ontology model and benchmark-subject identity rules
- contract versioning and publication
- compatibility notes for older bundle versions

### Hub Consumes

- published schema bundles from Runner releases
- ontology and bundle contracts from Runner
- Runner-declared contract versions when generating run configs or validating uploads

### Hub Must Not

- hand-edit the meaning of the ontology independently
- invent a new result or bundle shape without a coordinated Runner contract change
- treat vendored schema snapshots as the ultimate source of truth

## Publication Model

Runner publishes contract bundles that include:

- a contract manifest
- JSON schemas
- examples
- selected contract docs

These bundles are the unit the Hub should pin to.

## Versioning Model

For now, the contract version follows the Runner package version.

That is acceptable while the system is early, but the contract should still be treated explicitly as a published artifact rather than an accidental side effect of the repo.

Future refinement may split:

- Runner package version
- contract version

if those need to move at different speeds.

## Hub Consumption Recommendation

The Hub should eventually replace direct schema authorship with one of:

1. a pinned contract bundle imported from a Runner release
2. a generated package built from the Runner contract bundle
3. a CI sync step that vendors Runner-published schemas into the Hub

In all three cases, the Runner remains authoritative.

## Immediate Rule For This Repo

If a schema or ontology change is needed:

1. make it in `infergrade-runner`
2. publish or export a new contract bundle
3. update the Hub to consume that version

That is the contract boundary we should optimize around going forward.
