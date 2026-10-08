# Hugging Face credentials on Runner

Settings offers a password input for a Hugging Face personal access token,
verified directly against HTTPS Hugging Face without following redirects. The
token is stored under a separate OS credential-store entry; it never goes to
InferGrade Hub, a profile file, native response, or log. Native save/clear share
a generation fence so a late sign-in cannot undo removal. Browser input clears
before invocation and save/remove returns focus to the section heading.

Environment credentials retain precedence. The native listener injects a saved
token only when no existing HF environment credential is present. An unavailable
or invalid optional HF store does not block public/cached models; it emits a
sanitized warning. Settings reports credential-store errors explicitly. Changes
take effect at the next listener start; existing jobs retain their environment.

Python additionally reads a bounded regular personal-access-token file from
HF_TOKEN_PATH, HF_HOME/token, or the documented XDG/default Hugging Face home.
It does not modify that file. Removing Runner's saved token does not sign out
the CLI or unset an inherited environment token. Gated models still require
accepting their license and granting access on Hugging Face.

Artifact downloads, sibling lookup and readiness probes share a redirect policy:
only exact HTTPS huggingface.co:443 keeps Authorization; public HTTPS CDNs
receive no credential, and HTTPS downgrades are rejected. Curl fallbacks disable
user configuration first and retain HTTPS-only redirects without location-trusted.
The supervisor also redacts HF token-shaped output from child-resolved login files.

References: [HF environment variables](https://huggingface.co/docs/huggingface_hub/package_reference/environment_variables),
[HF access tokens](https://huggingface.co/docs/hub/security-tokens),
[curl redirect/header behavior](https://curl.se/docs/manpage.html).

## Validation and delivery boundary

Worktree `.worktrees/redesign-runner-hf-credentials`, branch
`codex/redesign-runner-hf-credentials`, based on main e1a42a0.
Code 7f650c5, redirect fix fde3450, optional-store/curl fix 3e7ea86.

- Clean full Runner suite: 1177 Python tests and tier/product audits passed;
  `/tmp/infergrade-redesign-hf-full-candidate.log`.
- Desktop: 66 Node tests/build passed; `/tmp/infergrade-redesign-hf-web-candidate.log`.
- Native: 51 tests passed, two opt-in protocol tests ignored; Clippy passed.
  `/tmp/infergrade-redesign-hf-rust-candidate.log`,
  `/tmp/infergrade-redesign-hf-clippy-candidate.log`.
- Focused artifact39/doctor19 tests cover login-file precedence/bounds/FIFO,
  origin restrictions, CDN/alternate-port/lookalike redirect stripping, same-origin
  compatibility, downgrade rejection and curl configuration suppression.
- Four final browser captures1060×760/375px, light/dark inspected; no overflow.
  Keyboard submission clears synthetic input before invocation, save/remove focus
  and status passed with a labeled in-memory test adapter, removed by reloading.
- Independent review approved after redirect and optional-store corrections.

An initial mocked download test unexpectedly read the developer's login file and
included its credential in assertion output. The user was notified to revoke and
replace it. Mocked artifact/readiness tests now isolate credential-file paths;
shared engineer guidance records this requirement. No credential value is recorded
here. No real credential was intentionally entered for acceptance, and no OS-store
or native Mac GUI acceptance is claimed: the desktop remains locked. No release tag.
