# Native macOS test receipt

The local test bundle uses the existing acceptance keyring namespace and a temporary Runner config directory. No real account is paired, no model files are changed, and no OS startup/notification preference is changed. Rust/backend source and Tauri commands are unchanged.

- Native build: optimized `.app`, version 0.3.70, current cache recovery frontend changes.
- Launch from the Desktop worktree caused Python initialization to block in directory access. The same bundle copied to `/tmp` loads readiness, managed downloads, storage budget, GPU preference and private history successfully. This isolates the earlier failures to the test launch environment; it is not a claim about deployment or physical execution.
- Native Tab/Return navigation reached Models and focused the Home primary action. Home/Models control roles and labels were observed in the macOS accessibility tree.
- Activity and Settings render visually, but later native accessibility snapshots omit their page body. Earlier snapshots of the preceding source build exposed these bodies. This inconsistency remains unresolved; these files do not establish a native screen-reader pass.
- VoiceOver was enabled. Its copy-last-spoken-phrase command returned no text through computer use; audible verification has been requested. Automated browser axe/keyboard evidence is separate.

Native screenshots show real local inventory and unpaired state. The nine scenario comparisons elsewhere use synthetic Tauri responses.
