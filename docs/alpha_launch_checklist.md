# InferGrade First-User Launch Checklist

This document defines what must be true before InferGrade is ready for a small first-user release wave.

The goal here is not broad benchmark coverage or perfect methodology. The goal is a trustworthy first-user path that outside users can actually complete:

1. open the site
2. generate a run config
3. run it locally in containers
4. resume safely if interrupted
5. upload the bundle
6. browse the result in a shared catalog

## First-User Promise

For the first-user release wave, InferGrade should truthfully be able to claim:

- there is a known-good `llama.cpp` lane
- users can generate server-issued run configs from the web UI
- hosted APIs can protect write operations with a simple token
- bundle uploads persist into a shared catalog
- the web app helps users choose a model from real evidence
- the system is clear about trust levels and current limitations

## Hard Blockers

These are the current blockers to putting InferGrade in front of initial external users.

### 1. Golden-Path Installation

- Publish prebuilt container images for:
  - `infergrade-llama-cpp`
  - `infergrade-ifeval`
  - `infergrade-evalplus`
- Provide one known-good demo run config that works with a public GGUF.
- Add one bootstrap flow that tells users exactly what to install and in what order.

Exit criteria:

- a new user can complete the first canary run without building custom images locally
- the first-run docs are copy-pasteable and tested on a clean machine

### 2. Hosted Access Controls

- Protect API write endpoints with a bearer token
- Keep public read access optional for the catalog
- Expose client-facing auth expectations to the web app
- Document how to set the token and allowed origins in deployment

Exit criteria:

- outside users cannot write to the shared catalog without a token
- browser-based run-config generation still works when a token is provided

### 3. Trust And Validation

- Tighten bundle acceptance rules
- Reject obviously incomplete or malformed uploads
- Surface clearer trust states in the UI and API
- Keep simulated and real evidence visibly distinct

Exit criteria:

- the shared catalog cannot quietly mix misleading evidence with real verified runs

### 4. First-Run Onboarding

- Make the first-run path obvious in the web app
- Recommend one demo preset and one serious preset
- Generate exact `doctor`, `run-config`, and `upload-bundle` commands
- Explain token use and resume behavior clearly

Exit criteria:

- a technically comfortable open-source user can finish a run without asking us what to do next

### 5. Operational Robustness

- Better disk-space and cache guidance
- Clearer artifact download failures
- Better long-run progress visibility
- Safer API deployment defaults

Exit criteria:

- the most common failure states feel recoverable, not mysterious

## Good Enough For The First-User Wave

These are explicitly not blockers for a small first-user release wave:

- full `vLLM` support
- large benchmark breadth
- public cloud execution marketplace
- polished result-detail pages
- final recommendation methodology

## What We Implemented This Pass

- optional bearer-token protection for API write endpoints
- configurable CORS origins for hosted API deployment
- a public `/client-config` endpoint so the web app can adapt to hosted auth requirements
- runner CLI and transport support for `--api-token` and `INFERGRADE_API_TOKEN`
- web UI support for API token entry, hosted-auth messaging, and auth-aware generated commands
- alpha container build/export scripts plus a GHCR publish workflow
- server-side validation that now normalizes trust labels instead of accepting client claims at face value
- a known-good first-user quickstart with a pinned TinyLlama demo run config

## Next Implementation Sprint

1. publish prebuilt runtime and capability images
2. add a tested first-user quickstart guide with one known-good run config
3. harden server-side bundle validation and trust gating
4. add stronger first-run onboarding surfaces in the web app
5. run 3-5 outside-user alpha tests and record friction points in memory
