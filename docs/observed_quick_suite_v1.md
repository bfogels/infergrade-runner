# Observed quick suite v1

`infergrade discover-runtimes` safely probes the five standard loopback ports
and prints only redacted receipts. `infergrade --all observe-runtime` runs an
immutable 5, 20, or 40-case
reasoning content prefix against an already-running loopback
OpenAI-compatible server. It is a low-friction local diagnostic, not a normal
verified InferGrade run.

The command accepts an explicit loopback endpoint, or a provider whose standard
port Runner can derive locally. It supports compatibility hints for Ollama, LM
Studio, llama-server, vLLM, and TGI. A server with one
reported model is selected implicitly. For an ambiguous server, pass a model
ID in memory with `--model-id` or use `--model-id-stdin` when the ID contains a
private local path. Receipts may retain a model label only when it passes the
public-label filter; local paths and unsafe IDs are withheld.

Before spending the selected suite, Runner sends a tiny terminal-format
canary. A failed canary stops the run. The first transport failure also stops
remaining work and records the completed, failed, and not-attempted buckets
separately.

Endpoint discovery uses a short bounded timeout. Generation has a separate
bounded timeout (300 seconds by default) because local CPU and memory-constrained
inference can legitimately take much longer than a health probe.

The result intentionally excludes the endpoint URL and port, credentials, raw
or unsafe model IDs, prompts, generated text, artifact identity, publisher,
quantization, runtime build identity, and runtime bytes. It retains only the
locked selection identity, strict per-case pass/fail diagnostics, aggregate
denominators, and `observed_runtime_v1` receipt.

A score-inert diagnostic may extract one signed integer from an otherwise
strictly invalid terminal marker line. It records only the integer and stable
classification, never an output excerpt. This separates likely format-only
failures from substantive wrong answers without changing strict scores.

Observed scores use `observed_quick_generation_v1`, which requests temperature
zero and disables thinking only where the provider exposes a reviewed request
control. Runner appends a versioned strict terminal-line directive but retains
neither the prompt nor completion. The directive suppresses visible reasoning
so the generic transport does not depend on provider-specific output grammars.
This policy is not the Reasoning v2
qualification policy. Results are
informational-only, non-comparable, and ineligible for promotion,
recommendations, or headline capability claims.
