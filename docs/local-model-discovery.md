# Local models from Hugging Face and vLLM

`infergrade models list` scans the standard Hugging Face cache (also used by vLLM), LM Studio folders and Ollama blobs. It respects `HF_HUB_CACHE`, `HF_HOME` and `OLLAMA_MODELS`. For a custom vLLM download directory, add `--folder /path/to/models`. `--json` returns local inventory without uploading paths or files to Hub.

The Desktop Models screen also lists detected Safetensors checkpoints. These are local observations, not verified benchmark artifacts. The hosted Benchmark catalog does not receive this local inventory or automatically substitute local files for requested Hub artifacts.

- **GGUF detected:** header found. Architecture, exact identity and memory fit still need verification.
- **Check compatibility:** checkpoint found; converter support is unverified. Quantized AWQ/GPTQ checkpoints remain in this state.
- **Incomplete checkpoint:** missing Safetensors shards or tokenizer files.
- **Ready to convert:** complete files and architecture support confirmed by an explicitly selected local llama.cpp converter. This does not prove conversion or loading will succeed.

## Explicit conversion on Ubuntu

Use a trusted local llama.cpp source checkout and install that checkout's converter requirements into the Python environment running InferGrade. The converter is not bundled with the managed inference binaries. The check runs the selected local script with `--print-supported-models`; it never imports model repository code.

```bash
infergrade models list --converter /path/to/llama.cpp/convert_hf_to_gguf.py
infergrade models convert \
  --folder /path/to/checkpoint \
  --converter /path/to/llama.cpp/convert_hf_to_gguf.py \
  --output /path/to/converted/model-f16.gguf
```

Choose an output directory outside the source checkpoint. Existing outputs are never replaced. The default output is F16; optional `--outtype bf16` or `--outtype f32` selects another unquantized output. RAM and disk use can be much larger than a Q4 GGUF. Conversion runs locally with Hugging Face/Transformers offline settings and preserves source files. It hashes the complete source manifest before and after conversion and records the converter entry-script hash, output hash and requested output type in `<output>.conversion.json`. This is a local conversion receipt, not a verified upstream artifact identity or complete runtime-build attestation.

A failed conversion or changed source publishes no output. Successful conversion still needs a llama.cpp load check and a real benchmark. Use the resulting local GGUF through the existing private local benchmark workflow; conversion alone does not publish a Compare point.

Scans are bounded to 20,000 entries, 500 models and eight directory levels. File links must resolve within the selected model root; Hugging Face snapshot links to cache blobs are supported. Directory links are not traversed. Scans report partial results when limits or unreadable locations prevent completion.
