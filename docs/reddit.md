# InferGrade Reddit Draft

This is an internal hype draft for now, not a public-ready launch post.

## Title

InferGrade is live: an open-source benchmark runner for figuring out which quantized LLM setup is actually worth deploying

## Body

Hi all, I’ve been building **InferGrade**, a new open-source project for benchmarking and comparing **quantized LLM deployments** in a way that is actually useful for operators, tinkerers, and the broader open-source community.

The core problem I kept running into was this:

We have tons of model releases, tons of quants, tons of backend options, and endless benchmark screenshots, but it is still weirdly hard to answer practical questions like:

- What is the best model I can run on 24 GB of VRAM?
- Which quant is actually worth the quality tradeoff?
- Is `llama.cpp` or `vLLM` better for this workload?
- What is the fastest setup that still clears a reasonable capability floor?
- How much did this benchmark actually cost to run?

So InferGrade is meant to be a more honest and more reproducible answer to that.

## What InferGrade does

- generates **portable run configs** that can be executed locally or in the cloud
- runs models through containerized backends like `llama.cpp` and eventually `vLLM`
- captures real deployment metrics like:
  - TTFT
  - decode speed
  - latency
  - VRAM usage
  - load time
  - benchmark runtime cost
- stores full benchmark bundles with provenance and validation metadata
- keeps a catalog of past results so people can compare runs over time
- helps users find the right model via **constraint-based recommendations** and **Pareto frontiers**

The bigger idea is that this is not just “another leaderboard.”

It is supposed to become a shared open standard for answering:

**“What should I actually deploy on my hardware, for my use case, with my constraints?”**

## Why I think this matters

A lot of benchmark culture right now is still too vague, too easy to game, or too far removed from real deployment decisions.

InferGrade is trying to push in the other direction:

- artifact-aware
- backend-aware
- cost-aware
- reproducible
- community-submittable
- useful for real deployment choices instead of just flex charts

One concept I’m especially excited about is treating this as an **ontology of quantized models**:

- model family
- checkpoint
- quantization recipe
- artifact file
- runtime binding
- benchmark subject

That may sound nerdy, but I think it matters a lot if we want comparisons to be honest instead of collapsing everything into “same model lol.”

## The long-term vision

I want this to evolve into something like:

- the easiest way to generate trustworthy benchmark bundles
- a public results catalog for quantized model deployments
- a decision engine that helps people choose the best setup for coding, assistant tasks, local inference, and more
- a tool that can eventually run seamlessly on local hardware or paid cloud runners with minimal friction

Basically:

**Consumer Reports for quantized open-source LLM deployment, but built in a way that stays community-updatable.**

## If this sounds interesting

I’d love feedback on any of the following:

- what benchmark signals you trust most
- what deployment metrics are most decision-relevant to you
- what you would want from a hosted results browser
- what would make you actually contribute runs
- what would make you trust recommendations from a project like this

If there’s interest, I’m happy to share more of the architecture, schema, and runner design as it takes shape.

I’m very excited about this one. I think open-source AI needs better deployment truth, not just more model releases.

## Shorter Version

Built **InferGrade** to help answer:

“What quantized LLM should I actually run on my hardware?”

It’s an open-source benchmarking and results system focused on:

- real deployment metrics
- reproducible run bundles
- backend/container-aware execution
- cost capture
- and recommendation views based on real constraints, not just one leaderboard score

Still early, but I think this could become genuinely useful for the open-source community.
