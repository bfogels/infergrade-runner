import "./styles.css";

const SIDECAR_NAME = "binaries/infergrade-sidecar";
const API_URL_STORAGE_KEY = "infergrade.runner.apiUrl";
const THEME_STORAGE_KEY = "infergrade.runner.theme";
const APP_VERSION_FALLBACK = "0.1.13";
const UPDATE_CHANNEL = "preview";
const UPDATE_STATUS = "Updates are available in the desktop app when signed release artifacts are published.";

const form = document.querySelector("[data-runner-form]");
const startButton = document.querySelector("[data-start-runner]");
const stopButton = document.querySelector("[data-stop-runner]");
const pairButton = document.querySelector("[data-pair-runner]");
const saveTokenButton = document.querySelector("[data-save-token]");
const clearTokenButton = document.querySelector("[data-clear-token]");
const clearLogsButton = document.querySelector("[data-clear-logs]");
const themeChoiceButtons = [...document.querySelectorAll("[data-theme-choice]")];
const runtimePlanButton = document.querySelector("[data-runtime-plan]");
const runtimeSelectExistingButton = document.querySelector("[data-runtime-select-existing]");
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
    updateChannel.textContent = `${UPDATE_CHANNEL} channel`;
  }
  if (updateStatus) {
    updateStatus.textContent = isTauriRuntime() ? "Signed update checks are available from the app." : UPDATE_STATUS;
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
    appendLog("Browser preview cannot check Tauri updates.");
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
    setUpdateStatus("Could not check updates.");
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
    form.elements.apiUrl.value = savedApiUrl;
  }

  await updateTokenState();
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
  const hasToken = Boolean(await loadStoredToken());
  if (isTauriRuntime()) {
    tokenState.textContent = hasToken
      ? "Runner token saved in the OS credential store."
      : "No token saved. Paste a paired runner token before listening for Hub jobs.";
    return;
  }

  tokenState.textContent = hasToken
    ? "Preview token held in memory until this page is closed."
    : "Preview mode does not persist tokens; the app uses the OS credential store.";
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
    appendLog(`Preview mode cannot run: infergrade ${args.join(" ")}`);
    setStatus("Preview mode", "warning");
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
  const rawApiUrl = form.elements.apiUrl.value.trim() || "http://127.0.0.1:8000";
  const parsed = new URL(rawApiUrl);
  const host = parsed.hostname.toLowerCase();
  const ipv4Octet = "(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)";
  const isLocalHttp =
    parsed.protocol === "http:" &&
    (host === "localhost" || host === "::1" || host === "[::1]" || new RegExp(`^127(?:\\.${ipv4Octet}){3}$`).test(host));
  if (parsed.protocol !== "https:" && !isLocalHttp) {
    throw new Error("Hub URL must use HTTPS, except local development URLs on localhost or 127.x.x.x.");
  }
  return parsed.href;
}

function runtimeCommandArgs(extraArgs = []) {
  const runtimeId = form.elements.runtimeId?.value.trim();
  const args = ["install-runtime", "--runtime", "llama.cpp"];
  if (runtimeId) {
    args.push("--runtime-id", runtimeId);
  }
  return [...args, ...extraArgs];
}

async function startRunner() {
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
    setStatus("Preview mode", "warning");
    appendLog("Tauri runtime not detected. Browser preview cannot start the Runner sidecar.");
    startButton.disabled = false;
    return;
  }

  const command = Command.sidecar(SIDECAR_NAME, ["start", "--api-url", apiUrl], {
    env: await runnerEnvironment()
  });

  command.stdout.on("data", (line) => appendLog(line));
  command.stderr.on("data", (line) => appendLog(line));
  command.on("close", (event) => {
    appendLog(`Runner exited with code ${event.code ?? "unknown"}.`);
    childProcess = null;
    startButton.disabled = false;
    stopButton.disabled = true;
    setStatus("Stopped", event.code === 0 ? "idle" : "error");
  });
  command.on("error", (error) => {
    appendLog(`Runner sidecar error: ${error}`);
    childProcess = null;
    startButton.disabled = false;
    stopButton.disabled = true;
    setStatus("Failed", "error");
  });

  childProcess = await command.spawn();
  stopButton.disabled = false;
  setStatus("Listening", "good");
  appendLog(`Started infergrade listener for ${apiUrl}.`);
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
    setStatus("Preview mode", "warning");
    pairState.textContent = "Browser preview cannot redeem pairing codes. Open the desktop app to pair this machine.";
    appendLog("Tauri runtime not detected. Desktop pairing needs the Runner sidecar.");
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
    await startRunner();
    pairState.textContent = "Paired and listening for Hub jobs.";
  } finally {
    pairButton.disabled = false;
    if (!childProcess) {
      startButton.disabled = false;
    }
  }
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
    pairState.textContent = "Pairing failed. Check that the code has not expired, then try again.";
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
    .catch((error) => appendLog(`Could not save token: ${error.message || error}`));
});

clearTokenButton.addEventListener("click", () => {
  clearStoredToken()
    .then(() => {
      form.elements.hubToken.value = "";
      return updateTokenState();
    })
    .catch((error) => appendLog(`Could not clear token: ${error.message || error}`));
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
  executeSidecar(runtimeCommandArgs()).catch((error) => {
    setStatus("Runtime check failed", "error");
    appendLog(`Could not inspect llama.cpp runtime plan: ${error.message || error}`);
  });
});

runtimeSelectExistingButton?.addEventListener("click", () => {
  executeSidecar(runtimeCommandArgs(["--select-existing"])).catch((error) => {
    setStatus("Runtime selection failed", "error");
    appendLog(`Could not select installed llama.cpp runtime: ${error.message || error}`);
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
restoreFormState().catch((error) => appendLog(`Could not restore pairing state: ${error.message || error}`));
setStatus("Idle", "idle");
