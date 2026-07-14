# InferGrade Runner 0.3.18

Runner 0.3.18 adds a reviewed Qwen3.5-9B Q4_K_M assistant evidence priority after exact artifact verification and a successful local llama.cpp compatibility canary on Apple Silicon. It reuses the Runner-owned deterministic direct-answer policy so fixed-budget assistant checks measure scorable answers rather than unfinished thinking blocks.

## Included

- add Qwen3.5-9B Q4_K_M to the Apple Silicon assistant coverage priorities;
- require `deterministic_direct_answer_v1` for the Qwen3.5 assistant baseline;
- keep assistant capability, speed, memory, task-time, and output-length evidence tied to the same reviewed setup;
- publish Runner contract 0.3.14 for downstream Hub pinning.

## Evidence boundary

The release proves only catalog eligibility and runtime compatibility. It does not claim that Qwen3.5 passes assistant checks or outperforms Qwen3 or Qwen2.5. Those claims require a fresh measured bundle, and perplexity remains comparable only within the same model family and pinned protocol.
