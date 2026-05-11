# Codex v0.2.18 Sprint Planning

## Current Branch State

- Runner `origin/main`: v0.2.17 quant-fidelity reference release.
- Runner `origin/develop`: one post-release sync commit ahead of `main`, same version.
- Runner open PRs at sprint start: none observed.
- Working branch: `codex/runner-dogfood-evidence`.
- Worktree: `/Users/brianfogelson/Desktop/Code/infergrade/.worktrees/runner-dogfood-evidence`.
- Hub note: Hub `main` is ahead of Hub `develop` by recent v3 work. This slice starts in Runner and does not touch Hub.

## Release Goal

Generate and preserve real local dogfood evidence without adding benchmark scope.

Target user promise:

> A maintainer can select a small Apple Silicon GGUF matrix, generate reproducible Runner request files, run thin local samples plus selected reference lanes, preserve exact provenance, and upload token-free bundles to Hub when pairing is available.

## Planned PRs

- Dogfood planning PR: add a local evidence dogfood runbook, request-plan generator, and tests that keep pairing codes, tokens, model weights, and generated bundles out of committed artifacts.
- Release PR: promote reviewed dogfood tooling/docs from `develop` to `main` and bump version only in the release branch.

## Implementation Notes

- Do not add GPQA, LiveCodeBench, SWE-bench, adaptive head-to-head testing, public leaderboard mechanics, or new benchmark lanes.
- Keep MMLU-Pro, HumanEval+, MBPP+, and quant-fidelity intentionally selected and out of quick/default first-run paths.
- Dogfood evidence should be labeled as real local evidence or dogfood evidence, not official validation.
- Reference evidence remains reference evidence, not gold evidence.
- Thin local samples remain thin local samples.
- Generated request files, dogfood manifests, command sheets, and bundles live under ignored `runs/` by default.

## Reviewer Checklist

- The dogfood planner does not accept or write pairing codes, runner tokens, bearer tokens, upload tokens, or cookies.
- The planner does not commit model weights or generated bundle artifacts.
- Generated lane requests keep thin local samples, MMLU-Pro reference, HumanEval+ reference, MBPP+ reference, and quant fidelity distinguishable.
- Upload commands are token-free and rely on existing paired profile/env-token behavior.
- Docs do not call dogfood official validation, gold evidence, leaderboard-grade evidence, global intelligence proof, LiveCodeBench proof, SWE-bench proof, or repo-edit proof.
- Quant-fidelity wording keeps same-family comparability boundaries explicit.

## Validation Plan

```bash
PYTHONPATH=python/runner-core/src python3 -m unittest python/runner-core/tests/test_local_evidence_dogfood.py
python3 scripts/plan_local_evidence_dogfood.py --init-matrix /tmp/infergrade-dogfood-matrix.json
python3 scripts/plan_local_evidence_dogfood.py --matrix-file /tmp/infergrade-dogfood-matrix.json --output-root /tmp/infergrade-dogfood-plan --skip-sha256
python3 -m unittest discover python/runner-core/tests
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 -m json.tool schemas/json/capability_summary.schema.json >/tmp/capability_summary.schema.json.check
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
git diff --check
gitleaks detect --source=. --redact --no-banner --exit-code 1
```

## Validation Evidence

- Focused dogfood planner tests passed:

```bash
PYTHONPATH=python/runner-core/src python3 -m unittest python/runner-core/tests/test_local_evidence_dogfood.py
```

- Planner smoke passed:

```bash
python3 scripts/plan_local_evidence_dogfood.py --init-matrix /tmp/infergrade-dogfood-matrix.json
python3 scripts/plan_local_evidence_dogfood.py --matrix-file /tmp/infergrade-dogfood-matrix.json --output-root /tmp/infergrade-dogfood-plan --skip-sha256
```

