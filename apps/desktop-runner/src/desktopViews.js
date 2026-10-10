// Pages own their markup; command controllers hydrate stable controls in named slots.
import { assignmentProgressStage } from "./desktopHelpers.js";
// Strings from the machine or Hub must pass through escapeHtml.
export const escapeHtml = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const slot = (state, key) =>
  state.components?.[key]?.render(state.components[key].state) || "";
const button = (attribute, label, extra = "") =>
  `<button type="button" ${attribute} ${extra}>${label}</button>`;
export function homePresentation(state = {}) {
  if (state.running || state.privateRunning)
    return {
      title: "Running",
      sentence: "This machine is working on your benchmark.",
      action: "View current run",
      target: "run",
    };
  if (state.authFailure)
    return {
      title: "Needs attention",
      sentence: "Reconnect this machine to continue.",
      action: "Reconnect in browser",
      target: "connect",
    };
  if (state.lowDisk)
    return {
      title: "Needs attention",
      sentence:
        "Disk space is low; clear unkept downloads before the next benchmark.",
      action: "Manage model storage",
      target: "models",
    };
  if (state.needsHf)
    return {
      title: "Needs attention",
      sentence: "This model needs a Hugging Face token before it can download.",
      action: "Add Hugging Face token",
      target: "token",
    };
  if (state.offline)
    return {
      title: "Needs attention",
      sentence:
        "Hub is offline; local checks and saved results are still available.",
      action: "Check connection",
      target: "ready",
    };
  if (state.admissionError)
    return {
      title: "Needs attention",
      sentence: "Could not confirm whether new benchmarks are paused.",
      action: "Check pause setting",
      target: "pause-retry",
    };
  if (state.paused)
    return {
      title: "Paused",
      sentence: "Current work can finish; new benchmarks will wait.",
      action: "Resume new benchmarks",
      target: "resume",
    };
  if (state.failed || state.privateFailed || state.authFailure)
    return {
      title: "Needs attention",
      sentence: state.authFailure
        ? "Reconnect this machine to continue."
        : "This machine needs help before continuing.",
      action: state.authFailure
        ? "Reconnect in browser"
        : state.hasRun || state.privateFailed
          ? "Review current run"
          : "Review settings",
      target: state.authFailure
        ? "connect"
        : state.hasRun || state.privateFailed
          ? "run"
          : "settings",
    };
  if (!state.paired)
    return {
      title: "Connect this machine",
      sentence:
        "Approve this machine in your browser to receive benchmarks from Hub.",
      action: "Connect in browser",
      target: "connect",
    };
  if (!state.runtimeAvailable)
    return {
      title: "Needs attention",
      sentence: "Set up the local runtime to run benchmarks on this machine.",
      action: "Make ready",
      target: "ready",
    };
  if (!state.verified)
    return {
      title: "Needs attention",
      sentence: "Check the connection before receiving your next benchmark.",
      action: "Check connection",
      target: "ready",
    };
  return {
    title: "Ready",
    sentence: state.listening
      ? "Choose a benchmark in Hub; this machine will take it from here."
      : "This machine is connected; start listening when you’re ready.",
    action: state.listening ? "Choose a benchmark in Hub" : "Start listening",
    target: state.listening ? "hub" : "listen",
  };
}
export function renderHome(state = {}) {
  const hero = homePresentation(state);
  return `<header class="hero"><div class="mark" data-ready-mark data-state="${hero.title.toLowerCase().replaceAll(" ", "-")}" aria-hidden="true">${statusIcon(hero)}</div><div><p class="eyebrow">This machine</p><h1 tabindex="-1" data-primary-state-title>${hero.title}</h1><p class="sub" data-primary-state-message role="status">${hero.sentence}</p><div class="actions">${button("data-home-primary", hero.action, 'class="primary" data-action="' + hero.target + '"')}${button("data-open-check", "Check a model offline", 'class="ghost"')}</div></div></header>
 <section class="assignment-panel card" data-assignment-panel data-state="${escapeHtml(state.assignment?.state || "idle")}" aria-label="Current run" ${!state.assignment || state.assignment.state === "idle" ? "hidden" : ""}>
 <p class="eyebrow" data-assignment-kicker>Current run</p><h2 tabindex="-1" data-assignment-title>${escapeHtml(state.assignment?.title || "No current run")}</h2><p class="sub" data-assignment-description>${escapeHtml(state.assignment?.description)}</p>
 <div data-assignment-progress-wrap ${state.assignment ? "" : "hidden"}><div class="progress-meta"><span data-assignment-phase role="status">${escapeHtml(state.assignment?.phase)}</span><span data-assignment-time>${escapeHtml(state.assignment?.time)}</span></div><div class="progress-bar" aria-hidden="true"><span data-assignment-progress-bar style="width:${Math.max(0, Math.min(100, Number(state.assignment?.progress) || 0))}%"></span></div><ol class="assignment-stages" aria-label="Benchmark stages">${[
   ["download", "Download"],
   ["verify", "Check"],
   ["load", "Load"],
   ["benchmark", "Benchmark"],
   ["publish", "Upload"],
   ["complete", "Complete"],
 ]
   .map(
     ([id, label]) =>
       `<li data-assignment-stage="${id}" data-state="${stageState(id, state.assignment)}"><span></span><small>${label}</small></li>`,
   )
   .join("")}</ol><p class="hint" data-assignment-check hidden></p></div>
 <p class="destination">Results go to your paired Hub; local checks stay on this machine.</p><div class="actions">${button("data-assignment-start-listening", "Start listening", "hidden")}${button("data-assignment-install-runtime", "Install runtime and retry", "hidden")}${button('data-open-hub data-hub-target="assignment"', "View in Hub")}${button("data-view-logs", "View logs", 'class="ghost"')}${button("data-retry-first-run-upload", "Retry upload", "hidden")}${button("data-copy-artifact-path", "Copy artifact path", "hidden")}${button("data-first-run-again", "Check again", "hidden")}${button("data-first-run-another-model", "Choose another model", "hidden")}</div></section>
 <div data-slot="private-running">${slot(state, "private-running")}</div><section class="card" data-home-recent><h2>Recent results</h2><div data-slot="home-results"><p class="meta">Your accepted results appear here after a benchmark.</p></div></section>
 <div class="duo"><section class="card"><h2>This machine</h2><strong data-machine-hardware>${escapeHtml(state.hardware || "Checking hardware…")}</strong><p class="meta" data-machine-fit>Model fit is checked before each benchmark.</p><div class="examples" data-home-models>${(
   state.downloadedModels || []
 )
   .slice(0, 3)
   .map((name) => `<span>${escapeHtml(name)}</span>`)
   .join(
     "",
   )}</div></section><section class="card"><h2>Already on this machine</h2><div data-home-local-models>${
   state.localModels?.length
     ? state.localModels
         .slice(0, 3)
         .map((name) => `<p class="meta">${escapeHtml(name)}</p>`)
         .join("")
     : '<p class="meta">No local model files found.</p>'
 }</div>${button("data-go-models", "View model library", 'class="ghost"')}</section></div>`;
}
export function renderModels(state = {}) {
  return `<h1 tabindex="-1">Models</h1><p class="sub">Your local model library.</p><div class="library card"><h2>Model library</h2><div data-library>${renderLibrary(state.library || {})}</div><div data-slot="discovery"></div><p class="meta" data-model-cache-status role="status">Checking downloads…</p><div class="actions">${button("data-refresh-model-cache", "Retry downloads", "hidden")}${button("data-clear-model-cache", "Clear unkept downloads", 'class="ghost"')}</div></div><div data-slot="storage">${slot(state, "storage")}</div>
 <details class="card check-panel" data-check-panel><summary>Check a model offline</summary><p class="meta">Local reports stay on this machine; endpoint checks follow the Hub handoff.</p><div class="seg" role="group" aria-label="Use case">${[
   ["general_assistant", "Chat & reasoning"],
   ["agentic_coding", "Coding"],
   ["reasoning", "Reasoning"],
 ]
   .map(([id, label]) =>
     button(
       'data-check-use-case="' + id + '"',
       label,
       'aria-pressed="' + (id === "general_assistant") + '"',
     ),
   )
   .join("")}</div>
 <div data-slot="private-benchmark">${slot(state, "private-benchmark")}</div><section><h2>Quick engine check</h2><div class="actions">${button("data-setup-runtime", "Make runtime ready")}${button("data-download-starter-gguf", "Download starter · 638 MB")}</div><p data-setup-runtime-status role="status"></p><label>Local GGUF file<input name="firstRunModelPath" autocomplete="off" placeholder="Paste a .gguf path"></label><p data-model-path-status role="status"></p>${button("data-first-run-start", "Run local check", "disabled")}<p data-first-run-status role="status"></p></section>${renderEndpoint()}</details>`;
}
function renderEndpoint() {
  return `<section data-observed-runtime-panel><h2>Check a local model endpoint</h2><label>Local API URL<input name="observedRuntimeEndpoint" type="url" placeholder="http://127.0.0.1:8000/v1"></label><p class="meta">The address and full responses stay on this machine.</p>${button("data-observed-runtime-start", "Run endpoint check", "disabled")}${button('data-observed-runtime-open-hub data-open-hub data-hub-target="build"', "View in Hub", "hidden")}<p data-observed-runtime-status role="status">Choose an endpoint check in Hub to begin.</p></section>`;
}
export function renderActivity(state = {}) {
  return `<h1 tabindex="-1">Activity</h1><p class="sub">Queue and results for this machine.</p><div data-slot="activity">${slot(state, "activity")}</div><div data-slot="private-history">${slot(state, "private-history")}</div><details class="card log-disclosure"><summary>Live Runner logs</summary><pre data-log-output>Waiting for Runner output…</pre><div class="actions">${button("data-clear-logs", "Clear logs")}${button("data-copy-logs", "Copy logs")}</div></details>`;
}
export function renderSettings(state = {}) {
  return `<h1 tabindex="-1">Settings</h1><p class="sub">Changes save automatically.</p>
 <section class="settings-group"><h2>General</h2><div class="settings-list"><div data-slot="startup">${slot(state, "startup")}</div><div data-slot="background">${slot(state, "background")}</div><div data-slot="notifications">${slot(state, "notifications")}</div><div class="setting-row"><strong>Theme</strong><div class="seg" role="group" aria-label="Color theme">${["system", "light", "dark"].map((id) => button('data-theme-choice="' + id + '"', id[0].toUpperCase() + id.slice(1), 'aria-pressed="' + (id === "system") + '"')).join("")}</div></div></div></section>
 <section class="settings-group"><h2>This machine</h2><div class="settings-list"><div data-slot="machine">${slot(state, "machine")}</div><div data-slot="gpu">${slot(state, "gpu")}</div></div></section>
 <section class="settings-group"><h2>Account</h2><div class="settings-list"><form data-runner-form><div class="setting-row"><div><strong data-pair-state>Connect this machine</strong><p class="meta" data-token-state>Tokens are not shown in this browser UI.</p></div><div class="actions">${button("data-browser-pair-runner", "Connect in browser")}${button("data-start-runner", "Start listening")}${button("data-stop-runner", "Stop listening", "disabled")}${button("data-reset-pairing", "Disconnect")}</div></div><div data-device-pairing hidden><strong data-device-user-code></strong><p data-device-expiry></p>${button("data-device-open-browser", "Open connection page")}${button("data-device-cancel", "Stop waiting")}</div><details class="pair-code"><summary>Use a pasted code</summary><label>Hub URL<input name="apiUrl" type="url" value="https://api.infergrade.com"></label><label>Pairing code<input name="pairCode" autocomplete="off"></label><label>Machine name<input name="runnerLabel" autocomplete="off"></label>${button("data-pair-runner", "Connect with code")}${button('data-open-hub data-hub-target="setup"', "Get a code in Hub")}</details></form></div></section>
 <section class="settings-group"><h2>Hugging Face</h2><div class="settings-list" data-slot="hf">${slot(state, "hf")}</div></section>
 <details class="settings-group advanced" data-support-details><summary>Advanced</summary><div class="settings-list"><section data-runtime-tools><h2>Runtime</h2><p data-runtime-llama-status role="status"></p><div class="actions">${button("data-readiness-check", "Make ready")}${button("data-runtime-install-managed", "Make runtime ready")}${button("data-runtime-plan", "Inspect plan")}${button("data-runtime-remove-selected", "Remove runtime")}${button("data-runner-self-test", "Run self-test")}</div><label>Managed build<select name="runtimeId"><option value="">Runner-pinned default</option></select></label>${button("data-runtime-reinstall-managed", "Use selected build")}<label>Reviewed build<select name="runtimeCatalogTarget" disabled><option value="">Load catalog first</option></select></label><p data-runtime-catalog-status role="status"></p>${button("data-runtime-catalog-install", "Install selected build", "disabled")}${button("data-runtime-catalog-refresh", "Retry catalog", "hidden")}<label>Custom llama-cli<input name="firstRunRuntimePath" placeholder="/path/to/llama-cli"></label>${button("data-runtime-browse-existing", "Choose file")}${button("data-runtime-select-existing", "Use this binary")}</section>
 <div class="setting-row"><strong>Local endpoint</strong>${button("data-settings-endpoint", "Check local endpoint")}</div><div class="setting-row"><strong>Logs & support</strong><div class="actions">${button("data-settings-logs", "Open logs")}${button("data-copy-support-summary", "Copy support summary")}</div></div><div class="setting-row"><div><strong>Updates <span data-app-version></span></strong><p data-update-channel>Update status unknown</p><p data-update-status role="status"></p></div>${button("data-check-update", "Check for updates")}</div><div data-update-actions hidden><strong data-update-available></strong><p data-update-detail></p>${button("data-install-update", "Install update")}${button("data-relaunch-update", "Relaunch", "hidden")}</div>
 <details><summary>Checks & connection details</summary><p data-native-suite-status></p><p data-runtime-runner-version></p><p data-runner-cli-version></p><p data-hub-connection-status></p><p data-pairing-readiness-status></p><p data-container-runtime-status></p><p data-model-preflight-status></p><p data-last-check-label></p>${button("data-repair-pairing", "Reconnect")}</details></div></details>`;
}

