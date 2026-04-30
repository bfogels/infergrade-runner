# InferGrade Strategy

## One-Sentence Positioning

InferGrade should become the open benchmark execution standard for quantized LLM deployment, with a hosted hub that turns those runs into community evidence and trustworthy recommendations.

## Core Product Split

InferGrade is two products built on one contract:

- `InferGrade Runner`: the open-source execution layer
- `InferGrade Hub`: the hosted identity, recommendation, and community layer

The runner should be broadly portable and maximally reproducible.
The hub should be the best place to sign in, connect accounts, generate runs, publish evidence, and consume recommendations.

The canonical boundary is documented in [docs/runner_vs_hub.md](runner_vs_hub.md).

## Mission

Help developers, researchers, and infrastructure builders choose and benchmark quantized LLM configurations with confidence by making execution easy and comparison trustworthy.

## Why This Matters

Quantized LLM deployment is confusing in practice because the information surface is fragmented:

- results are posted ad hoc across Reddit, Discord, and model cards
- many findings are underspecified or not reproducible
- artifact identity is often fuzzy
- hardware context is frequently incomplete
- capability claims and deployment claims are disconnected
- and users have to do too much manual setup before they can test anything themselves

InferGrade should reduce that ambiguity.

## Product Thesis

The highest-impact version of InferGrade is not a generic benchmark website.

It is:

- an open, low-friction runner that can execute trustworthy benchmark jobs anywhere
- plus a hosted hub that aggregates those results into identity-aware, community-aware, continuously recomputed recommendations

This keeps the execution standard open while allowing the product experience to be much stronger than a self-host-everything model would allow.

## Strategic Wedge

The wedge is:

"Make it extremely easy to run a trustworthy quantized-model benchmark job, then make the hosted InferGrade Hub the best place to understand and reuse the result."

That means:

- the runner must be easy to install and execute
- the hub must be clearly better than scattered forum posts for discovery and trust
- and the shared contract between them must stay explicit and versioned

## Primary User

The primary user is still an open-source practitioner making a deployment decision, but the product now has two modes:

- `operator mode`: I want to run a benchmark locally or in cloud with minimal friction
- `consumer mode`: I want to sign into the hub, browse evidence, generate runs, and choose a model with confidence

## Core User Questions

InferGrade should help users answer:

1. What model and quant should I run on my hardware?
2. What configuration fits my VRAM or cost budget?
3. Which result is trustworthy enough to act on?
4. Can I run the same benchmark job locally or in cloud with minimal friction?
5. Can I connect my Hugging Face account and stop hand-entering artifact details?
6. Can I contribute a result that becomes part of a real community evidence base?

## Design Principles

### 1. Open Execution, Hosted Intelligence

The runner should be open and portable.
The hub should be the best hosted product experience.

### 2. Decision-Making Over Ranking

InferGrade should optimize for recommendations and tradeoff visibility, not abstract winners.

### 3. Trust Over Coverage

Fewer high-confidence runs are better than large noisy catalogs.

### 4. Reproducibility Over Peak Numbers

Every serious result should be rerunnable within a reasonable variance band.

### 5. Real Workloads Over Vanity Tests

The benchmark should reflect actual deployment behavior and real user tasks.

### 6. Shared Contracts Over Blurry Boundaries

The runner and hub should communicate through stable run configs, result bundles, and schemas.

### 7. Low-Friction Execution Over Manual Setup

Users should not have to hand-enter artifact, quantization, and runtime details when the system can infer them.

### 8. Identity and Credentials Belong in the Hub

The hosted hub should own SSO, connected accounts, and external credentials such as Hugging Face access.

## Product Surfaces

## 1. InferGrade Runner

The open-source runner should handle:

- local and cloud execution
- artifact resolution and caching
- backend and benchmark containers
- telemetry capture
- capability execution
- bundle generation
- resumability and preflight checks
- optional upload to the hub

## 2. InferGrade Hub

The hosted hub should handle:

- sign-in and contributor identity
- connected Hugging Face credentials
- run planning and run-config generation
- recommendations and compare views
- community result hosting and browsing
- trust signaling and moderation
- cloud-launch flows and later provider-managed execution

## 3. Shared Data Contract

The shared contract should remain open and versioned:

- run config schema
- result bundle schema
- ontology schema
- validation and trust rules

## Hosted Hub Strategy

InferGrade Hub should be treated as the canonical hosted product.

It does not make strategic sense to optimize for broad third-party self-hosting of the hub right now because:

- identity, SSO, and connected credentials are core product value
- community effects matter
- canonical trust policy matters
- recommendation quality depends on shared data and shared policy
- and the best user experience comes from one well-run hosted surface

The self-hostable thing should be the runner, not the full hub.

## Capability and Deployment Model

InferGrade should still combine:

1. trusted capability benchmarks for important use cases
2. clean deployment telemetry from canonical workloads
3. strict configuration identity and ontology
4. derived recommendations based on thresholds and Pareto frontiers

That part of the thesis does not change.

## Strategic Focus

The next public release should prove four things:

1. the runner can execute real benchmark jobs reproducibly with low friction
2. the hub can generate and manage those runs for signed-in users
3. connected Hugging Face resolution meaningfully reduces setup friction
4. hosted recommendations and comparisons are better than scattered community anecdotes

## Anti-Goals

- Do not optimize the hub as a generic self-hosted deployment target.
- Do not make the runner depend on the hub for every use case.
- Do not blur identity, execution, and recommendation concerns together.
- Do not build a leaderboard-first experience that ignores trust.
- Do not let manual form entry remain the dominant way to create runs.

## Success Condition

InferGrade succeeds if:

- the runner becomes the easiest trustworthy way to produce a benchmark bundle
- the hub becomes the best place to browse, compare, publish, and act on that evidence
- and the open-source community starts using InferGrade results as a more trustworthy replacement for scattered benchmark claims
