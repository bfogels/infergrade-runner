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

| Boundary | Rule |
| --- | --- |
| Runner owns | `schemas/json/*.json`, `schemas/examples/*`, `schemas/capability_catalog.json`, benchmark-scope metadata, metadata ordering, ontology identity rules, contract versioning, publication, and compatibility notes. |
| Hub may render | Imported schemas, imported capability suites/groups/checks, imported benchmark-scope summaries, Runner-declared contract/release versions, and result/bundle fields emitted by Runner. |
| Hub may derive locally | Presentation filters, UI grouping, recommendation sorting, user-specific slices, and operational diagnostics that do not redefine contract semantics. |
| Hub must not author | New ontology meaning, result or bundle shapes, benchmark scope semantics, effort/duration/token ordering, or release-truth labels without a coordinated Runner contract change. |

## Publication Model

Runner publishes contract bundles that include:

- a contract manifest
- JSON schemas
- examples
- selected contract docs

These bundles are the unit the Hub should pin to.

## Versioning Model

The contract and Runner package use independent version sequences. A schema
change increments `schemas/contract_manifest.json`; a feature PR does not bump
the Runner package version unless it is also the release PR. The exported
contract bundle remains the explicit compatibility unit Hub pins.

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
