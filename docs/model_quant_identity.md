# Model quant and artifact-source identity

Runner model ontology version `model_quant_identity_v1` separates three concepts that must not be collapsed:

- the upstream model publisher and checkpoint, such as `Qwen/Qwen3-27B`;
- the logical, format-qualified quantization, such as `gguf:q4_k_m` or `safetensors:int4`;
- the quantized artifact source, such as publisher `PearsonKyle` or `RedHatAI` on Hugging Face.

The upstream publisher remains `model_family.publisher`. The quant publisher belongs under `artifact.source`; cloud and runtime providers are separate metadata.

## Quant canonicalization

`quant_v1` preserves the raw label and emits a canonical scheme and format-qualified `quantization_id`. It case-folds and normalizes separator aliases only where the mapping is lossless. For example, `Q4KM`, `Q4_K_M`, `q_4_k_m`, `q4-k-m`, and `q4.k.m` resolve to `gguf:q4_k_m` for GGUF artifacts.

Generic `Q4`, `Q4_0`, and `Q4_K_M` remain different. `INT4` remains different from GGUF `Q4` and is qualified by format, so `awq:int4`, `gptq:int4`, and `safetensors:int4` do not merge. Unknown labels remain unknown. A recognized explicit scheme that conflicts with a recognized artifact label, or an explicit format that conflicts with an unambiguous artifact format, has `canonicalization_status: conflict` and no canonical ID.

Consumers should compare `quantization_id`, not raw labels. They may retain raw-label filters for legacy records, but must not guess identities for ambiguous data.

## Artifact publisher and source

Run requests may provide `artifacts.quantized_weights.source` with provider, repository, publisher, publisher ID, and revision. Runner also derives Hugging Face source coordinates from unambiguous `hf://` and `huggingface.co` references. A two-segment repository reference is accepted only as a direct vLLM model reference; artifact paths require an explicit source or Hugging Face URI. Runner never infers a quant publisher from the upstream model publisher or from a local path.

`artifact_source_id` binds normalized source provider, repository, publisher identity, and revision. Display casing is preserved, while source identity is case-stable for Hugging Face. Artifact SHA remains content identity; identical bytes from two publishers retain two source identities and provenance records.

Publisher-aware recommendation or comparison variants should use the canonical quant ID plus `artifact.source.publisher_id`. Exact deployable repeats should retain the source-aware artifact identity. Unknown legacy publishers must remain artifact-specific rather than merging into a shared "unknown publisher" variant.

## Compatibility

All new schema fields are additive. Existing contract bundles remain readable. Old records without canonical or source identity must remain explicit legacy/unknown data until their artifact URI or repository makes a lossless derivation possible.
