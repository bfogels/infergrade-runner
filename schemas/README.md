# Schemas

This directory is the language-neutral source of truth for InferGrade data contracts.

Within the overall product, this Runner repo is the authoritative publisher of:

- the ontology
- the run-request and run-config schemas
- the bundle and result schemas
- the example payloads that demonstrate the contract

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
- give InferGrade Hub a versioned contract bundle to consume instead of independently redefining schemas

## Initial Contents

- `json/run_request.schema.json`
- `json/run_config.schema.json`
- `json/manifest.schema.json`
- `json/model_ontology.schema.json`
- `json/result_record.schema.json`
- `examples/`

## Published Contract Bundle

Runner can export a versioned contract bundle with:

```bash
python3 -m pip install -e ./python/runner-core
python ./scripts/export_contract_bundle.py
```

That produces a versioned bundle under `dist/contracts/` containing the contract manifest, schemas, examples, and selected supporting docs.