- Real local dogfood smoke completed on Apple Silicon using TinyLlama Q4_K_M through `local_native` llama.cpp:
  - Bundle id: `qb_20260511_232633_b321c98c`.
  - Runner version: `0.2.17`.
  - Artifact: `tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf`.
  - Artifact SHA256: `9fecc3b3cd76bba89d504f29b616eedf7da85b96540e490ca5824d3f7d2776a0`.
  - Artifact source: downloaded from the configured Hugging Face GGUF source into the local artifact cache.
  - Hardware slice: Apple M1 Pro, 16 GB unified memory, Metal-capable native path.
  - Selected checks: `interactive_chat_v1`, `multiturn_chat_memory_v1`, `coding_static_repair_v1`, `reasoning_exact_answer_v1`.
  - Bundle validation: valid; Runner bundle verification field: `verified`; simulated: false. This is local bundle provenance status, not official validation.
  - Deployment: completed; TTFT p50 `63.83 ms`; latency p50 `1603.42 ms`; decode p50 `103.97 tokens/s`; load time `419.35 ms`.
  - Assistant thin sample: scored, 5/5, score `1.0`.
  - Coding thin sample: partial, 3 completed generations, static score `0.0`; next action recommends retry/inspect coding lane.
  - Reasoning thin sample: scored, 3/3, exact-answer score `0.0`.
  - Quant fidelity: not yet benchmarked in this smoke.
  - No Hub upload was attempted because no production pairing code was available in this thread.
- Targeted Runner regression suite passed:

```bash
PYTHONPATH=python/runner-core/src python3 -m unittest python/runner-core/tests/test_capability_summary.py python/runner-core/tests/test_runner.py python/runner-core/tests/test_local_evidence_dogfood.py
```

- JSON and diff hygiene passed:

```bash
python3 -m json.tool schemas/capability_catalog.json >/tmp/capability_catalog.json.check
python3 -m json.tool schemas/json/capability_run.schema.json >/tmp/capability_run.schema.json.check
python3 -m json.tool schemas/json/capability_summary.schema.json >/tmp/capability_summary.schema.json.check
git diff --check
```

- Version checks passed:

```bash
python3 ./scripts/sync_versions.py --check
python3 ./scripts/check_versions.py
```

- Secret scan passed:

```bash
gitleaks detect --source=. --redact --no-banner --exit-code 1
```

- Full runner-core discovery passed after committing the feature branch, which gave the public-release readiness tests a clean worktree:

```bash
python3 -m unittest discover python/runner-core/tests
```

## Reviewer Findings

- P2: Source-URI fallback initially paired a remote `source_uri` with the missing local-path filename. Fixed by deriving the request filename from the selected artifact URI when the local GGUF does not exist.
- P3: Template placeholder revision could be emitted as artifact provenance. Fixed by using `null` in the template and stripping placeholder values from generated provenance.
- P3: Dogfood smoke wording said `verification level: verified` without enough caveat. Fixed by naming it the Runner bundle verification field and stating it is not official validation.

## Evidence Honesty Notes

- Dogfood evidence is product proof and calibration data. It is not official validation.
- A single local machine does not create leaderboard-grade or gold evidence.
- A thin local sample does not become reference evidence because it scored well.
- MMLU-Pro sampled reference, EvalPlus HumanEval+/MBPP+ executable references, and quant-fidelity reference evidence must stay visibly separate in artifacts, summary, docs, and Hub display.

## Release Criteria

- A maintainer can generate local dogfood request files from a small GGUF matrix.
- The generated plan captures model family, checkpoint, GGUF filename/path, quant scheme, source URI/revision when known, artifact SHA when available, selected lanes, claim boundaries, and output paths.
- Dogfood docs explain how to regenerate local evidence and upload bundles safely if pairing is available.
- No secrets, huge artifacts, or raw benchmark outputs are committed.
- Tests cover planner output, lane distinction, token-free command generation, and catalog check-id validity.

## Current Blockers

- The first local dogfood smoke succeeded after downloading TinyLlama into the artifact cache because no local GGUFs were found in the usual cache/model/download paths.
- Docker is installed but the daemon is not running, so MMLU-Pro, HumanEval+, and MBPP+ reference-lane dogfood could not be executed yet.
- Upload proof depends on production pairing availability and Hub acceptance of the generated bundles.

## Next Actions

- Open feature PR to `develop` and spawn reviewer before merge.
- If reviewed and merged, promote a coherent v0.2.18 release from `develop` to `main`.
- After release, continue with Hub populated evidence proof path using this dogfood payload shape.
- When Docker is running and a pairing code is available, run selected reference lanes and upload at least one token-free Hub result.
