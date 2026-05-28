# Local Evidence Dogfood

InferGrade needs real local evidence before adding more benchmark lanes. This runbook describes the maintainer path for generating Apple Silicon dogfood bundles from known local GGUFs without committing weights, secrets, raw benchmark outputs, or huge artifacts.

Dogfood evidence is useful product proof. It is not official validation, gold evidence, leaderboard-grade evidence, or a global model-quality claim.

## Scope

Run a small matrix deeply instead of a broad model sweep.

Recommended slots:

- small/fast local sanity model
- strong general 7B/8B model
- coding-leaning model
- one same-family quant ladder where practical: `Q8_0` or highest practical reference quant, `Q5_K_M`, `Q4_K_M`, and optionally `Q4_0`

Selected evidence lanes:

- deployment plus thin local samples: `interactive_chat_v1`, `multiturn_chat_memory_v1`, `coding_static_repair_v1`, `reasoning_exact_answer_v1`
- sampled reasoning reference: `mmlu_pro_reference_v1`
- executable coding reference: `evalplus_humaneval`
- executable coding breadth reference: `evalplus_mbpp`
- same-family quant-fidelity reference: `perplexity_reference_v1`

Keep all reference checks intentionally selected. They are not part of the quick/default first-run path.

## Safety Rules

Do not commit:

- GGUF files or model weights
- generated dogfood bundles
- raw benchmark outputs
- production pairing codes
- Hub runner tokens, upload tokens, bearer tokens, or cookies
- local-only command logs containing credentials
- large artifacts under `runs/`

It is acceptable to commit:

- this runbook
- dogfood planning scripts
- sanitized example metadata shapes
- token-free public Hub result URLs only after explicit approval

## Generate A Local Matrix

Create a local matrix template under ignored `runs/`:

```bash
python3 scripts/plan_local_evidence_dogfood.py \
  --init-matrix runs/local_evidence_dogfood/matrix.local.json
```

Edit the local matrix so each model entry has:

- `slot`
- `model_family`
- `checkpoint`
- absolute `gguf_path` when the GGUF already exists locally
- `quantization_scheme`
- `source_uri` and `source_revision` when known
- `include_lanes` for the lanes that should run for that artifact

When `gguf_path` does not exist yet and `source_uri` is an `hf://` or HTTPS artifact reference, the generated request uses `source_uri` so Runner can download into its artifact cache. The completed bundle's `artifacts/receipts/artifact_resolution.json` is then the source of truth for the resolved local path, size, and SHA.

Then generate request files and command sheets:

```bash
python3 scripts/plan_local_evidence_dogfood.py \
  --matrix-file runs/local_evidence_dogfood/matrix.local.json
```

The planner writes:

- `dogfood_manifest.json`
- `requests/**.json`
- `commands.sh`
- `upload_commands.sh`

The default output root is `runs/local_evidence_dogfood/`, which is ignored by git.

## Execute Local Runs

Inspect the generated command sheet first:

```bash
sed -n '1,220p' runs/local_evidence_dogfood/<matrix-id>/commands.sh
```

Run a small lane first:

```bash
bash runs/local_evidence_dogfood/<matrix-id>/commands.sh
```

If a lane fails or is too slow, preserve the bundle and record the failure class. Do not rewrite dogfood into success.

Expected useful artifacts per bundle:

- `manifest.json`
- `summary.json`
- `report.md`
- `progress.json`
- `artifacts/capability/capability_summary.json` when capability evidence ran
- `artifacts/capability/<benchmark_id>/capability_run.json` where the lane emits Runner-owned capability evidence
- raw outputs and scoring outputs beside each benchmark artifact

## Upload To Hub

If a production pairing code is provided out of band, pair once:

```bash
read -rsp 'InferGrade pairing code: ' INFERGRADE_PAIR_CODE
printf '\n'
printf '%s\n' "$INFERGRADE_PAIR_CODE" | \
infergrade pair \
  --api-url 'https://api.infergrade.com' \
  --pair-code-stdin \
  --label "agent-dogfood-$(hostname -s)"
unset INFERGRADE_PAIR_CODE
```

Never write the real pairing code into this file, the matrix, shell history, issue comments, PR bodies, or screenshots.

After local bundles exist, upload with a token-free command sheet:

```bash
export INFERGRADE_API_URL='https://api.infergrade.com'
bash runs/local_evidence_dogfood/<matrix-id>/upload_commands.sh
```

If upload fails, keep the local artifacts and record the failure class. Local artifact-only dogfood is still useful.

## Evidence Labels

Use these labels in notes and Hub-visible copy:

- real local evidence
- dogfood evidence
- exact machine
- Apple Silicon
- thin local sample
- sampled reference
- executable coding reference
- quant-fidelity reference
- same-family comparability only
- needs confirmation
- failed
- partial

Avoid:

- globally best
- proven intelligence
- leaderboard-grade
- gold evidence
- official validation
- decision-grade

## Review Checklist

Before using a dogfood bundle as product evidence, verify:

- `capability_run.json` validates for every emitted capability run
- `capability_summary.json` indexes assistant, coding, reasoning, and quant-fidelity surfaces separately
- HumanEval+ and MBPP+ remain separate artifacts
- MMLU-Pro appears as sampled reference evidence, not gold
- quant fidelity has a same-family comparability key
- malformed output, generation failure, valid wrong answer, scoring failure, timeout, and container failure remain distinct where the lane can observe them
- `report.md` and uploaded Hub payloads contain no runner token, bearer token, upload token, pairing code, or local secret

## Current Known Limits

- Observed duration, token volume, memory behavior, and failure rates still need real runs across the selected matrix.
- Reference samples are intentionally selected and may take materially longer than thin local samples.
- Quant-fidelity evidence is not a general capability score and should only compare runs with matching family/checkpoint/tokenizer/corpus/protocol boundaries.
- Dogfood evidence should not outrank or impersonate maintainer-reviewed official evidence.
