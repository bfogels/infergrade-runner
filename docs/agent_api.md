# Agent API

## Why This Exists

InferGrade should be useful to agents directly, not only through a human-facing website.

That means the product needs machine-native primitives for:

- discovering what InferGrade can do
- searching benchmark evidence
- requesting recommendations
- generating executable run configs
- estimating likely performance before a run
- comparing stored evidence

This is the first slice of that work.

## Current Scope

InferGrade now exposes an initial agent-native surface with:

- discovery via `GET /.well-known/infergrade-agent.json`
- `POST /v1/agent/search-results`
- `POST /v1/agent/recommendations`
- `POST /v1/agent/run-configs`
- `POST /v1/agent/estimate`
- `POST /v1/agent/compare`
- run-job resources under `/v1/runs`

These endpoints are intentionally thin wrappers over the existing decision engine and run-planning logic so human and agent recommendations do not drift apart.

## Design Principles

The agent API should be:

- versioned
- deterministic
- JSON-first
- explicit about trust and uncertainty
- easy to compose into larger workflows

It should not require agents to scrape HTML or infer hidden state from prose.

## Discovery

`GET /.well-known/infergrade-agent.json`

This document advertises:

- current agent API version
- auth requirements
- supported tools
- supported estimation metrics
- trust levels and comparison grades
- planned but not yet implemented tools

This gives an agent enough information to decide how to interact with InferGrade without hard-coding assumptions.

## Current Tool Mapping

- `infergrade.search_results`
  - `POST /v1/agent/search-results`
- `infergrade.recommend`
  - `POST /v1/agent/recommendations`
- `infergrade.generate_run_config`
  - `POST /v1/agent/run-configs`
- `infergrade.estimate_performance`
  - `POST /v1/agent/estimate`
- `infergrade.compare`
  - `POST /v1/agent/compare`

## Structured Recommendation Output

Recommendations now include:

- `reasons`
- `reason_codes`
- `tradeoffs`
- `tradeoff_codes`
- `next_actions`

This is important because agents need machine-readable explanations, not just a headline.

## Structured Errors

Agent endpoints return errors in a stable shape:

```json
{
  "error": {
    "code": "run_config_not_found",
    "message": "run config not found",
    "retryable": false
  }
}
```

This is the preferred contract for agent callers. The legacy human-oriented endpoints may still use simpler error payloads.

## Idempotency

The first write-like agent endpoint, `POST /v1/agent/run-configs`, supports `Idempotency-Key`.

If the same key is reused with the same payload:

- InferGrade replays the stored response

If the same key is reused with a different payload:

- InferGrade returns an `idempotency_key_conflict` error

This makes agent retries safer.

## Why MCP Is Not First

MCP is still a strong direction, but we are deliberately not leading with it.

The right order is:

1. stabilize the agent API contract
2. prove the decision/planning semantics
3. add job-state resources
4. add MCP as a thin wrapper

That way the MCP surface wraps something stable instead of freezing unstable orchestration behavior too early.

## Deliberately Deferred

These are still planned rather than implemented:

- event streams for active jobs
- agent-native upload/publish flows
- MCP server implementation
- true provider-managed worker provisioning rather than externally started workers

## Next Logical Step

Once cloud execution becomes a true provider-managed orchestration flow, the next major agent milestone should be:

- event/state streaming
- stronger control semantics for active jobs
- an MCP server that wraps this API cleanly
