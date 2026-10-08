# Desktop local model discovery

The Models page now scans existing LM Studio, Hugging Face and Ollama locations,
including explicit HF_HUB_CACHE, HF_HOME and OLLAMA_MODELS overrides. A native
folder picker adds up to sixteen custom folders, persisted separately from the
Runner profile. Stop scanning removes a location from discovery, preserving its
files. Paths remain local and are not uploaded.

Discovery reads four-byte GGUF headers, including extensionless blobs. It does
not infer exact artifact identity, publisher, quantization, compatibility or fit
from names. Files are read-only. The existing local engine check can select a
discovered file; execution checks its regular-file type and GGUF header again.
This diagnostic does not create a comparable chart point.

Scans cap depth at eight, entries at 20,000 and returned files at 500. Directory
symlinks are never traversed; file symlinks must resolve inside the selected
root. Canonical files and directories are deduplicated. Partial or unreadable
scans are reported. Unix nonblocking file open and handle metadata validation
reject raced FIFOs without waiting for a writer.

## Delivery evidence

Worktree: `.worktrees/redesign-runner-model-discovery`, branch
`codex/redesign-runner-model-discovery`, based on main09842c7 (browser pairing).
Code6feddc7 plus filesystem safeguard04d03b4.

- `./scripts/test_all.sh`: 1174 Python tests and tier/product audits pass;
  `/tmp/infergrade-redesign-discovery-full-candidate.log`.
- Desktop: 61 Node tests and Vite build pass;
  `/tmp/infergrade-redesign-discovery-web-rebased.log`.
- Native: 47 Rust tests pass, one opt-in actual pairing test ignored;
  `/tmp/infergrade-redesign-discovery-rust-rebased.log`.
- Clippy all-targets with warnings denied passes;
  `/tmp/infergrade-redesign-discovery-clippy-rebased.log`.
- Independent review approved after extensionless-path, focus and FIFO fixes.
- Browser preview: 1060×760 and375px, light/dark, no overflow; Models Enter
  focuses heading, folder action honestly requires native app. Four captures
  inspected. Four additional browser-only QA layout captures exercise disclosure,
  extensionless selection callback and Stop scanning focus restoration. These
  injected rows are labeled QA, cleared by reload and never persisted/uploaded.

Earlier uncommitted full-suite runs failed only repository cleanliness checks;
final committed candidate passed. No native Mac GUI/folder-picker acceptance,
release tag, model execution or installed-app upgrade is claimed. The Mac remains
locked. Cache retention/pinning, complete Activity, OS preferences and remaining
prototype capabilities continue in separate slices.
