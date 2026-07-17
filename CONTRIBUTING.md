# Contributing

InferGrade is meant to be useful, inspectable, and easy to extend. This guide defines the baseline style we use across the repo so new contributions feel consistent instead of stitched together.

## Public Contribution Policy

Issues and pull requests are welcome when they keep the Runner trustworthy, reproducible, and easy to inspect.

- Use issues for reproducible bugs, documentation gaps, benchmark methodology questions, and focused feature proposals.
- Do not include tokens, `.env` files, private model credentials, Apple signing materials, certificates, private keys, or private run artifacts in issues, PRs, screenshots, logs, or uploaded bundles.
- Report suspected vulnerabilities privately through the process in [SECURITY.md](SECURITY.md).
- Keep PRs focused. Separate unrelated benchmark, packaging, workflow, and documentation changes unless a maintainer asks for a combined patch.
- PRs that change execution behavior should include tests or a clear smoke path. PRs that change user-facing workflows should update the nearest README or doc.
- Public release, signing, notarization, and package-publishing changes require maintainer review and must not weaken the protected release workflow.
- PRs that add vendored code, benchmark fixtures, datasets, or generated third-party assets must update [docs/third_party_license_audit.md](docs/third_party_license_audit.md).

## Core Principles

- Prefer clarity over cleverness.
- Keep user-facing workflows obvious and explicit.
- Treat reproducibility and provenance as first-class concerns.
- Document the "why" when behavior is not immediately obvious from the code.
- Keep comments lightweight. Good names and small functions should do most of the work.

## Repo Style

- Python uses 4-space indentation.
- Web assets, JSON, YAML, and Markdown use 2-space indentation.
- Files should end with a trailing newline.
- New files should stay ASCII unless the file already uses Unicode or there is a clear need.

The repo ships with [`.editorconfig`](.editorconfig) so editors can pick these defaults up automatically.

## Python Conventions

- Add a module docstring to modules that define core behavior, public helpers, or service entrypoints.
- Add docstrings to public functions, non-trivial private helpers, and methods with side effects.
- Keep docstrings short and practical:
  - first line explains what the function does
  - optional second paragraph explains important constraints or side effects
- Prefer type hints on public interfaces and data-heavy helpers.
- Use inline comments sparingly, mainly for non-obvious control flow or benchmarking caveats.

Example:

```python
def resolve_quant_artifact(request: RunRequest) -> Optional[ResolvedArtifact]:
    """Resolve and optionally download the quantized artifact for a run request."""
```

## JavaScript Conventions

These apply to the Desktop Runner web assets under `apps/desktop-runner/`.

- Prefer small helpers with descriptive names over deeply nested callbacks.
- Add JSDoc comments to important stateful, rendering, or API-related functions.
- Keep DOM-building helpers deterministic where possible.
- Keep user-facing copy in sentence case unless a domain term is conventionally titled.

Example:

```js
/**
 * Refresh all dashboard surfaces that depend on API data.
 */
async function refreshAll() {
  // ...
}
```

## Documentation Conventions

- Start with what the component does, then explain why it exists.
- Be honest about current limitations.
- Favor runnable examples over abstract descriptions.
- When introducing a new workflow, update the closest README in the same pass.

## Open-Source Maintainability Checklist

When adding a new feature, try to cover these in the same PR:

- implementation
- tests or at least a smoke verification path
- docstrings or comments for the non-obvious parts
- README or docs updates for changed workflows

This is not about maximizing process. It is about keeping InferGrade welcoming for the next contributor who did not live inside the original implementation context.

## Testing

Run the full local Python verification pass with:

```bash
./scripts/test_all.sh
```

That script runs the runner-core unit and integration-style tests with stdlib `unittest` (the repo intentionally does not use pytest). CI also lints Python with `ruff check python scripts`; the rule set lives in [`ruff.toml`](ruff.toml).

For the Rust workspace, run the same checks CI enforces:

```bash
cargo fmt --all -- --check
cargo test --workspace --exclude infergrade_desktop_runner --locked
./scripts/build_desktop_sidecar.sh
cargo clippy --workspace --all-targets --locked -- -D warnings
```
