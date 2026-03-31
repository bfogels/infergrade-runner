# InferGrade Runner vs Hub

## Why This Split Matters

InferGrade should not be one blurry product.

It should be two tightly connected products with a shared contract:

- `InferGrade Runner`: the open-source execution engine
- `InferGrade Hub`: the hosted control plane, community layer, and recommendation product

This split makes the product easier to trust, easier to explain, and easier to grow.

The runner is where openness and reproducibility matter most.
The hub is where identity, integrations, community, and managed workflows matter most.

## InferGrade Runner

The runner should be fully open-source.

Its job is to make benchmark execution as low-friction and trustworthy as possible across local and cloud environments.

### Runner Responsibilities

- execute server-issued or locally authored run configs
- resolve and cache artifacts
- run backend containers and benchmark containers
- capture deployment telemetry and capability results
- produce normalized result bundles
- upload bundles back to the hub when configured
- support resumability, preflight checks, and portable execution

### Runner Non-Goals

- do not become the identity system
- do not own recommendations or community browsing
- do not require the hosted hub to be useful
- do not carry long-lived user accounts as a primary concern

## InferGrade Hub

The hub should be treated as the canonical hosted InferGrade product.

It is where users sign in, connect their external accounts, generate runs, browse evidence, and receive recommendations.

### Hub Responsibilities

- user identity and single sign-on
- connected credentials such as Hugging Face API tokens
- run planning and run-config generation
- hosted catalog storage for results and bundles
- recommendation, comparison, and estimation surfaces
- community contribution, attribution, and trust signaling
- cloud-launch workflows and later provider-managed execution

### Hub Non-Goals

- it should not be optimized as a general self-hosted deployment target
- it should not force advanced users to stop using the runner directly
- it should not hide the underlying schemas or bundle contracts

## Shared Contract

The runner and hub should meet through explicit, versioned artifacts:

- `run config`: the execution program the runner can consume
- `result bundle`: the normalized output the hub can ingest
- `shared schemas`: the stable contract between the two

That contract is more important than whether every surrounding service is open-source.

## Identity and Credentials

This split also clarifies security.

### Hub Owns Identity

- sign-in and user accounts
- contributor identity
- organization/team concepts later
- connected external credentials

### Runner Uses Scoped Access

The runner should receive only what it needs to execute a run:

- a run config
- a hub API token or signed upload credential
- short-lived or scoped access to private artifacts when necessary

The runner should not become the long-lived home for user identity.

## Hugging Face Integration

The hub should connect to a user's Hugging Face account or API token and use that connection to:

- infer model and artifact choices
- support gated or private artifact access
- reduce builder friction
- keep model-selection flows centered around the ecosystem people already use

The runner should consume the resolved artifact plan rather than force users to hand-enter Hugging Face details repeatedly.

## Recommended User Flows

### 1. Hosted Local Run

1. User signs into InferGrade Hub.
2. User connects Hugging Face.
3. Hub recommends or generates a run config.
4. User launches the open-source runner locally.
5. Runner executes and uploads the bundle automatically.
6. Hub shows the result in `My Runs`, compare views, and recommendations.

### 2. Hosted Cloud Run

1. User signs into InferGrade Hub.
2. User chooses `Run in cloud`.
3. Hub creates the run job and manages the launch path.
4. A runner instance executes remotely.
5. Bundle uploads automatically.
6. Hub shows progress, trust state, and final results.

### 3. Standalone Runner

1. User installs the open-source runner.
2. User runs a config locally without signing into the hub if they want.
3. User may keep the bundle local or upload it later.

This preserves openness while still allowing the hosted product to be the best experience.

## Open-Source Posture

The recommended posture is:

- open-source the runner
- keep schemas and bundle formats open
- keep benchmark definitions and validation rules transparent
- keep read-friendly data surfaces as open as practical
- treat the hub as the canonical hosted product, not as the primary self-host artifact

## Strategic Consequence

InferGrade should stop thinking of itself as "an open-source website plus runner."

It should think of itself as:

- an open benchmark execution standard
- plus a hosted intelligence and community product built on that standard

That is a cleaner, stronger foundation for adoption.
