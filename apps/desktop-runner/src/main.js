import "./styles.css";
import packageInfo from "../package.json";
import {
  normalizeDesktopApiUrl,
  userSafeStartFailure,
  userSafeTokenFailure,
  userSafeUpdateFailure,
} from "./desktopHelpers.js";

const SIDECAR_NAME = "binaries/infergrade-sidecar";
const API_URL_STORAGE_KEY = "infergrade.runner.apiUrl";
const FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY = "infergrade.runner.firstRun.runId";
const FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY = "infergrade.runner.firstRun.workerId";
const THEME_STORAGE_KEY = "infergrade.runner.theme";
const APP_VERSION_FALLBACK = packageInfo.version;
const UPDATE_CHANNEL = "release";
const UPDATE_STATUS = "Open the signed desktop app to check for verified updates.";

const form = document.querySelector("[data-runner-form]");
const startButton = document.querySelector("[data-start-runner]");
const stopButton = document.querySelector("[data-stop-runner]");
const pairButton = document.querySelector("[data-pair-runner]");
const saveTokenButton = document.querySelector("[data-save-token]");
const clearTokenButton = document.querySelector("[data-clear-token]");
const resetPairingButton = document.querySelector("[data-reset-pairing]");
const clearLogsButton = document.querySelector("[data-clear-logs]");
const themeChoiceButtons = [...document.querySelectorAll("[data-theme-choice]")];
const runtimePlanButton = document.querySelector("[data-runtime-plan]");
const runtimeSelectExistingButton = document.querySelector("[data-runtime-select-existing]");
const firstRunStartButton = document.querySelector("[data-first-run-start]");
const firstRunStatus = document.querySelector("[data-first-run-status]");
const firstRunHandoffStatus = document.querySelector("[data-first-run-handoff-status]");
const runnerSelfTestButton = document.querySelector("[data-runner-self-test]");
const checkUpdateButton = document.querySelector("[data-check-update]");
const installUpdateButton = document.querySelector("[data-install-update]");
const relaunchUpdateButton = document.querySelector("[data-relaunch-update]");
const appVersion = document.querySelector("[data-app-version]");
const updateChannel = document.querySelector("[data-update-channel]");
const updateStatus = document.querySelector("[data-update-status]");
const updateActions = document.querySelector("[data-update-actions]");
const updateAvailable = document.querySelector("[data-update-available]");
const updateDetail = document.querySelector("[data-update-detail]");
const runnerCliVersion = document.querySelector("[data-runner-cli-version]");
const runtimeRunnerVersion = document.querySelector("[data-runtime-runner-version]");
const nativeSuiteStatus = document.querySelector("[data-native-suite-status]");
const hubConnectionStatus = document.querySelector("[data-hub-connection-status]");
const pairingReadinessStatus = document.querySelector("[data-pairing-readiness-status]");
const runtimeLlamaStatus = document.querySelector("[data-runtime-llama-status]");
const containerRuntimeStatus = document.querySelector("[data-container-runtime-status]");
const modelPathStatus = document.querySelector("[data-model-path-status]");
const statusText = document.querySelector("[data-runner-status]");
const statusDot = document.querySelector("[data-status-dot]");
const pairState = document.querySelector("[data-pair-state]");
const tokenState = document.querySelector("[data-token-state]");
const logOutput = document.querySelector("[data-log-output]");

let childProcess = null;
let logLines = [];
let tauriInvoke = null;
let tauriListen = null;
let runnerListenerEventsReady = false;
let firstRunEventsReady = false;
let runnerStartupLines = [];
let runnerStartupWaiters = [];
let previewToken = "";
let pendingUpdate = null;
let lastNormalizedApiUrl = "https://api.infergrade.com/";
let llamaRuntimeReadiness = "Inspect the plan before running local llama.cpp jobs.";
let nativeSuiteReadiness = "Native first-run can run with a local GGUF model and selected llama.cpp runtime. Docker is optional for advanced sandboxed benchmarks.";
let containerRuntimeReadiness = "Docker and Podman only unlock advanced sandboxed benchmarks.";
let modelPathReadiness = "Select a local GGUF model for the first benchmark.";
let savedTokenAvailable = false;
let runnerProfileAvailable = false;

