# Desktop redesign shell

First slice of runner-claude.html: Home, Models, Activity and Settings with the
approved sidebar, green theme and compact content hierarchy. Existing native
controls move as the same DOM nodes, retaining their handlers and state.

Home contains readiness, listening and the current assignment; first launch has
an explicit connect action. Models contains the existing managed cache and native
starter check. Activity mirrors actual assignment text and contains listener logs.
Settings retains paste-code pairing, observed endpoint intake, managed/pinned/
custom runtime controls, self-test, updates and support. Pairing deep links,
logs and readiness failures navigate to the relevant page.

This is not the complete desktop redesign. Local model discovery, per-file cache
retention, richer history, browser-first native pairing, machine preferences and
native Mac/two-machine acceptance remain subsequent slices. No prototype model,
score, fit, throughput or history numbers are introduced.

Browser development shell at1060x760 and375x760 light/dark: all four pages had no
horizontal overflow; navigation Enter focuses the active rendered heading.
Sixteen captures in output/playwright inspected; mobile grid spacing and cache
heading adjusted. Assignment mirror updates while Home is hidden; repeated
paired=true state notifications preserve the current Settings page. Paired Home
focus skips the hidden welcome heading. These are UI regressions, not actual
benchmark execution or native app acceptance. Final sixteen captures were inspected after these fixes. Full Runner suite
passed: 1,170 tests and tier audit, /tmp/infergrade-redesign-runner-desktop-full.log.
Desktop npm check passed 54 tests and production build; independent review
approved the repaired slice.

The worktree starts at maine2ab6ad and preserves develop248e338, including
CI efficiency PR649 and best-effort cleanup PR651. No release tag or version
bump is included in this slice.
