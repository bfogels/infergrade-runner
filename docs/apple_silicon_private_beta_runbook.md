# Apple Silicon Private-Beta Runbook

This runbook is the golden path for an early Apple Silicon user or maintainer validating the full InferGrade loop:

1. choose a setup in Hub;
2. pair Runner with Hub;
3. run local native evidence on the Mac;
4. upload the bundle;
5. open the Hub Result;
6. decide which benchmark to run next.

This path is for private beta. It does not claim broad Windows/Linux support, gold-lane status, public leaderboard status, or stronger quality claims beyond the captured evidence.

## Scope

Use this runbook when the goal is realistic Apple Silicon local `llama.cpp` evidence. The native path is intentional because Docker Desktop does not exercise Metal performance.

Start with one small setup before trying reference lanes:

- public GGUF: TinyLlama Q4_K_M or another known-good small artifact;
- backend: `llama.cpp`;
- execution mode: `local_native`;
- first selected checks: `interactive_chat_v1`, `multiturn_chat_memory_v1`, `coding_static_repair_v1`, `reasoning_exact_answer_v1`;
- optional follow-up checks: `mmlu_pro_reference_v1`, `evalplus_humaneval`, `evalplus_mbpp`, `perplexity_reference_v1`.

Keep reference checks intentionally selected. They are not quick/default first-run checks.

## Secret Handling

Never commit, paste, screenshot, or log:

- production pairing codes;
- Hub runner tokens;
- upload tokens;
- Hub authorization tokens;
- cookies;
- signed URLs;
- local command transcripts containing any of the above.

Use the real pairing code only at execution time. Prompt for it so it is not written into shell history:

```bash
read -rsp 'InferGrade pairing code: ' INFERGRADE_PAIR_CODE
printf '\n'
printf '%s\n' "$INFERGRADE_PAIR_CODE" | infergrade pair \
  --api-url 'https://api.infergrade.com' \
  --pair-code-stdin \
  --label 'founder-primary'
unset INFERGRADE_PAIR_CODE
```

If the code is expired or already redeemed, request a fresh code out of band. Do not write the failed code into a doc, PR, issue, or artifact.

## 1. Install Runtime Prerequisites

```bash
brew install llama.cpp
python3 --version
infergrade --help
```

If `infergrade` is not installed as a command yet, run from a checkout:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade --help
```

## 2. Pair Runner

Pair once against production Hub:

```bash
read -rsp 'InferGrade pairing code: ' INFERGRADE_PAIR_CODE
printf '\n'
printf '%s\n' "$INFERGRADE_PAIR_CODE" | infergrade pair \
  --api-url 'https://api.infergrade.com' \
  --pair-code-stdin \
  --label 'founder-primary'
unset INFERGRADE_PAIR_CODE
```

Expected success:

- Runner saves a local paired profile;
- the raw token is not printed into browser-visible state;
- later `infergrade start` and `infergrade run-job` can use the saved profile.

If pairing fails:

- `pair_code_not_found`: confirm the code was copied exactly, then request a new code if needed;
- `pair_code_expired`: request a new code;
- `pair_code_redeemed`: request a new code;
- network/TLS failure: verify the API URL and connectivity, then retry.

## 3. Start The Local Listener

Start the paired native listener:

```bash
infergrade start --execution-mode local_native
```

Checkout fallback:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade start --execution-mode local_native
```

Expected Hub state:

- runner is paired;
- runner heartbeat becomes fresh;
- execution mode is `local_native`;
- Hub can hand off local jobs to this machine.

If the listener cannot start:

- run `infergrade doctor --execution-mode local_native` for dependency checks;
- confirm `llama-cli` or `llama-server` is available from the Homebrew `llama.cpp` install;
- confirm the artifact cache and run output parent directories are writable;
- restart the listener after fixing dependencies.

## 4. Queue A Small Hub Run

In Hub:

1. open Recommend or Build;
2. choose a local-friendly GGUF setup;
3. select the quick local evidence checks first;
4. queue the run for the paired Apple Silicon runner.

The first beta run should prefer thin local samples plus deployment evidence. Do not start with HumanEval+, MBPP+, MMLU-Pro, or quant fidelity until the small run completes and uploads.

## 5. Execute And Upload

If the listener is running, Runner should claim the Hub job, execute locally, and upload automatically.

Manual fallback for one specific Hub run:

```bash
infergrade run-job \
  --run-id '<RUN_ID_FROM_HUB>' \
  --execution-mode local_native
```

Checkout fallback:

```bash
PYTHONPATH=python/runner-core/src python3 -m infergrade run-job \
  --run-id '<RUN_ID_FROM_HUB>' \
  --execution-mode local_native
```

Expected local bundle artifacts:

- `manifest.json`;
- `summary.json`;
- `validation.json`;
- `progress.json`;
- `report.md`;
- `artifacts/receipts/artifact_resolution.json`;
- `artifacts/capability/capability_summary.json` when capability checks ran;
- `artifacts/capability/<benchmark_id>/capability_run.json` for Runner-owned capability checks.

Expected Hub result:

- uploaded bundle accepted;
- Result page opens without exposing tokens;
- deployment fitness is separate from assistant/coding/reasoning capability;
- thin local samples remain labeled as thin local samples;
- failed or partial lanes remain visible.

## 6. Recover Upload Failures

If local execution succeeds but upload fails:

1. preserve the local run directory;
2. confirm the paired runner profile still exists;
3. confirm the Hub run still exists and is owned by the paired user;
4. retry from the same local artifacts instead of rerunning the benchmark when possible.

Manual upload fallback:

```bash
infergrade upload-bundle '<LOCAL_RUN_DIR>' \
  --api-url 'https://api.infergrade.com'
```

`upload-bundle` uploads the bundle identity preserved in the local artifact. If Hub rejects the upload because the original run is missing or no longer owned by the paired user, keep the local bundle and support export rather than editing the run id into the command.

If upload still fails, create a secret-free support export:

```bash
infergrade export-support \
  --run-dir '<LOCAL_RUN_DIR>' \
  --output '<LOCAL_RUN_DIR>/support_export.json'
```

Review the support export before sharing. It should describe runtime status, pairing status, first-run status, upload status, safe recent errors, and artifact paths without tokens.

## 7. Read The Hub Result

In Hub Result, verify:

- deployment fitness is smoke evidence, not capability quality;
- assistant/coding/reasoning thin samples are separate surfaces;
- MMLU-Pro, HumanEval+, MBPP+, and quant fidelity appear as reference evidence only when intentionally selected;
- quant fidelity says same-family/protocol comparability only;
- no global score is created from the surfaces;
- next benchmark action is specific and cautious.

Good next actions:

- run a missing thin local sample;
- retry or inspect a failed/partial lane;
- run MMLU-Pro sampled reference after thin reasoning works;
- run HumanEval+ or MBPP+ after static coding evidence works;
- run quant fidelity before choosing between nearby same-family quants;
- repeat a run to improve confidence.

Avoid next actions that imply:

- global-best model choice;
- gold-lane status;
- public leaderboard readiness;
- broad coding or reasoning proof from thin samples.

## 8. Private-Beta Exit Criteria

A beta operator can call the path successful when:

- pairing works without exposing credentials;
- the native listener receives a Hub job;
- a local GGUF run completes on Apple Silicon;
- local artifacts are preserved;
- upload succeeds or the local-only fallback is clearly documented;
- Hub Result shows the evidence surfaces and next benchmark action;
- recovery steps are clear for pairing, runtime, local execution, and upload failures.

If any step fails, preserve the exact failure class and local artifacts. A truthful failed run is more useful than a hand-edited success story.