function systemTheme() {
  if (typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

function preferredThemeMode() {
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (savedTheme === "dark" || savedTheme === "light" || savedTheme === "system") {
    return savedTheme;
  }
  return "system";
}

function applyThemeMode(mode) {
  const themeMode = mode === "dark" || mode === "light" || mode === "system" ? mode : "system";
  const effectiveTheme = themeMode === "system" ? systemTheme() : themeMode;
  document.documentElement.dataset.theme = effectiveTheme;
  document.documentElement.dataset.themeMode = themeMode;
  themeChoiceButtons.forEach((button) => {
    button.setAttribute("aria-pressed", button.dataset.themeChoice === themeMode ? "true" : "false");
  });
}

function initTheme() {
  applyThemeMode(preferredThemeMode());
  if (typeof window.matchMedia !== "function") {
    return;
  }
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const refreshSystemTheme = () => {
    if (preferredThemeMode() === "system") {
      applyThemeMode("system");
    }
  };
  if (typeof media.addEventListener === "function") {
    media.addEventListener("change", refreshSystemTheme);
  } else if (typeof media.addListener === "function") {
    media.addListener(refreshSystemTheme);
  }
}

async function resolveAppVersion() {
  if (!isTauriRuntime()) {
    return APP_VERSION_FALLBACK;
  }
  try {
    const app = await import("@tauri-apps/api/app");
    return await app.getVersion();
  } catch (error) {
    appendLog(`Could not read app version from Tauri: ${error.message || error}`);
    return APP_VERSION_FALLBACK;
  }
}

async function renderReleaseStatus() {
  const version = await resolveAppVersion();
  if (appVersion) {
    appVersion.textContent = `v${version}`;
  }
  if (updateChannel) {
    updateChannel.textContent = UPDATE_CHANNEL === "release" ? "Current release" : `${UPDATE_CHANNEL} channel`;
  }
  if (updateStatus) {
    updateStatus.textContent = isTauriRuntime() ? "Ready to check for verified updates." : UPDATE_STATUS;
  }
}

function renderUpdateActions(visible, title = "Update available", detail = "Ready to download.") {
  if (updateActions) {
    updateActions.hidden = !visible;
  }
  if (updateAvailable) {
    updateAvailable.textContent = title;
  }
  if (updateDetail) {
    updateDetail.textContent = detail;
  }
}

function setUpdateStatus(message) {
  if (updateStatus) {
    updateStatus.textContent = message;
  }
}

function updateDownloadProgress(event) {
  if (event.event === "Started") {
    const size = event.data?.contentLength ? `${Math.round(event.data.contentLength / 1024 / 1024)} MB` : "unknown size";
    setUpdateStatus(`Downloading update (${size})...`);
    return;
  }
  if (event.event === "Progress") {
    setUpdateStatus("Downloading update...");
    return;
  }
  if (event.event === "Finished") {
    setUpdateStatus("Installing update...");
  }
}

async function checkForAppUpdate() {
  if (!isTauriRuntime()) {
    setUpdateStatus("Open the desktop app to check signed updates.");
    appendLog("Open the desktop app to check signed updates.");
    return;
  }
  checkUpdateButton.disabled = true;
  setUpdateStatus("Checking for signed updates...");
  renderUpdateActions(false);
  try {
    const { check } = await import("@tauri-apps/plugin-updater");
    const update = await check();
    pendingUpdate = update;
    if (!update) {
      setUpdateStatus("InferGrade Runner is up to date.");
      appendLog("No desktop Runner update is available.");
      return;
    }
    const detail = update.body || `Current ${update.currentVersion}; available ${update.version}.`;
    setUpdateStatus(`Update ${update.version} is available.`);
    renderUpdateActions(true, `Update ${update.version}`, detail);
    if (installUpdateButton) {
      installUpdateButton.disabled = false;
    }
    if (relaunchUpdateButton) {
      relaunchUpdateButton.disabled = true;
    }
    appendLog(`Desktop Runner update ${update.version} is available.`);
  } catch (error) {
    setUpdateStatus(userSafeUpdateFailure(error.message || error));
    appendLog(`Update check failed: ${error.message || error}`);
  } finally {
    checkUpdateButton.disabled = false;
  }
}

async function installPendingUpdate() {
  if (!pendingUpdate) {
    await checkForAppUpdate();
  }
  if (!pendingUpdate) {
    return;
  }
  installUpdateButton.disabled = true;
  setUpdateStatus(`Installing update ${pendingUpdate.version}...`);
  try {
    await pendingUpdate.downloadAndInstall(updateDownloadProgress);
    setUpdateStatus("Update installed. Relaunch to finish.");
    appendLog(`Installed desktop Runner update ${pendingUpdate.version}.`);
    if (relaunchUpdateButton) {
      relaunchUpdateButton.disabled = false;
    }
  } catch (error) {
    installUpdateButton.disabled = false;
    setUpdateStatus("Update install failed.");
    appendLog(`Update install failed: ${error.message || error}`);
  }
}

async function relaunchAfterUpdate() {
  try {
    const { relaunch } = await import("@tauri-apps/plugin-process");
    await relaunch();
  } catch (error) {
    appendLog(`Could not relaunch automatically: ${error.message || error}`);
    setUpdateStatus("Relaunch failed. Quit and reopen the app.");
  }
}

function renderRunnerCliVersion(label) {
  if (runnerCliVersion) {
    runnerCliVersion.textContent = `Runner CLI: ${label}`;
  }
  if (runtimeRunnerVersion) {
    runtimeRunnerVersion.textContent = label;
  }
}

function renderLocalReadinessChecklist() {
  if (nativeSuiteStatus) {
    nativeSuiteStatus.textContent = nativeSuiteReadiness;
  }
  if (hubConnectionStatus) {
    hubConnectionStatus.textContent = `Hub API: ${lastNormalizedApiUrl}`;
  }
  if (pairingReadinessStatus) {
    if (childProcess) {
      pairingReadinessStatus.textContent = "Paired and listening for Hub runs.";
    } else if ((savedTokenAvailable && runnerProfileAvailable) || previewToken || form.elements.hubToken.value.trim()) {
      pairingReadinessStatus.textContent = savedTokenAvailable && runnerProfileAvailable
        ? "Pairing token and profile are saved. Start listening when ready."
        : "Pairing token is available. Start listening when ready.";
    } else if (runnerProfileAvailable) {
      pairingReadinessStatus.textContent = "Runner profile is saved, but the token is unavailable. Pair again or reset pairing.";
    } else if (savedTokenAvailable) {
      pairingReadinessStatus.textContent = "Runner token is saved, but the profile is unavailable. Pair again or reset pairing.";
    } else {
      pairingReadinessStatus.textContent = "Paste a Hub pairing code to save this machine.";
    }
  }
  if (runtimeLlamaStatus) {
    runtimeLlamaStatus.textContent = llamaRuntimeReadiness;
  }
  if (containerRuntimeStatus) {
    containerRuntimeStatus.textContent = containerRuntimeReadiness;
  }
  if (modelPathStatus) {
    modelPathStatus.textContent = modelPathReadiness;
  }
}

function renderDesktopReadiness(payload = {}) {
  if (!payload.status) {
    nativeSuiteReadiness = "Native first-run can run with a local GGUF model and selected llama.cpp runtime. Docker is optional for advanced sandboxed benchmarks.";
    containerRuntimeReadiness = "Open the desktop app to check Docker/Podman. Docker is optional advanced support.";
    renderLocalReadinessChecklist();
    return;
  }
  nativeSuiteReadiness =
    payload.native_benchmark_message ||
    "Native first-run can run with a local GGUF model and selected llama.cpp runtime. Docker is optional for advanced sandboxed benchmarks.";
  const runtime = payload.llama_cpp_runtime || "";
  const runtimeMessage = payload.llama_cpp_message || "";
  if (runtime === "available") {
    llamaRuntimeReadiness = runtimeMessage || "Native llama.cpp runtime is available.";
  } else if (runtime === "missing") {
    llamaRuntimeReadiness = runtimeMessage || "Select or install a native llama.cpp runtime before the first local benchmark.";
  }
  const docker = payload.docker || {};
  const podman = payload.podman || {};
  if (docker.status === "found") {
    containerRuntimeReadiness = "Docker detected. Advanced sandboxed benchmarks are available.";
  } else if (podman.status === "found") {
    containerRuntimeReadiness = "Podman detected. Advanced sandboxed benchmark support may be available.";
  } else {
    containerRuntimeReadiness =
      runtime === "available"
        ? "Docker not found. Native runtime checks can continue; advanced sandboxed benchmarks are disabled."
        : "Docker not found. Select a native runtime before first-run benchmark support; advanced sandboxed benchmarks are disabled.";
  }
  renderLocalReadinessChecklist();
}

async function refreshRunnerCliVersion() {
  const Command = await loadTauriShell();
  if (!Command) {
    renderRunnerCliVersion("available inside the desktop app");
    return;
  }

  try {
    const output = await Command.sidecar(SIDECAR_NAME, ["--version"]).execute();
    if (output.code !== 0) {
      throw new Error(output.stderr || output.stdout || `version command exited with code ${output.code}`);
    }
    renderRunnerCliVersion((output.stdout || output.stderr || "version unavailable").trim());
  } catch (error) {
    renderRunnerCliVersion("version unavailable");
    appendLog(`Could not read Runner CLI version: ${error.message || error}`);
  }
}

async function checkRunnerStartupSelfTest() {
  if (runtimeRunnerVersion) {
    runtimeRunnerVersion.textContent = "Checking Runner startup self-test...";
  }
  const Command = await loadTauriShell();
  if (!Command) {
    if (runtimeRunnerVersion) {
      runtimeRunnerVersion.textContent = "Startup self-test runs inside the desktop app.";
    }
    return;
  }
  try {
    const output = await Command.sidecar(SIDECAR_NAME, ["desktop-self-test"]).execute();
    if (output.code !== 0) {
      throw new Error(output.stderr || output.stdout || `self-test exited with code ${output.code}`);
    }
    const detail = output.stdout?.trim() || "Runner core is available.";
    if (runtimeRunnerVersion) {
      runtimeRunnerVersion.textContent = "Runner core available.";
    }
    appendLog(`Startup self-test passed: ${detail}`);
  } catch (error) {
    if (runtimeRunnerVersion) {
      runtimeRunnerVersion.textContent = "Runner core unavailable. Run startup self-test for details.";
    }
    appendLog(`Startup self-test failed: ${error.message || error}`);
  }
}

async function checkDesktopReadiness() {
  const Command = await loadTauriShell();
  if (!Command) {
    renderDesktopReadiness({});
    return;
  }
  try {
    const output = await Command.sidecar(SIDECAR_NAME, ["desktop-readiness"]).execute();
    if (output.code !== 0) {
      throw new Error(output.stderr || output.stdout || `readiness command exited with code ${output.code}`);
    }
    const payload = JSON.parse(output.stdout || "{}");
    renderDesktopReadiness(payload);
    appendLog(`Desktop readiness: ${output.stdout.trim()}`);
  } catch (error) {
    containerRuntimeReadiness = "Could not check optional Docker/Podman support. Native benchmark setup can continue.";
    appendLog(`Desktop readiness check failed: ${error.message || error}`);
    renderLocalReadinessChecklist();
  }
}

function chooseThemeMode(mode) {
  const themeMode = mode === "dark" || mode === "light" || mode === "system" ? mode : "system";
  window.localStorage.setItem(THEME_STORAGE_KEY, themeMode);
  applyThemeMode(themeMode);
}

function isTauriRuntime() {
  return "__TAURI_INTERNALS__" in window;
}

async function restoreFormState() {
  const savedApiUrl = window.localStorage.getItem(API_URL_STORAGE_KEY);

  if (savedApiUrl) {
    form.elements.apiUrl.value = normalizeDesktopApiUrl(savedApiUrl);
    lastNormalizedApiUrl = form.elements.apiUrl.value;
  }

  await updateTokenState();
  renderLocalReadinessChecklist();
}

async function loadTauriInvoke() {
  if (!isTauriRuntime()) {
    return null;
  }
  if (!tauriInvoke) {
    const core = await import("@tauri-apps/api/core");
    tauriInvoke = core.invoke;
  }
  return tauriInvoke;
}

async function loadTauriListen() {
  if (!isTauriRuntime()) {
    return null;
  }
  if (!tauriListen) {
    const event = await import("@tauri-apps/api/event");
    tauriListen = event.listen;
  }
  return tauriListen;
}

function resolveRunnerStartupWaiters(error = null) {
  const waiters = runnerStartupWaiters;
  runnerStartupWaiters = [];
  waiters.forEach((resolve) => resolve(error));
}

function waitForEarlyRunnerFailure(timeoutMs = 900) {
  return new Promise((resolve) => {
    runnerStartupWaiters.push(resolve);
    window.setTimeout(() => {
      runnerStartupWaiters = runnerStartupWaiters.filter((waiter) => waiter !== resolve);
      resolve(null);
    }, timeoutMs);
  });
}

async function ensureRunnerListenerEvents() {
  if (runnerListenerEventsReady) {
    return;
  }
  const listen = await loadTauriListen();
  if (!listen) {
    return;
  }
  runnerListenerEventsReady = true;
  await listen("runner-listener-event", (event) => {
    const payload = event?.payload || {};
    if (payload.type === "stdout" || payload.type === "stderr") {
      const line = String(payload.line || "");
      if (line.trim()) {
        runnerStartupLines.push(line.trim());
        if (runnerStartupLines.length > 8) {
          runnerStartupLines.shift();
        }
        appendLog(line);
      }
      return;
    }
    if (payload.type === "error") {
      const detail = payload.detail || "Runner process error.";
      appendLog(`Runner process error: ${detail}`);
      childProcess = null;
      startButton.disabled = false;
      stopButton.disabled = true;
      setStatus("Failed", "error");
      renderLocalReadinessChecklist();
      resolveRunnerStartupWaiters(new Error(String(detail)));
      return;
    }
    if (payload.type === "terminated") {
      const code = payload.code ?? "unknown";
      appendLog(`Runner exited with code ${code}.`);
      childProcess = null;
      startButton.disabled = false;
      stopButton.disabled = true;
      setStatus("Stopped", code === 0 ? "idle" : "error");
      renderLocalReadinessChecklist();
      const detail = runnerStartupLines.filter(Boolean).join("\n");
      resolveRunnerStartupWaiters(new Error(detail || `Runner exited with code ${code} before listening.`));
    }
  });
}

async function ensureFirstRunEvents() {
  if (firstRunEventsReady) {
    return;
  }
  const listen = await loadTauriListen();
  if (!listen) {
    return;
  }
  firstRunEventsReady = true;
  await listen("runner-first-run-event", (event) => {
    const payload = event?.payload || {};
    const message = firstRunMessageFromEvent(payload);
    if (!message) {
      return;
    }
    if (firstRunStatus) {
      firstRunStatus.textContent = message;
    }
    appendLog(`First-run ${payload.type || "event"}: ${message}`);
  });
}

async function loadStoredToken() {
  const invoke = await loadTauriInvoke();
  if (invoke) {
    return null;
  }
  return previewToken;
}

async function saveStoredToken(token) {
  const invoke = await loadTauriInvoke();
  if (invoke) {
    await invoke("save_runner_token", { token });
    return;
  }
  previewToken = token;
}

async function clearStoredToken() {
  const invoke = await loadTauriInvoke();
  if (invoke) {
    await invoke("clear_runner_token");
    return;
  }
  previewToken = "";
}

async function updateTokenState() {
  let hasToken = false;
  try {
    const invoke = await loadTauriInvoke();
    if (invoke) {
      const status = await invoke("runner_pairing_status");
      hasToken = status?.token?.status === "present";
      savedTokenAvailable = hasToken;
      runnerProfileAvailable = status?.profile?.status === "present";
      const profile = status?.profile?.profile || {};
      if (runnerProfileAvailable && hasToken) {
        tokenState.textContent = `Runner profile and OS token saved${profile.label ? ` for ${profile.label}` : ""}.`;
      } else if (runnerProfileAvailable) {
        tokenState.textContent = `Runner profile saved${profile.label ? ` for ${profile.label}` : ""}, but the OS token is unavailable.`;
      } else if (hasToken) {
        tokenState.textContent = "Runner token is saved in the OS credential store, but no runner profile is saved.";
      } else {
        tokenState.textContent = "No runner profile saved. Paste a Hub pairing code before listening for Hub runs.";
      }
      renderLocalReadinessChecklist();
      return;
    }
    hasToken = Boolean(await loadStoredToken());
  } catch (error) {
    savedTokenAvailable = false;
    runnerProfileAvailable = false;
    tokenState.textContent = userSafeTokenFailure(error.message || error);
    appendLog(`Could not read saved token: ${error.message || error}`);
    return;
  }
  savedTokenAvailable = hasToken;
  runnerProfileAvailable = false;
  if (isTauriRuntime()) {
    tokenState.textContent = hasToken
      ? "Runner token saved in the OS credential store."
      : "No token saved. Paste a paired runner token before listening for Hub runs.";
    if (hasToken && pairingReadinessStatus) {
      pairingReadinessStatus.textContent = "Pairing token is saved. Start listening when ready.";
    }
    return;
  }

  tokenState.textContent = hasToken
    ? "Development token held in memory until this page is closed."
    : "Development view does not persist tokens; the app uses the OS credential store.";
}

function setStatus(status, tone = "idle") {
  statusText.textContent = status;
  statusDot.dataset.tone = tone;
}

function redactSecrets(message) {
  return String(message || "")
    .replace(/igrp_[^\s"']+/g, "igrp_[redacted]")
    .replace(/igrt_[^\s"']+/g, "igrt_[redacted]")
    .replace(/qbhr_[^\s"']+/g, "qbhr_[redacted]")
    .replace(/("access_token"\s*:\s*")[^"]+(")/g, "$1[redacted]$2")
    .replace(/("runner_token"\s*:\s*")[^"]+(")/g, "$1[redacted]$2");
}

function appendLog(message) {
  const normalized = redactSecrets(message).trimEnd();
  if (!normalized) {
    return;
  }

  const timestamp = new Date().toLocaleTimeString();
  logLines = [...logLines, `[${timestamp}] ${normalized}`].slice(-400);
  logOutput.textContent = logLines.join("\n");
  logOutput.scrollTop = logOutput.scrollHeight;
}

function firstRunMessageFromEvent(payload = {}) {
  if (payload.type === "benchmark_started") {
    return "Native first-run started.";
  }
  if (payload.type === "benchmark_progress") {
    const percent = Number.isFinite(payload.progress_percent) ? ` (${Math.round(payload.progress_percent)}%)` : "";
    return `${payload.message || "Native first-run progress."}${percent}`;
  }
  if (payload.type === "benchmark_completed") {
    return "Native first-run completed.";
  }
  if (payload.type === "error") {
    return payload.message || "Native first-run failed.";
  }
  return "";
}

function pairingSummary(stdout) {
  try {
    const payload = JSON.parse(stdout || "{}");
    const label = payload.runner_profile?.label || payload.runner_profile?.runner_id || "local runner";
    const profilePath = payload.profile_path ? ` Profile saved at ${payload.profile_path}.` : "";
    return `Paired ${label}.${profilePath}`;
  } catch (_error) {
    return "Pairing completed and the runner profile was saved.";
  }
}

async function loadTauriShell() {
  if (!isTauriRuntime()) {
    return null;
  }

  const shell = await import("@tauri-apps/plugin-shell");
  return shell.Command;
}

async function executeSidecar(args) {
  const Command = await loadTauriShell();
  if (!Command) {
    appendLog(`Development view cannot run: infergrade ${args.join(" ")}`);
    setStatus("Development view", "warning");
    return null;
  }
  appendLog(`Running: infergrade ${args.join(" ")}`);
  const output = await Command.sidecar(SIDECAR_NAME, args).execute();
  if (output.stdout) {
    appendLog(output.stdout);
  }
  if (output.stderr) {
    appendLog(output.stderr);
  }
  if (output.code !== 0) {
    throw new Error(`infergrade ${args[0]} exited with code ${output.code}.`);
  }
  return output;
}

async function runnerEnvironment() {
  const typedToken = form.elements.hubToken.value.trim();
  if (typedToken) {
    return { INFERGRADE_HUB_TOKEN: typedToken };
  }
  return {};
}

function credentialSourceLabel(source = "") {
  if (source === "typed_input") {
    return "the pasted token";
  }
  if (source === "saved_pairing") {
    return "the saved Runner profile and OS credential store";
  }
  return "missing pairing credentials";
}

async function listenerStartPlan(apiUrl) {
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    return null;
  }
  return invoke("listener_start_plan", {
    apiUrl,
    typedTokenPresent: Boolean(form.elements.hubToken.value.trim()),
  });
}

function readApiUrl() {
  const normalized = normalizeDesktopApiUrl(form.elements.apiUrl.value);
  form.elements.apiUrl.value = normalized;
  lastNormalizedApiUrl = normalized;
  renderLocalReadinessChecklist();
  return normalized;
}

function runtimeCommandArgs(extraArgs = []) {
  const runtimeId = form.elements.runtimeId?.value.trim();
  const args = ["install-runtime", "--runtime", "llama.cpp"];
  if (runtimeId) {
    args.push("--runtime-id", runtimeId);
  }
  return [...args, ...extraArgs];
}

function runtimePlanSummary(plan = {}) {
  const recommended = plan.recommended_runtime || {};
  const selected = plan.selected_runtime || {};
  const selectedText = selected.status === "selected" ? "Selected runtime is recorded." : "No managed runtime is selected yet.";
  const runtimeText = plan.message || "No install command was run. Review the runtime plan before selecting a runtime.";
  const lane = recommended.platform || recommended.accelerator || "this machine";
  return `${runtimeText} Recommended lane: ${lane}. ${selectedText}`;
}

function readFirstRunModelPath() {
  const modelPath = form.elements.firstRunModelPath?.value.trim() || "";
  if (!modelPath) {
    throw new Error("Select a local GGUF model file before running the first benchmark.");
  }
  if (!modelPath.toLowerCase().endsWith(".gguf")) {
    throw new Error("Use a local GGUF model file for the native first-run benchmark.");
  }
  modelPathReadiness = `First-run model selected: ${modelPath}`;
  renderLocalReadinessChecklist();
  return modelPath;
}

function readFirstRunRuntimePath() {
  return form.elements.firstRunRuntimePath?.value.trim() || null;
}

function firstRunHandoffFromUrl() {
  const params = new URLSearchParams(window.location.search || "");
  const runId =
    params.get("first_run_run_id") ||
    params.get("firstRunRunId") ||
    params.get("run_id") ||
    params.get("runId") ||
    "";
  const workerId = params.get("first_run_worker_id") || params.get("worker_id") || params.get("workerId") || "";
  return {
    runId: runId.trim(),
    workerId: workerId.trim(),
  };
}

function applyFirstRunHandoff() {
  const urlHandoff = firstRunHandoffFromUrl();
  const storedRunId = window.localStorage.getItem(FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY) || "";
  const storedWorkerId = window.localStorage.getItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY) || "";
  const runId = urlHandoff.runId || storedRunId;
  const workerId = urlHandoff.workerId || storedWorkerId;
  if (runId && form.elements.firstRunUploadRunId && !form.elements.firstRunUploadRunId.value.trim()) {
    form.elements.firstRunUploadRunId.value = runId;
  }
  if (workerId && form.elements.firstRunUploadWorkerId && !form.elements.firstRunUploadWorkerId.value.trim()) {
    form.elements.firstRunUploadWorkerId.value = workerId;
  }
  if (urlHandoff.runId) {
    window.localStorage.setItem(FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY, urlHandoff.runId);
    if (urlHandoff.workerId) {
      window.localStorage.setItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY, urlHandoff.workerId);
    }
  }
  if (firstRunHandoffStatus) {
    firstRunHandoffStatus.textContent = runId
      ? `Ready to upload this first-run result to Hub run ${runId}.`
      : "If Hub opened Desktop with a run handoff, this fills automatically.";
  }
}

function readFirstRunUploadRunId() {
  const runId = form.elements.firstRunUploadRunId?.value.trim() || "";
  if (runId) {
    window.localStorage.setItem(FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY, runId);
  }
  return runId || null;
}

function readFirstRunUploadWorkerId() {
  const workerId = form.elements.firstRunUploadWorkerId?.value.trim() || "";
  if (workerId) {
    window.localStorage.setItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY, workerId);
  }
  return workerId || null;
}

function clearFirstRunHandoff() {
  window.localStorage.removeItem(FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY);
  window.localStorage.removeItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY);
  if (form.elements.firstRunUploadRunId) {
    form.elements.firstRunUploadRunId.value = "";
  }
  if (form.elements.firstRunUploadWorkerId) {
    form.elements.firstRunUploadWorkerId.value = "";
  }
  if (firstRunHandoffStatus) {
    firstRunHandoffStatus.textContent = "Hub upload complete. Start another run from Hub when you want to add more evidence.";
  }
}

async function startRunner({ confirmStarted = false } = {}) {
  const apiUrl = readApiUrl();
  window.localStorage.setItem(API_URL_STORAGE_KEY, apiUrl);

  if (childProcess) {
    appendLog("Runner is already listening.");
    return;
  }

  startButton.disabled = true;
  setStatus("Starting", "warning");

  const invoke = await loadTauriInvoke();
  if (!invoke) {
    setStatus("Development view", "warning");
    appendLog("Open the desktop app to start the local Runner.");
    startButton.disabled = false;
    return;
  }

  await ensureRunnerListenerEvents();
  runnerStartupLines = [];
  const output = await invoke("start_runner_listener", {
    apiUrl,
    typedToken: form.elements.hubToken.value.trim() || null,
  });
  const plan = output?.plan || {};
  const runner = plan.runner_id ? ` for ${plan.runner_id}` : "";
  appendLog(
    `Runner start plan: ${plan.execution_mode || "default mode"} using ${credentialSourceLabel(plan.credential_source)}${runner}.`
  );
  childProcess = { rustManaged: true, pid: output?.pid || null };
  stopButton.disabled = false;
  setStatus("Listening", "good");
  renderLocalReadinessChecklist();
  appendLog(`Started infergrade listener for ${apiUrl}.`);
  if (confirmStarted) {
    const earlyFailure = await waitForEarlyRunnerFailure();
    if (earlyFailure) {
      throw earlyFailure;
    }
  }
}

async function pairRunner() {
  const apiUrl = readApiUrl();
  const pairCode = form.elements.pairCode.value.trim();
  const runnerLabel = form.elements.runnerLabel.value.trim();
  if (!pairCode) {
    throw new Error("Paste the one-time pairing code from the Hub first.");
  }
  window.localStorage.setItem(API_URL_STORAGE_KEY, apiUrl);

  const invoke = await loadTauriInvoke();
  if (!invoke) {
    setStatus("Development view", "warning");
    pairState.textContent = "Open the desktop app to redeem pairing codes and pair this machine.";
    appendLog("Open the desktop app to pair this machine.");
    return;
  }

  pairButton.disabled = true;
  startButton.disabled = true;
  pairState.textContent = "Redeeming pairing code...";
  try {
    const output = await invoke("redeem_runner_pairing", {
      apiUrl,
      pairCode,
      label: runnerLabel || null,
    });
    appendLog(pairingSummary(JSON.stringify(output || {})));
    form.elements.pairCode.value = "";
    await updateTokenState();
    pairState.textContent = "Paired. Starting the local Runner listener...";
    setStatus("Paired", "good");
    if (pairingReadinessStatus) {
      pairingReadinessStatus.textContent = "Pairing saved. Starting the listener...";
    }
    try {
      await startRunner({ confirmStarted: true });
      pairState.textContent = "Paired and listening for Hub runs.";
    } catch (startError) {
      const safeMessage = userSafeStartFailure(startError.message || startError);
      pairState.textContent = `Paired. Runner could not start automatically. ${safeMessage}`;
      setStatus("Paired; start blocked", "warning");
      appendLog(`Could not start Runner after pairing: ${startError.message || startError}`);
      await checkRunnerStartupSelfTest();
    }
  } finally {
    pairButton.disabled = false;
    if (!childProcess) {
      startButton.disabled = false;
    }
  }
}

async function resetPairing() {
  const wasListening = Boolean(childProcess);
  if (wasListening) {
    await stopRunner();
    childProcess = null;
    startButton.disabled = false;
    stopButton.disabled = true;
  }
  form.elements.pairCode.value = "";
  form.elements.hubToken.value = "";
  const invoke = await loadTauriInvoke();
  if (invoke) {
    const payload = await invoke("reset_runner_pairing");
    appendLog(`Reset pairing state: ${JSON.stringify(payload || {})}`);
  } else {
    await clearStoredToken().catch((error) => appendLog(`Reset pairing could not clear stored token: ${error.message || error}`));
  }
  window.localStorage.setItem(API_URL_STORAGE_KEY, readApiUrl());
  pairState.textContent = wasListening
    ? "Pairing reset. Listener stop requested. Paste a fresh one-time code from Hub."
    : "Pairing reset. Paste a fresh one-time code from Hub.";
  setStatus("Idle", "idle");
  await updateTokenState();
  renderLocalReadinessChecklist();
}

async function runDesktopSelfTest() {
  const output = await executeSidecar(["desktop-self-test"]);
  if (!output) {
    return;
  }
  setStatus("Runner self-test passed", "good");
}

async function runNativeFirstRun() {
  const modelPath = readFirstRunModelPath();
  const runtimePath = readFirstRunRuntimePath();
  const uploadRunId = readFirstRunUploadRunId();
  const uploadWorkerId = readFirstRunUploadWorkerId();
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    firstRunStatus.textContent = "Open the desktop app to run the native first benchmark.";
    appendLog("Development view cannot run the native first benchmark.");
    return;
  }

  await ensureFirstRunEvents();
  firstRunStartButton.disabled = true;
  setStatus("First benchmark running", "warning");
  firstRunStatus.textContent = "Starting native first-run benchmark...";
  try {
    const payload = await invoke("run_desktop_native_first_run", {
      modelPath,
      runtimePath,
      uploadRunId,
      uploadWorkerId,
    });
    const result = payload?.result || {};
    const metrics = result.metrics || {};
    const speed = Number.isFinite(metrics.decode_tokens_per_second)
      ? `${metrics.decode_tokens_per_second.toFixed(2)} tokens/sec`
      : "speed unavailable";
    const ttft = Number.isFinite(metrics.time_to_first_token_ms)
      ? `${metrics.time_to_first_token_ms} ms TTFT`
      : "TTFT unavailable";
    const artifactPath = payload?.artifact?.path ? ` Artifact: ${payload.artifact.path}.` : "";
    const bundlePath = payload?.bundle_artifact?.path ? ` Bundle payload: ${payload.bundle_artifact.path}.` : "";
    const uploadStatus = payload?.upload?.uploaded
      ? ` Uploaded bundle ${payload.upload.bundle_id} to Hub run ${payload.upload.run_id}.`
      : payload?.upload?.error
        ? ` Upload failed: ${payload.upload.error}`
        : " Not uploaded; enter a Hub run ID to attach this evidence to a run.";
    firstRunStatus.textContent = `Completed native first-run (${speed}, ${ttft}).${artifactPath}${bundlePath}${uploadStatus}`;
    modelPathReadiness = payload?.upload?.uploaded
      ? "Native first-run completed and uploaded to Hub with native_first_run evidence."
      : payload?.upload?.error
        ? "Native first-run completed locally, but Hub upload failed. Keep the local artifacts and retry upload after fixing pairing or run access."
        : "Native first-run completed locally with result and bundle artifacts.";
    nativeSuiteReadiness = payload?.upload?.uploaded
      ? "Native first-run completed and uploaded through the paired desktop runner."
      : payload?.upload?.error
        ? "Native first-run evidence exists locally; Hub upload still needs a valid paired runner and run ID."
        : "Native first-run completed locally with native_first_run evidence and a Hub-compatible bundle preview.";
    if (payload?.upload?.uploaded) {
      clearFirstRunHandoff();
    } else {
      applyFirstRunHandoff();
    }
    setStatus("First benchmark complete", "good");
    renderLocalReadinessChecklist();
    appendLog(`Native first-run result: ${JSON.stringify(payload)}`);
  } catch (error) {
    const message = error.message || error;
    firstRunStatus.textContent = `Native first-run failed: ${message}`;
    setStatus("First benchmark failed", "error");
    appendLog(`Native first-run failed: ${message}`);
  } finally {
    firstRunStartButton.disabled = false;
  }
}

async function stopRunner() {
  if (!childProcess) {
    return;
  }

  const invoke = await loadTauriInvoke();
  if (invoke && childProcess.rustManaged) {
    await invoke("stop_runner_listener");
  } else if (typeof childProcess.kill === "function") {
    await childProcess.kill();
  }
  appendLog("Stop requested.");
}

pairButton.addEventListener("click", () => {
  pairRunner().catch((error) => {
    setStatus("Pairing failed", "error");
    pairState.textContent = "Pairing failed before this machine was saved. Check that the code has not expired, then try again.";
    appendLog(`Could not pair Runner: ${error.message || error}`);
  });
});

saveTokenButton.addEventListener("click", () => {
  const token = form.elements.hubToken.value.trim();
  saveStoredToken(token)
    .then(() => {
      form.elements.hubToken.value = "";
      window.localStorage.setItem(API_URL_STORAGE_KEY, form.elements.apiUrl.value.trim());
      return updateTokenState();
    })
    .catch((error) => {
      tokenState.textContent = userSafeTokenFailure(error.message || error);
      appendLog(`Could not save token: ${error.message || error}`);
    });
});

clearTokenButton.addEventListener("click", () => {
  clearStoredToken()
    .then(() => {
      form.elements.hubToken.value = "";
      return updateTokenState();
    })
    .catch((error) => {
      tokenState.textContent = userSafeTokenFailure(error.message || error);
      appendLog(`Could not clear token: ${error.message || error}`);
    });
});

resetPairingButton?.addEventListener("click", () => {
  resetPairing().catch((error) => {
    pairState.textContent = "Reset pairing could not finish. You can still paste a fresh code and try again.";
    appendLog(`Could not reset pairing: ${error.message || error}`);
  });
});

startButton.addEventListener("click", () => {
  startRunner().catch((error) => {
    setStatus("Failed", "error");
    startButton.disabled = false;
    stopButton.disabled = true;
    appendLog(`Could not start Runner: ${error.message || error}`);
  });
});

stopButton.addEventListener("click", () => {
  stopRunner().catch((error) => appendLog(`Could not stop Runner: ${error.message || error}`));
});

clearLogsButton.addEventListener("click", () => {
  logLines = [];
  logOutput.textContent = "Waiting for Runner output...";
});

themeChoiceButtons.forEach((button) => {
  button.addEventListener("click", () => chooseThemeMode(button.dataset.themeChoice));
});

runtimePlanButton?.addEventListener("click", () => {
  llamaRuntimeReadiness = "Checking the llama.cpp runtime plan...";
  renderLocalReadinessChecklist();
  loadTauriInvoke()
    .then((invoke) => {
      if (!invoke) {
        appendLog("Open the desktop app to inspect the native llama.cpp runtime plan.");
        llamaRuntimeReadiness = "Runtime plan is available inside the desktop app.";
        return null;
      }
      return invoke("llama_cpp_runtime_plan");
    })
    .then((plan) => {
      if (!plan) {
        return;
      }
      llamaRuntimeReadiness = runtimePlanSummary(plan);
      renderLocalReadinessChecklist();
      appendLog(`llama.cpp runtime plan: ${JSON.stringify(plan)}`);
    })
    .catch((error) => {
      llamaRuntimeReadiness = "Runtime plan unavailable. See logs for the technical detail.";
      renderLocalReadinessChecklist();
      setStatus("Runtime check failed", "error");
      appendLog(`Could not inspect llama.cpp runtime plan: ${error.message || error}`);
    });
});

runtimeSelectExistingButton?.addEventListener("click", () => {
  llamaRuntimeReadiness = "Looking for an installed llama.cpp runtime...";
  renderLocalReadinessChecklist();
  executeSidecar(runtimeCommandArgs(["--select-existing"]))
    .then(() => {
      llamaRuntimeReadiness = "Installed llama.cpp runtime selected. Start listening when paired.";
      renderLocalReadinessChecklist();
    })
    .catch((error) => {
      llamaRuntimeReadiness = "No installed llama.cpp runtime selected. See logs for the technical detail.";
      renderLocalReadinessChecklist();
      setStatus("Runtime selection failed", "error");
      appendLog(`Could not select installed llama.cpp runtime: ${error.message || error}`);
    });
});

firstRunStartButton?.addEventListener("click", () => {
  runNativeFirstRun().catch((error) => {
    const message = error.message || String(error);
    if (firstRunStatus) {
      firstRunStatus.textContent = message;
    }
    setStatus("First benchmark blocked", "error");
    appendLog(`Could not start native first-run: ${message}`);
  });
});

runnerSelfTestButton?.addEventListener("click", () => {
  runDesktopSelfTest().catch((error) => {
    setStatus("Runner self-test failed", "error");
    appendLog(`Runner self-test failed: ${error.message || error}`);
  });
});

checkUpdateButton?.addEventListener("click", () => {
  checkForAppUpdate().catch((error) => appendLog(`Could not check updates: ${error.message || error}`));
});

installUpdateButton?.addEventListener("click", () => {
  installPendingUpdate().catch((error) => appendLog(`Could not install update: ${error.message || error}`));
});

relaunchUpdateButton?.addEventListener("click", () => {
  relaunchAfterUpdate().catch((error) => appendLog(`Could not relaunch: ${error.message || error}`));
});

initTheme();
applyFirstRunHandoff();
renderReleaseStatus().catch((error) => appendLog(`Could not render release status: ${error.message || error}`));
refreshRunnerCliVersion().catch((error) => appendLog(`Could not check Runner CLI version: ${error.message || error}`));
checkRunnerStartupSelfTest().catch((error) => appendLog(`Could not run startup self-test: ${error.message || error}`));
checkDesktopReadiness().catch((error) => appendLog(`Could not check desktop readiness: ${error.message || error}`));
restoreFormState().catch((error) => appendLog(`Could not restore pairing state: ${error.message || error}`));
setStatus("Idle", "idle");
renderLocalReadinessChecklist();
