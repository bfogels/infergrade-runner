# Task timing observations v1

Contract 0.3.40 adds bounded item observations to capability task performance in result records and summaries. These observations contain a hashed benchmark/case identity, exact fixture-case content digest, status, timing source, elapsed milliseconds, output token count and termination/recovery flags. They contain no prompts, answers, logs or original case IDs.

Only `request_elapsed` establishes HTTP submission through completed response handling on the managed llama.cpp server path. Compute and parsed timings remain distinguishable and must not be substituted on the prompt-to-completion chart. Downloads, loading, queue wait and scoring are outside this interval. Multi-turn and other paths without an explicit source remain unqualified.

Every attempted row is included, including failures and missing timing. Payloads are capped at 10,000 observations; `item_observations_complete=false` prevents truncated sets from claiming complete coverage. Consumers must check count consistency and version, pool individual qualifying observations rather than summary medians, and partition by the exact benchmark/task mix, task revision digests and execution setup. Failures, token-limited attempts, unknown termination and protocol recovery must be counted and excluded from a natural-completion timing statistic. A recovered request only measures its final HTTP attempt, not the entire task.

Legacy timing summaries and their aggregation labels are preserved for compatibility. Older bundles have no item observations; their pooled task timing remains missing. This contract addition is source promotion, not a desktop release or cross-platform acceptance receipt.

Contract0.3.41 adds nullable placement invocation/fingerprint references to the
same v1 observations and a bounded table of Runner-owned invocation receipts.
See runtime_placement_artifacts.md. A timing reference binds only its own
invocation, including server restarts. Missing, invalid or truncated binding
must remain unknown; neither requested context nor another task's placement
can qualify that observation.
