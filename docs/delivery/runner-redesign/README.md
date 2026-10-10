# Runner desktop redesign — develop review

The desktop shell now renders four pages from UI snapshots instead of moving legacy panels. Home leads with the machine state and next action; Models combines discovered and downloaded files; Activity groups queue/history; Settings uses grouped rows with saved-state controls. The sidebar owns pause. Empty preflight stays out of Home; an attempted offline check retains its result and recovery controls. Light, dark and system themes use the Claude prototype's tokens.

This is a frontend change based on Runner 0.3.70, commit `9b39145`, targeting **develop only**. No Rust source, Tauri command registration, command permissions, backend, contract, version, tag or release changes. The Tauri configuration changes only the minimum window size to 1000×700. No merge or promotion is authorized.

[Open the before / after / mockup gallery](comparison.html). The nine comparison PNGs below use the actual browser-rendered application with synthetic Tauri responses. They prove presentation and UI state handling; they do not prove OS settings, real pairing, GPU execution, uploads, publication or physical benchmark results. The prototype's numbers are illustrative too.

| State | Side-by-side receipt |
|---|---|
| First launch | [Compare](comparison-first-launch.png) |
| Ready | [Compare](comparison-ready.png) |
| Running | [Compare](comparison-running.png) |
| Finished | [Compare](comparison-finished.png) |
| Failed | [Compare](comparison-failed.png) |
| Offline | [Compare](comparison-offline.png) |
| Low disk | [Compare](comparison-low-disk.png) |
| Needs Hugging Face token | [Compare](comparison-needs-hf-token.png) |
| Paired idle | [Compare](comparison-paired-idle.png) |

## Capability paths

This maps every shipped capability in `REVIEW-runner-round-1.md` §1, plus the existing newer desktop controls. Click counts mean navigation/disclosure clicks to **reach** the control, not executing it or confirming a destructive action. Every listed control is reachable within two such clicks from Home. Failure-specific recovery buttons appear only with the corresponding real state.

| Capability | Path | Clicks |
|---|---|---:|
| Browser pairing / reconnect | Settings → Connect in browser | 1 |
| Pasted code / alternate Hub address | Settings → Use a pasted code | 2 |
| Guided Make ready | Home → Make ready when setup is needed; otherwise Settings → Advanced → Make ready | 0–2 |
| Start / stop listening / disconnect | Settings → Account | 1 |
| Pause new work without stopping current work | Sidebar → Pause new jobs | 0 |
| First local check without an account | Home → Check a model offline → Quick engine check | 1 |
| Download starter or use local GGUF | Models → Check a model offline → Quick engine check | 2 |
| Private benchmark, use case and depth | Models → Check a model offline | 2 |
| Stop/check private work | Home → Private benchmark card | 0 |
| Private reports and partial-coverage detail | Activity → Private on this machine | 1 |
| Local OpenAI-compatible endpoint check | Models → Check a model offline → Local model endpoint; also Settings → Advanced → Check local endpoint; existing Hub handoff still required | 2 |
| Combined discovered/downloaded library, paging, source, quant, size and last used | Models → Model library | 1 |
| Keep/delete/clear unkept downloads | Models → Model library | 1 |
| Add/remove discovered model folder; external-file ownership and safetensors guidance | Models → Model library / Folder list / File details | 1–2 |
| Storage meter / download cap / confirmed trimming | Models → Storage | 1 |
| Managed default, exact managed build, catalog build, custom binary | Settings → Advanced → Runtime | 2 |
| Inspect runtime plan / remove selected runtime | Settings → Advanced → Runtime | 2 |
| Startup self-test | Settings → Advanced → Run self-test | 2 |
| Live logs / clear / copy | Activity → Live Runner logs | 2 |
| Per-job details and Hub log handoff | Activity → Run details & logs | 2 |
| Redacted support summary export | Settings → Advanced → Copy support summary | 2 |
| Update check / verified install / relaunch | Settings → Advanced → Updates | 2 |
| System / Light / Dark | Settings → General → Theme | 1 |
| Exact Hub job/result handoff and resumed work | Home current run / recent result; Activity job/result | 0–1 |
| Upload retry without rerunning; local artifact path; check again / another model | Home current local result recovery actions | 0 |
| GPU default / GPU 0 / GPU 1 / both; >2 GPU manual subset | Settings → This machine → GPUs | 1 |
| Queue / running / failed / completed history and scoped accepted results | Activity → Queue & history | 1 |
| Open at login / background behavior / finish notifications | Settings → General | 1 |
| Machine name | Settings → This machine | 1 |
| Hugging Face token status / add / remove | Settings → Hugging Face → Add a token | 1–2 |