export function renderLibrary({ found = [], downloads = [], page = 0 } = {}) {
  const rows = [
    ...found.map((file) => ({ ...file, origin: "external" })),
    ...downloads.map((file) => ({ ...file, origin: "download" })),
  ];
  const bytes = (value) =>
    Number.isFinite(value)
      ? `${(value / 1024 ** 3).toFixed(1)} GB`
      : "Size unavailable";
  const pages = Math.max(1, Math.ceil(rows.length / 5));
  page = Math.min(page, pages - 1);
  return rows.length
    ? `<div class="model-list">${rows
        .slice(page * 5, page * 5 + 5)
        .map(
          (file) =>
            `<div class="model-row" data-model-id="${eModel(file.artifact_id || file.path || file.name)}"><div class="grow"><strong>${eModel(file.name)}</strong><p class="meta">${eModel(file.quantization || file.quant || "Quant unverified")} · ${bytes(file.size_bytes)} · ${eModel(file.origin === "download" ? "InferGrade" : file.source || "Local folder")} · ${libraryLastUsed(file.last_used_at)}</p></div>${file.origin === "download" && file.managed ? `<label>Keep <input type="checkbox" data-library-keep="${eModel(file.artifact_id)}" aria-label="Keep ${eModel(file.name)}" ${file.keep ? "checked" : ""}></label><button type="button" data-library-delete="${eModel(file.artifact_id)}" ${file.keep ? "disabled" : ""}>Delete</button>` : `<button type="button" data-library-check="${eModel(file.path)}" ${file.format === "safetensors" ? "disabled" : ""}>Check</button><span class="meta" title="Runner preserves files owned by other apps.">External file</span>`}<details><summary aria-label="Details for ${eModel(file.name)}">Details</summary><p>${eModel(file.path || file.name)}</p><p class="meta">${eModel(file.reason || "File names do not verify publisher, quantization or memory fit.")}</p>${file.format === "safetensors" ? '<p class="meta">Use infergrade models convert with a compatible llama.cpp converter to create a GGUF; source files stay unchanged.</p>' : ""}</details></div>`,
        )
        .join(
          "",
        )}</div>${pages > 1 ? `<div class="actions"><button type="button" data-library-page="${page - 1}" ${page === 0 ? "disabled" : ""}>Previous</button><span>Page ${page + 1} of ${pages}</span><button type="button" data-library-page="${page + 1}" ${page + 1 === pages ? "disabled" : ""}>Next</button></div>` : ""}`
    : '<p class="meta">No models found yet.</p>';
}
const eModel = escapeHtml;

