# Native macOS test receipt

The local test bundle uses the existing acceptance keyring namespace and a temporary Runner config directory. No real account is paired, no model files are changed, and no OS startup/notification preference is changed. Rust/backend source and Tauri commands are unchanged.

- Native build: optimized `.app`, version 0.3.70, current cache recovery frontend changes.
- Launch from the Desktop worktree caused Python initialization to block in directory access. The same bundle copied to `/tmp` loads readiness, managed downloads, storage budget, GPU preference and private history successfully. This isolates the earlier failures to the test launch environment; it is not a claim about deployment or physical execution.
- Native Tab/Return navigation reached Models and focused the Home primary action. Home/Models control roles and labels were observed in the macOS accessibility tree.
- Activity and Settings render visually, but later native accessibility snapshots omit their page body. Earlier snapshots of the preceding source build exposed these bodies. This automation inconsistency remains unresolved; the snapshots alone do not establish an audible screen-reader pass.
- VoiceOver was enabled. Its copy-last-spoken-phrase command returned no text through computer use. The user confirmed: “Yes, labels and roles are announced clearly”. This verifies focused-control announcements on the shown page. The user was unsure about the additional Models/Activity/Settings check. The broader native screen-reader pass remains unverified; no failure is asserted from this uncertainty. Automated browser axe/keyboard evidence is separate.

Native screenshots show real local inventory and unpaired state. The nine scenario comparisons elsewhere use synthetic Tauri responses.

All source CI checks passed on `546860017e4cca084ad373c2d58f03e258120bb0`, including Python/desktop tests, Rust on all three platforms, Linux/Windows install-launch smoke, CodeQL and security checks.

Cleanup: VoiceOver was restored to its original off state, the idle review build was closed, and the installed Runner was reopened.
