# Runner Recovery

This page is the short map for recovering a local InferGrade run without leaking pairing codes, runner tokens, signed URLs, or raw model output.

## Pairing And Token Recovery

Use the Hub pairing flow to create a fresh code, then redeem it through stdin or the environment so the code does not land in shell history:

```bash
printf '%s' "$INFERGRADE_PAIR_CODE" | infergrade pair --api-url https://infergrade.com --pair-code-stdin --label agent-dogfood-host
```

The legacy `--pair-code <value>` form still works for compatibility, but it prints a warning because the value can appear in shell history or process listings.

If the saved runner profile is stale, revoked, or bound to the wrong Hub account, remove it and re-pair:

```bash
infergrade unpair
infergrade pair --api-url https://infergrade.com --pair-code-stdin --label agent-dogfood-host
```

The Desktop app stores the paired runner token in the platform token store. If token storage is denied or stale, use the app's reset/unpair flow or run `infergrade unpair`, then pair again with a fresh Hub code.

## Runtime Recovery

Inspect the current managed `llama.cpp` runtime plan without changing the machine:

```bash
infergrade install-runtime --runtime llama.cpp --list
infergrade install-runtime --runtime llama.cpp
```

Select known-good local binaries explicitly:

```bash
infergrade install-runtime --runtime llama.cpp --select-existing \
  --llama-cpp-cli-path /path/to/llama-cli \
  --llama-cpp-server-path /path/to/llama-server
```

Install the managed runtime only after reviewing the plan:

```bash
infergrade install-runtime --runtime llama.cpp --execute
```

The Desktop app exposes the same recovery model with explicit actions:

- Inspect runtime plan.
- Install or retry the recommended runtime.
- Replace selection with managed runtime.
- Remove selected runtime.
- Select an existing `llama.cpp` binary.

Removing a selected runtime clears InferGrade's selection record. It does not delete user-owned local binaries. Managed runtime files may be removed only when the Desktop action is explicitly run with managed-file removal.

## Artifact And Upload Recovery

When a native first-run completes locally but upload fails, keep the local run directory. Do not edit bundle ids or run ids by hand.

Retry upload from a saved bundle:

```bash
infergrade upload-bundle runs/example/bundle.json --api-url https://infergrade.com
```

For Hub-backed run jobs, prefer restarting the paired listener so it can retry from its persisted state:

```bash
infergrade start
```

The Desktop app provides two local first-run support actions:

- Copy artifact path.
- Retry upload from persisted local artifacts.

The current app copies artifact paths instead of opening Finder directly. That keeps the app from widening file-system permissions while still giving support a precise local path.

## Support Export

Create a secret-free support export after pairing, runtime, execution, or upload failures:

```bash
infergrade export-support --run-dir runs/example --output runs/example/support_export.json
```

Without `--output`, the same command prints JSON to stdout:

```bash
infergrade export-support --run-dir runs/example
```

Review the export before sharing. It should include runner shape, runtime/environment status, progress, validation, file-presence checks, and artifact receipts while redacting tokens, pair codes, signed URLs, and raw prompt/model-output fields.

## Help Discovery

The default CLI help shows the common workflow:

```bash
infergrade --help
```

Advanced recovery commands are discoverable with:

```bash
infergrade --all --help
infergrade export-support --help
infergrade upload-bundle --help
infergrade install-runtime --help
```
