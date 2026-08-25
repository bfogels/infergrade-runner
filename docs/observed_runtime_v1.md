# Observed Runtime v1

`observed_runtime_v1` is the Runner-owned contract for benchmarking a model that
is already running behind a local OpenAI-compatible HTTP endpoint. It is an
observed contribution lane, not a replacement for the managed/native llama.cpp
path or the verified runtime receipt.

The adapter probes only loopback endpoints. Discovery is bounded to the default
local ports for Ollama, LM Studio, llama-server, vLLM, and TGI. Explicit
endpoints must use `http` or `https` and resolve to `localhost`, `127.0.0.0/8`,
or `::1`; redirects, userinfo, queries, fragments, and non-loopback hosts are
rejected. Requests have bounded timeouts and response sizes.

The receipt records the network scope and port, the provider compatibility hint
used for the probe, and model IDs reported by the endpoint. The provider field
is a compatibility hint, not a verified runtime identity. It never records an
endpoint URL, credential, local filesystem path, or generated text. A reported model ID
does not establish its artifact publisher, quantization, checksum, runtime
build, or runtime byte identity; those fields remain unknown/null and the
receipt is permanently ineligible for verified promotion.

The seam supports the OpenAI `/v1/models` and `/v1/chat/completions` shapes,
including JSON and bounded server-sent-event (SSE) completions. Ollama's local
`/api/tags` response and TGI's `/info` response are accepted only as bounded
discovery metadata; generation still uses the generic OpenAI-compatible chat
endpoint.

## Integration boundary

Construct `infergrade.adapters.openai_compatible.OpenAICompatibleAdapter`
explicitly with a loopback endpoint. Do not register it as `llama.cpp` and do
not feed its receipt into the verified `runtime_receipt_v1` path. The next
integration step is for Runner orchestration to add an opt-in observed request
mode, invoke `preflight_model`, pass generated text through the existing
benchmark/scoring path, and persist this receipt beside the result with an
observed evidence label.
