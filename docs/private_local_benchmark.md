# Private local GGUF benchmarks

`infergrade benchmark-local` scores a file already on this machine through the
ordinary Runner native execution and scorer pipeline. It requires installed
llama.cpp CLI/server binaries; it never downloads a model or pairs with Hub.
It has no upload, API credential, remote request document, or simulation option.

```
infergrade benchmark-local \
  --model-file /absolute/path/model.gguf \
  --llama-cpp-cli-path /absolute/path/llama-cli \
  --llama-cpp-server-path /absolute/path/llama-server \
  --use-case general_assistant --tier canary
```

Use cases are `general_assistant`, `agentic_coding`, and `reasoning`. `canary`
is the default, and `standard` deliberately expands the sample. This is a
selected native check inventory, not a promise of a complete use-case profile:

- Assistant: IFEval, compositional instructions, and diagnostic chat memory.
- Coding: static repair. Executable EvalPlus checks require their existing
  container lane and are absent from this private native inventory.
- Reasoning: exact answers. The MMLU reference component is absent.

Every inventory includes the existing interactive-chat deployment check, with
one warmup and three measurements. Runner's existing score policy retains
missing coverage and determines whether a headline score is ready. A canary
is thin local evidence; it does not qualify public chart publication or support
promotion. No replacement score or comparison-point receipt is invented here.

The model is SHA-256 verified and identified as `local/sha256-<digest>`, without
claiming a publisher, checkpoint revision, or Hub catalog match. The ordinary
pipeline locks the exact runtime, checks the model, records timing and scorer
provenance, and validates its local result bundle. Assistant checks require the
reviewed offline native IFEval package installed by Runner packaging.

Results stay under the selected Runner config directory in
`private-runs/private_<id>/bundle/`, including the usual report, progress,
capability evidence and validation. A sibling closed `receipt.json` records
running/completed/failed state and `uploaded: false`. Failed validation and
interruptions never produce a completed receipt. On Unix, new private directories
are mode 0700 and files mode 0600. Existing linked or shared private storage is
refused. A user-selected model symlink may resolve to its regular local target;
models, runtimes and unrelated user data are never deleted or modified.

This PR supplies the CLI execution foundation. Desktop selection, progress,
private history and local report opening are separate acceptance gates.