function stageState(id, assignment) {
  if (!assignment) return "pending";
  const order = [
    "download",
    "verify",
    "load",
    "benchmark",
    "publish",
    "complete",
  ];
  const current = assignmentProgressStage(assignment);
  const index = order.indexOf(current);
  return assignment.phase === "Complete" || order.indexOf(id) < index
    ? "complete"
    : order.indexOf(id) === index
      ? "current"
      : "pending";
}

function statusIcon(hero) {
  const paths =
    hero.title === "Running"
      ? '<path d="M20 12a8 8 0 1 1-8-8"/>'
      : hero.title === "Ready"
        ? '<path d="m5 12 4 4L19 6"/>'
        : hero.title === "Needs attention"
          ? '<path d="M12 4 3 20h18L12 4Z"/><path d="M12 9v5m0 3h.01"/>'
          : hero.title === "Paused"
            ? '<path d="M8 5v14m8-14v14"/>'
            : '<path d="M8 3v5m8-5v5M6 8h12v3a6 6 0 0 1-12 0V8Zm6 9v4"/>';
  return `<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
}

function libraryLastUsed(value) {
  // Managed cache timestamps are Unix seconds; ISO strings also occur in UI fixtures.
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return value != null && Number.isFinite(date.getTime())
    ? "Last used " + escapeHtml(date.toLocaleDateString())
    : "Last used unavailable";
}
