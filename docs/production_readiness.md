# InferGrade Production Readiness

This document defines what must be true for InferGrade to move from a strong prototype into a production-grade Runner plus hosted Hub.

The goals are different for each side of the product:

- the `Runner` should feel trustworthy, portable, and easy to install
- the `Hub` should feel safe, durable, observable, and identity-aware

## Production Bar

InferGrade is production-ready when all of these are true:

1. users can sign in safely and connect external accounts without exposing long-lived credentials
2. runs can be created, observed, retried, cancelled, and audited as first-class jobs
3. results and bundles are stored durably outside the app container filesystem
4. the system can be monitored, rate-limited, backed up, and operated safely
5. the Runner can be installed and executed without developer-only setup knowledge

## Must-Have

### Hub Infra

- move catalog persistence to managed Postgres
- move bundle persistence to managed object storage
- replace local `openssl`-based secret sealing with a managed secret store
- add structured logs, metrics, traces, and error reporting
- add liveness and readiness checks that reflect real dependencies

### Hub Auth And Credentials

- move from dev-session scaffolding to production auth/session management
- support real session revocation and rotation
- store connected Hugging Face credentials through a proper secret manager
- issue scoped runner credentials instead of relying on shared write tokens

### Hub Job System

- add a queue-backed run orchestration layer
- support retries, cancellation, dead-letter handling, and job timeouts
- connect one real cloud provider so `Run in cloud` becomes truly one-click
- keep local and cloud jobs on the same observable lifecycle contract

### Runner

- publish signed releases and prebuilt images
- provide a real install story such as `pipx`, Homebrew, or both
- harden artifact downloads, cache cleanup, retries, and resumability
- improve telemetry completeness for TTFT, load time, GPU, and Apple Silicon
- widen the real backend matrix beyond the first `llama.cpp` lane

### Trust And Data Contract

- version and freeze the shared schemas
- sign or attest images and optionally bundles
- strengthen server-side provenance and trust policy enforcement
- keep public read/export APIs stable and easy to build on

## Beta

- team or organization concepts in the Hub
- richer moderation/admin tools for community data
- multiple cloud providers
- richer result detail pages and shareable compare links
- automated recurring reference runs and scheduled refreshes

## Later

- learned performance prediction models beyond the first heuristic estimator
- deeper org billing and quota management
- broader benchmark portfolio and official slices
- MCP layer over the mature agent API and run-job system

## Current Gaps

The current repo is already strong on:

- shared schemas and bundle contracts
- a real `llama.cpp` execution lane
- real capability containers for the first benchmark slice
- run-job lifecycle scaffolding
- GitHub OAuth-capable Hub sign-in
- connected Hugging Face credentials
- Hub-issued runner tokens

The biggest remaining production gaps are:

- the Hub still uses SQLite and local filesystem storage
- bundle storage is not yet backed by managed object storage
- secret storage is still a local-process mechanism
- run orchestration is still worker-driven rather than queue/provider-managed
- Runner installation and telemetry quality still need more hardening

## First Implementation Slice

The first productionization slice should be:

1. create a real storage abstraction for bundle persistence
2. expose a readiness endpoint that reports database, storage, and auth hardening state
3. externalize Hub storage configuration through env-driven deployment settings
4. keep the code path backward-compatible with the current local development flow

This slice does not finish productionization, but it creates the seam we need for managed storage and safer deployment checks.
