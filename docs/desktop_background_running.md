# Desktop background running

The Settings background toggle is opt-in and saved only on this machine. A real Tauri tray must be created before closing can hide the window. Show Runner reopens it; Quit Runner and OS exit requests are refused while the listener, local check, runtime installation, starter download or upload still has native work ownership. An idle close atomically fences new work before destroying the window. A failed tray or preference write leaves the honest unavailable/error state visible.

Stop listening confirms interruption, sends SIGINT to the Unix sidecar that execs Python, or stops the Windows sidecar process tree (including its existing kill-on-close job). Native supervision and exit admission remain held until the requested PID terminates. Stop fences restart, retains handles on failure, waits at most 30 seconds and reports an unconfirmed stop rather than quitting. PID-tagged events cannot clear a newer listener. Disconnect honors canceled Stop. Capability server startup now cleans up on KeyboardInterrupt as well as ordinary exceptions.

## Validation and boundaries

Independent lifecycle review approved the final atomic idle-close and PID stop fences. Both committed full-suite candidates passed 1204 Python tests plus tier/product audits. The final code candidate was740b5d9; its clean run is recorded in /tmp/infergrade-redesign-background-full-final.log. Focused adapter tests passed82, including real long-lived subprocess interruption during server startup and active suite. Native55 tests pass, with two opt-in HTTP tests ignored; Clippy passes. Desktop68 tests and build pass.

Four final Settings screenshots at1060/375 px, light/dark, were inspected with no overflow and a21px section heading. Browser keyboard navigation passed. A separate, labeled, browser-only adapter checked Space-to-enable, failed-write checkbox rollback and blocked-exit heading focus, then was removed by reload. It did not create a tray, alter OS preferences or execute a model.

Actual native Mac tray/show/hide, OS Quit and stop acceptance remain unverified because the Mac is locked. Linux/Windows compile and packaging smoke remain CI gates. CI caught an interruption-test dependency on a host-installed server; the test now explicitly supplies its native server path. The optional Ubuntu24.04 managed-runtime smoke independently failed when first-run returned no eval tokens; that runtime acceptance is not claimed. No release tag or installed app update is implied. Open at login, notifications, GPU preferences and managed cache retention remain separate redesign slices.

Uses the [Tauri native tray API](https://v2.tauri.app/learn/system-tray/) and existing shell supervision. Linux desktop tray availability depends on the running desktop environment; initialization failure disables hiding rather than making an inaccessible background app.
