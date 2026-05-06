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
let previewToken = "";
let pendingUpdate = null;
let lastNormalizedApiUrl = "https://api.infergrade.com/";
let llamaRuntimeReadiness = "Inspect the plan before running local llama.cpp jobs.";
let nativeSuiteReadiness = "Docker is not required for your first local benchmark.";
let containerRuntimeReadiness = "Docker and Podman only unlock advanced sandboxed benchmarks.";
let savedTokenAvailable = false;

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
    } else if (savedTokenAvailable || previewToken || form.elements.hubToken.value.trim()) {
      pairingReadinessStatus.textContent = "Pairing token is available. Start listening when ready.";
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
    modelPathStatus.textContent = "Chosen in Hub run plans; Desktop validates runtime and listener readiness.";
  }
}

function renderDesktopReadiness(payload = {}) {
  nativeSuiteReadiness = "Native benchmark suite: ready. Docker is not required for your first local benchmark.";
  if (!payload.status) {
    containerRuntimeReadiness = "Open the desktop app to check Docker/Podman. Native benchmarks do not require them.";
    renderLocalReadinessChecklist();
    return;
  }
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
    containerRuntimeReadiness = "Docker not found. Native benchmarks are available; advanced sandboxed benchmarks are disabled.";
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

async function loadStoredToken() {
  const invoke = await loadTauriInvoke();
  if (invoke) {
    return invoke("load_runner_token");
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
    hasToken = Boolean(await loadStoredToken());
  } catch (error) {
    savedTokenAvailable = false;
    tokenState.textContent = userSafeTokenFailure(error.message || error);
    appendLog(`Could not read saved token: ${error.message || error}`);
    return;
  }
  savedTokenAvailable = hasToken;
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

  const savedToken = await loadStoredToken();
  return savedToken ? { INFERGRADE_HUB_TOKEN: savedToken } : {};
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

async function startRunner({ confirmStarted = false } = {}) {
  const apiUrl = readApiUrl();
  window.localStorage.setItem(API_URL_STORAGE_KEY, apiUrl);

  if (childProcess) {
    appendLog("Runner is already listening.");
    return;
  }

  startButton.disabled = true;
  setStatus("Starting", "warning");

  const Command = await loadTauriShell();
  if (!Command) {
    setStatus("Development view", "warning");
    appendLog("Open the desktop app to start the local Runner.");
    startButton.disabled = false;
    return;
  }

  const command = Command.sidecar(SIDECAR_NAME, ["start", "--api-url", apiUrl], {
    env: await runnerEnvironment()
  });

  const startupOutput = [];
  const rememberStartupLine = (line) => {
    startupOutput.push(String(line || "").trim());
    if (startupOutput.length > 8) {
      startupOutput.shift();
    }
  };
  let startupFailure = null;
  let markStartupFailure = null;
  const startupFailurePromise = new Promise((resolve) => {
    markStartupFailure = resolve;
  });

  command.stdout.on("data", (line) => {
    rememberStartupLine(line);
    appendLog(line);
  });
  command.stderr.on("data", (line) => {
    rememberStartupLine(line);
    appendLog(line);
  });
  command.on("close", (event) => {
    appendLog(`Runner exited with code ${event.code ?? "unknown"}.`);
    childProcess = null;
    startButton.disabled = false;
    stopButton.disabled = true;
    setStatus("Stopped", event.code === 0 ? "idle" : "error");
    renderLocalReadinessChecklist();
    const detail = startupOutput.filter(Boolean).join("\n");
    startupFailure = new Error(detail || `Runner exited with code ${event.code ?? "unknown"} before listening.`);
    markStartupFailure(startupFailure);
  });
  command.on("error", (error) => {
    appendLog(`Runner process error: ${error}`);
    childProcess = null;
    startButton.disabled = false;
    stopButton.disabled = true;
    setStatus("Failed", "error");
    renderLocalReadinessChecklist();
    startupFailure = new Error(String(error || "Runner process error."));
    markStartupFailure(startupFailure);
  });

  childProcess = await command.spawn();
  stopButton.disabled = false;
  setStatus("Listening", "good");
  renderLocalReadinessChecklist();
  appendLog(`Started infergrade listener for ${apiUrl}.`);
  if (confirmStarted) {
    const earlyFailure = await Promise.race([
      startupFailurePromise,
      new Promise((resolve) => setTimeout(() => resolve(null), 900)),
    ]);
    if (earlyFailure || startupFailure) {
      throw earlyFailure || startupFailure;
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

  const Command = await loadTauriShell();
  if (!Command) {
    setStatus("Development view", "warning");
    pairState.textContent = "Open the desktop app to redeem pairing codes and pair this machine.";
    appendLog("Open the desktop app to pair this machine.");
    return;
  }

  pairButton.disabled = true;
  startButton.disabled = true;
  pairState.textContent = "Redeeming pairing code...";
  const args = ["pair", "--api-url", apiUrl, "--pair-code", pairCode];
  if (runnerLabel) {
    args.push("--label", runnerLabel);
  }
  try {
    const output = await Command.sidecar(SIDECAR_NAME, args).execute();
    if (output.code !== 0) {
      throw new Error(redactSecrets(output.stderr || output.stdout || `Pairing command exited with code ${output.code}.`));
    }
    if (output.stderr) {
      appendLog(output.stderr);
    }
    appendLog(pairingSummary(output.stdout));
    form.elements.pairCode.value = "";
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
  await clearStoredToken().catch((error) => appendLog(`Reset pairing could not clear stored token: ${error.message || error}`));
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

async function stopRunner() {
  if (!childProcess) {
    return;
  }

  await childProcess.kill();
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
  executeSidecar(runtimeCommandArgs())
    .then(() => {
      llamaRuntimeReadiness = "Runtime plan checked. Review logs before explicitly installing or selecting a runtime.";
      renderLocalReadinessChecklist();
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
renderReleaseStatus().catch((error) => appendLog(`Could not render release status: ${error.message || error}`));
refreshRunnerCliVersion().catch((error) => appendLog(`Could not check Runner CLI version: ${error.message || error}`));
checkRunnerStartupSelfTest().catch((error) => appendLog(`Could not run startup self-test: ${error.message || error}`));
checkDesktopReadiness().catch((error) => appendLog(`Could not check desktop readiness: ${error.message || error}`));
restoreFormState().catch((error) => appendLog(`Could not restore pairing state: ${error.message || error}`));
setStatus("Idle", "idle");
renderLocalReadinessChecklist();
