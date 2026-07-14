# InferGrade Runner 0.3.17

Runner 0.3.17 makes the Qwen3 assistant coverage priority executable with the Runner's existing deterministic direct-answer policy. The contract now declares that policy explicitly so downstream schedulers can disable Qwen3 thinking for fixed-budget assistant benchmarks instead of exhausting the answer budget inside an unfinished thinking block.

## Included

- declare `deterministic_direct_answer_v1` on the reviewed Qwen3-8B Q4_K_M assistant priority;
- validate coverage-priority generation presets against Runner-supported policies;
- preserve both the default deterministic policy and the Qwen3 direct-answer policy as valid contract values;
- publish Runner contract 0.3.13 for downstream Hub pinning.

## Evidence boundary

This release corrects benchmark execution policy; it does not claim that Qwen3 passes assistant checks or outperforms another setup. A fresh measured run is still required, and any earlier run that exhausted its token budget inside an unfinished thinking block remains valid failure evidence for the policy it actually used.
