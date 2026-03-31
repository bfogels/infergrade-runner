# Run Jobs

## Why This Exists

InferGrade already had strong `discover` and `plan` surfaces:

- search
- compare
- recommend
- estimate
- generate run configs
- plan cloud launches

What it still lacked was a durable object for `act` and `observe`.

Run jobs are that missing object.

They are the API-backed record that connects:

- a run config
- an execution mode
- a lifecycle state
- execution commands or launch plans
- chronological events

## Current Goal

The current implementation is intentionally a thin orchestration layer, not a full cloud scheduler.

It lets InferGrade:

- create a durable run record
- attach local execution commands or cloud launch planning
- expose status and events
- support safe retries through idempotency
- support lifecycle actions like resume and cancel
- let workers claim jobs, report progress, and finalize outcomes

It still does not pretend to be a full provider-managed control plane.

## Core Endpoints

- `GET /v1/runs`
- `POST /v1/runs`
- `GET /v1/runs/{run_id}`
- `GET /v1/runs/{run_id}/watch`
- `GET /v1/runs/{run_id}/events`
- `GET /v1/runs/{run_id}/events/stream`
- `POST /v1/runs/{run_id}/resume`
- `POST /v1/runs/{run_id}/cancel`

## Lifecycle

Current status values:

- `awaiting_execution`
- `running`
- `paused`
- `completed`
- `failed`
- `cancelled`

New jobs start in `awaiting_execution`.

That means:

- the run config is resolved
- the run record exists
- commands or launch plans are attached
- execution has not yet been claimed by a worker

## Local vs Cloud

### Local container jobs

Local jobs are intended for a worker running on the operator's own machine or another self-hosted environment. They store:

- the run config reference
- a local worker-compatible execute command
- an upload command
- lifecycle state and events

### Cloud container jobs

Cloud jobs use the same lifecycle contract, but additionally attach:

- provider-ready cloud launch planning
- estimated cost
- provider/instance identifiers
- cloud launch events

That means the job model works for both locally hosted and cloud runs. The difference is not the API contract. The difference is which worker claims the job and where that worker is running.

Today, cloud execution still uses our current plan-first layer rather than direct provider orchestration.

## Worker Model

InferGrade now supports an active worker flow:

- `POST /v1/runs/claim`
- `POST /v1/runs/{run_id}/heartbeat`
- `POST /v1/runs/{run_id}/complete`
- `POST /v1/runs/{run_id}/fail`

Workers poll for compatible jobs, claim them, execute the run config, upload the finished bundle, and finalize the run record.

This creates one shared lifecycle for:

- self-hosted local runners
- long-lived workers on benchmark boxes
- future provider-backed cloud workers

The runner CLI now exposes this through `infergrade worker`.

Run-job records now emit worker-scoped launch commands by default:

- local runs emit a one-shot local worker command scoped to `run_id`
- cloud runs emit a one-shot cloud worker bootstrap command scoped to `run_id`

That makes the execution contract much closer to the eventual one-click model. The UI or API can create the run first, then hand the operator or provider a single worker command that performs claim, execute, and upload in one flow.

## Events

Every run job maintains chronological events such as:

- `run.created`
- `cloud.plan_attached`
- `run.claimed`
- `run.progress`
- `run.completed`
- `run.failed`
- `run.resume_requested`
- `run.cancel_requested`

This is the start of the observable run timeline we’ll eventually expose to both humans and agents.

InferGrade now also exposes two observation-friendly read patterns:

- `watch`: a single payload that includes the current run state plus current events
- `events/stream`: a server-sent-events stream for live updates and lightweight keepalives

That gives both polling clients and stream-capable clients a clean contract for long-running work.

## Idempotency

`POST /v1/runs` supports `Idempotency-Key`.

That means:

- agents can retry safely
- duplicate run creation is avoided
- conflicts are explicit if the same key is reused for a different payload

## Current Limitations

- Workers currently poll over HTTP.
- Local and self-hosted workers are real, but InferGrade still does not provision cloud hardware directly.
- Cloud jobs attach provider-ready launch plans and can be claimed by compatible workers, but InferGrade is not yet creating those workers on demand.
- Resume/cancel update the durable lifecycle state, but they do not yet send a hard control signal into an external provider runtime.

## Why This Is Still Valuable

Even with this thin worker model, run jobs are important because they give us:

- a stable API contract for agents
- a stable object for the web app to display
- a place to accumulate events and future state
- one execution contract that works across local-hosted and cloud environments

## Next Step After This

The next major milestone should be:

1. one provider-backed execution worker deployment path
2. event streaming
3. stronger remote control semantics for resume/cancel
4. agent-facing run-status and control flows built on top of that
