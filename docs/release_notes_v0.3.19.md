# InferGrade Runner 0.3.19

Runner 0.3.19 makes Qwen3.5 direct-answer capability checks use llama-server's structured chat protocol on the local Apple Silicon lane. The change follows the first measured Qwen3.5 run, where the legacy completion protocol exhausted every task budget inside an unfinished thinking block even though deployment inference succeeded.

## Included

- apply the explicit `enable_thinking=false` chat-template policy to Qwen3.5 capability tasks;
- preserve task-level TTFT, decode speed, input/output tokens, load time, and prompt-transform provenance;
- support both chat-shaped assistant fixtures and plain reasoning or coding prompts;
- retain the existing Qwen3 and non-direct generation paths unchanged;
- keep Runner contract 0.3.14 because the result schema and Hub request contract are unchanged.

## Evidence boundary

The release proves that the corrected protocol can produce visible, scorable Qwen3.5 answers on the reviewed artifact. It does not claim a capability score or comparative advantage until a fresh benchmark bundle completes under Runner 0.3.19.
