# Schemas

This directory is the language-neutral source of truth for InferGrade data contracts.

The most important modeling decision in this directory is that InferGrade treats quantized models as an ontology, not a flat label. We explicitly distinguish:

- model family
- checkpoint
- quantization
- artifact
- runtime binding
- benchmark subject

That separation is what lets InferGrade make claims like "this artifact on this backend is comparable to that artifact on that backend" without collapsing lineage, packaging, and execution into one ambiguous model name.

The second important contract is that run requests can now be self-contained. In addition to `run.*`, a request may specify:

- `artifacts.quantized_weights`
- `runtime.backend_image`
- `runtime.artifact_cache_dir`

That lets a server-issued run config carry enough information for the runner to fetch, verify, cache, and execute a benchmark without asking the operator to pre-stage files manually.

## Goals

- keep runner, API, and web aligned without forcing one language everywhere
- make validation rules portable
- support future code generation into Python and TypeScript

## Initial Contents

- `json/run_request.schema.json`
- `json/run_config.schema.json`
- `json/manifest.schema.json`
- `json/model_ontology.schema.json`
- `json/result_record.schema.json`
- `examples/`