The single offline-use-case control uses **Chat & reasoning / Coding / Reasoning**. Existing quick-engine and endpoint checks keep their original fixed contracts; selecting a private use case does not silently alter either check's meaning. External models remain read-only; deletion confirmations and download-budget safeguards remain in place. Credentials never enter render snapshots; a pasted token is cleared before the native save request.

## Validation and evidence boundaries

- `npm run check`: all 116 desktop JavaScript tests pass, including render tests for every page and private/token views; production Vite build passes.
- Full stdlib suite: see `test-results.json` after validation from a clean commit. Static acceptance checks now inspect rendered page templates rather than deleted legacy HTML.
- [Browser receipts](browser-receipts.json): nine Home states, all four pages in light/dark, and expanded Advanced/offline controls report zero WCAG 2 A/AA or 2.1 AA violations; no console errors/page errors in the recorded fixture flows.
- Keyboard exercises Space on autosaving switches and Keep, Tab/blur on machine-name save, Enter on disclosures, pause/resume and use-case segments. Polling preserves the focused run's identity, its handler, open disclosures and draft text. Private work/failure route to their own current panel and completion clears the failure state.
- System follows operating-system light/dark changes; reduced motion disables animation. [Accessibility tree](accessibility-tree.txt) records named controls, navigation, headings and saved states. Status announcements exclude the ticking elapsed clock. **Native VoiceOver/NVDA testing remains outstanding**; computer use reported a locked Mac and automatic unlock failed. The user has been asked to unlock it. These are browser semantic and automated accessibility checks.
- At 1000×700, common page content heights are Home 700px, Models 883px, Activity 700px and Settings 974px (1.39 screens maximum); no horizontal overflow. Expanded diagnostic/check panels and long histories may be taller.
- Independent source review found no remaining actionable findings after correcting recovery visibility, execution-source routing, terminal-state flags, catalog hydration and polling reconciliation.

Two requested data fields cannot be supplied faithfully by the unchanged backends: the existing readiness response exposes hardware class but no RAM/model-fit estimate; the native activity projection omits use case for historical jobs. Home says fit is checked before benchmarking, and Activity says “Use case unavailable” when it is absent. Library quant/last-used fields similarly show unavailable when native data does not provide them; managed last-used timestamps use the backend’s Unix-second format. No hardware capacity or completed score is invented.

The screenshots use fixed synthetic numbers only within the test harness. Acceptance of real account/OS actions, native screen readers and physical execution is separate from this develop PR.

## Reproduce the UI receipts

Start the changed desktop frontend on `127.0.0.1:1420`, the archived baseline on `1422`, and the shared prototype folder on `4189`. Run `capture-before.cjs`, `capture-after.cjs`, `check-reconciliation.cjs`, `check-private.cjs`, `check-browser.cjs`, `check-system.cjs`, `check-pause-recovery.cjs`, `check-endpoint-shortcut.cjs`, `check-idle-home.cjs` and `capture-mockup.cjs` with the Playwright CLI `run-code --filename` command in that order. The scripts use a fake Tauri bridge and a temporary axe-core install; they do not modify accounts or native preferences. The capture output paths are explicit to this workspace. The gallery contains the original, unedited screenshots.
