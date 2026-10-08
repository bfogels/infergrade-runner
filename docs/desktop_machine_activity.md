# Desktop machine Activity

Activity now reads the paired Runner’s recent Hub jobs, including queued,
running, paused, completed, failed and cancelled work. The native request uses
its saved profile API and OS token; the token is never passed to the renderer.
The Hub must explicitly identify a machine-scoped response. Native projection
keeps a bounded set of job IDs, model labels, timestamps, stages, actual progress,
visibility and error codes; it excludes raw payloads, credentials and model output.
Profile/API/token checks fence late responses after connection changes.

The interface separates Now, Up next, Needs attention and Finished. Zero progress
is preserved. Completion does not invent publication, scores or accepted results.
View job opens the paired Hub’s Runs page. Existing current-assignment controls,
logs and retry capabilities remain. History refreshes every15 seconds only while
Activity is visible; refresh preserves focused job actions. Disconnect/profile
switch clears rows and generation-fences outstanding requests.

History is the most recent100 machine-associated Hub jobs. It is not an unlimited
local execution archive; standalone diagnostic checks remain separate. Older
unscoped Hub servers fail closed rather than showing another machine’s jobs.

## Validation and delivery boundary

Worktree `.worktrees/redesign-runner-activity`, branch
`codex/redesign-runner-activity`, based on maine2c7b99 (discovery).
Code24b20aa, disconnected refreshbfb83bd and test-directory safeguard0484210.

- Full Runner suite:1174 Python tests plus tier/product audits passed;
  `/tmp/infergrade-redesign-activity-full-final.log`.
- Desktop:65 Node tests/build passed;
  `/tmp/infergrade-redesign-activity-web-candidate.log`.
- Native:49 tests passed,two opt-in HTTP tests ignored; Clippy passed;
  `/tmp/infergrade-redesign-activity-rust-candidate.log` and
  `/tmp/infergrade-redesign-activity-clippy-candidate.log`.
- Actual opt-in native HTTP Activity test passed against isolated Hub8055,
  using a protected protocol profile and no OS-store mutations. Two actual
  pinned jobs were queued; only the selected Runner’s running job was returned,
  preserving actual zero progress. No model was loaded or benchmark executed.
  `/tmp/infergrade-redesign-activity-native-protocol-final.log`.
- Four browser preview and four replayed actual native HTTP projection captures
  at1060×760/375px, light/dark, inspected without overflow. Enter navigation,
  polling action focus, saved-Hub link and disconnected clearing passed. The
  replay route was removed and page reloaded; no result fixtures were persisted.
- Independent review approved after paused-state, result wording and paired-Hub
  destination corrections.

A discovery persistence test failed once with a missing temporary file in the
parallel native suite. Temporary test directories now include an atomic ordinal
alongside process/time; final native suite passed. Initial dirty full-suite runs
failed repository-cleanliness checks; final committed candidate passed.

Native Mac GUI/OS keyring acceptance remains blocked by the locked desktop.
No release tag, installed-app upgrade, real benchmark or Compare point is claimed.
The Hub machine-activity endpoint must deploy before this surface can load jobs.
