# InferGrade Runner 0.3.16

Runner 0.3.16 declares an Apple Silicon coverage priority for the already reviewed Qwen3-8B Q4_K_M artifact and corrects GGUF quant identity for filenames that begin with model-family names such as Qwen. Hosted scheduling still requires the matching Hub contract pin and deployment.

## Included

- add a Qwen3-8B Q4_K_M assistant coverage priority for deployment, chat-memory, and same-family quant-fidelity evidence;
- parse compound GGUF quant schemes such as `Q4_K_M` without mistaking `Qwen` or `Qwen2.5` for the quantization scheme;
- preserve explicit ontology hints as authoritative;
- keep cross-family claims limited to speed, memory, and task-scoped assistant evidence; perplexity remains same-family only;
- publish Runner contract 0.3.12 for downstream Hub pinning.

## Evidence boundary

This release makes a reviewed setup eligible for measurement. It does not claim that Qwen3 is faster, more capable, or a better fit until real runs are completed and published under the existing evidence rules.
