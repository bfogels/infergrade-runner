import "./styles.css";
import packageInfo from "../package.json";
import {
  firstRunHandoffFromDeepLink,
  firstRunHandoffFromParams,
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
const startButtons = [...document.querySelectorAll("[data-start-runner]")];
const stopButtons = [...document.querySelectorAll("[data-stop-runner]")];
const pairButton = document.querySelector("[data-pair-runner]");
const resetPairingButtons = [...document.querySelectorAll("[data-reset-pairing]")];
const clearLogsButton = document.querySelector("[data-clear-logs]");
const themeChoiceButtons = [...document.querySelectorAll("[data-theme-choice]")];
const runtimePlanButton = document.querySelector("[data-runtime-plan]");
const runtimeInstallManagedButton = document.querySelector("[data-runtime-install-managed]");
const runtimeReinstallManagedButton = document.querySelector("[data-runtime-reinstall-managed]");
const runtimeRemoveSelectedButton = document.querySelector("[data-runtime-remove-selected]");
const runtimeSelectExistingButton = document.querySelector("[data-runtime-select-existing]");
const refreshModelCacheButton = document.querySelector("[data-refresh-model-cache]");
const clearModelCacheButton = document.querySelector("[data-clear-model-cache]");
const downloadStarterGgufButton = document.querySelector("[data-download-starter-gguf]");
const runtimeIdInput = document.querySelector('[name="runtimeId"]');
const firstRunModelPathInput = document.querySelector('[name="firstRunModelPath"]');
const firstRunRuntimePathInput = document.querySelector('[name="firstRunRuntimePath"]');
const firstRunUploadRunIdInput = document.querySelector('[name="firstRunUploadRunId"]');
const firstRunUploadWorkerIdInput = document.querySelector('[name="firstRunUploadWorkerId"]');
const firstRunStartButton = document.querySelector("[data-first-run-start]");
const firstRunAgainButton = document.querySelector("[data-first-run-again]");
const firstRunAnotherModelButton = document.querySelector("[data-first-run-another-model]");
const retryFirstRunUploadButton = document.querySelector("[data-retry-first-run-upload]");
const copyArtifactPathButton = document.querySelector("[data-copy-artifact-path]");
const copySupportSummaryButton = document.querySelector("[data-copy-support-summary]");
const firstRunStatus = document.querySelector("[data-first-run-status]");
const firstRunHandoffStatus = document.querySelector("[data-first-run-handoff-status]");
const runnerSelfTestButton = document.querySelector("[data-runner-self-test]");
const checkUpdateButton = document.querySelector("[data-check-update]");
const installUpdateButton = document.querySelector("[data-install-update]");
const relaunchUpdateButton = document.querySelector("[data-relaunch-update]");
const readinessCheckButton = document.querySelector("[data-readiness-check]");
const openHubButtons = [...document.querySelectorAll("[data-open-hub]")];
const viewLogsButton = document.querySelector("[data-view-logs]");
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
const modelCacheStatus = document.querySelector("[data-model-cache-status]");
const modelCacheList = document.querySelector("[data-model-cache-list]");
const modelPathStatus = document.querySelector("[data-model-path-status]");
const firstRunStepNodes = new Map(
  [...document.querySelectorAll("[data-first-run-step]")].map((node) => [node.dataset.firstRunStep, node])
);
const statusText = document.querySelector("[data-runner-status]");
const statusDot = document.querySelector("[data-status-dot]");
const pairState = document.querySelector("[data-pair-state]");
const tokenState = document.querySelector("[data-token-state]");
const logOutput = document.querySelector("[data-log-output]");
const primaryStateTitle = document.querySelector("[data-primary-state-title]");
const primaryStateMessage = document.querySelector("[data-primary-state-message]");
const hubUrlDisplay = document.querySelector("[data-hub-url-display]");
const readinessFacts = new Map(
  [...document.querySelectorAll("[data-readiness-fact]")].map((node) => [node.dataset.readinessFact, node])
);
const backendRuntimeStatus = document.querySelector("[data-backend-runtime-status]");
const backendTokenStatus = document.querySelector("[data-backend-token-status]");
const backendReconnectStatus = document.querySelector("[data-backend-reconnect-status]");
const backendContainerStatus = document.querySelector("[data-backend-container-status]");
const supportDetails = document.querySelector("[data-support-details]");
const logDisclosure = document.querySelector(".log-disclosure");
const lastCheckLabel = document.querySelector("[data-last-check-label]");
const listenerTitle = document.querySelector("[data-listener-title]");
const listenerMessage = document.querySelector("[data-listener-message]");
const listenerStatusMark = document.querySelector("[data-listener-status-mark]");
const assignmentPanel = document.querySelector("[data-assignment-panel]");
const assignmentKicker = document.querySelector("[data-assignment-kicker]");
const assignmentTitle = document.querySelector("[data-assignment-title]");
const assignmentDescription = document.querySelector("[data-assignment-description]");
const assignmentProgressWrap = document.querySelector("[data-assignment-progress-wrap]");
const assignmentPhase = document.querySelector("[data-assignment-phase]");
const assignmentTime = document.querySelector("[data-assignment-time]");
const assignmentProgressBar = document.querySelector("[data-assignment-progress-bar]");
const assignmentCheck = document.querySelector("[data-assignment-check]");

let childProcess = null;
let logLines = [];
let tauriInvoke = null;
let tauriListen = null;
let runnerListenerEventsReady = false;
let firstRunEventsReady = false;
let runnerStartupLines = [];
let runnerStartupWaiters = [];
let pendingUpdate = null;
let lastNormalizedApiUrl = "https://api.infergrade.com/";
let llamaRuntimeReadiness = "Inspect the plan before running local llama.cpp jobs.";
let nativeSuiteReadiness = "Run a readiness check to verify local execution for Hub-assigned work.";
let containerRuntimeReadiness = "Docker and Podman only unlock advanced sandboxed benchmarks.";
let modelPathReadiness = "Hub assigns model artifacts when work is queued.";
let llamaRuntimeAvailable = false;
let savedTokenAvailable = false;
let runnerProfileAvailable = false;
let lastFirstRunPayload = null;
let lastReadinessCheckAt = null;
let assignmentStartedAt = null;
let assignmentClockTimer = null;
let currentAssignmentRemaining = "";
let currentAssignmentRunId = "";
let currentAssignmentPhase = "idle";
let currentHandoffRunId = "";
let currentHandoffWorkerId = "";
let previewStateApplied = false;

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

function displayHubUrl() {
  try {
    const url = new URL(lastNormalizedApiUrl);
    if (url.hostname === "api.infergrade.com") {
      return "infergrade.com";
    }
    return url.host || lastNormalizedApiUrl;
  } catch (_error) {
    return lastNormalizedApiUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
  }
}

function hubWebUrl(target = "home") {
  try {
    const url = new URL(lastNormalizedApiUrl);
    const base = url.hostname === "api.infergrade.com" ? "https://infergrade.com/" : `${url.origin}/`;
    const hubUrl = new URL(base);
    if (target === "setup") {
      hubUrl.searchParams.set("tab", "setup");
    } else if (target === "assignment") {
      hubUrl.searchParams.set("tab", "runs");
      if (currentAssignmentRunId) {
        hubUrl.searchParams.set("run_id", currentAssignmentRunId);
      }
    }
    return hubUrl.toString();
  } catch (_error) {
    if (target === "setup") {
      return "https://infergrade.com/?tab=setup";
    }
    if (target === "assignment") {
      return currentAssignmentRunId
        ? `https://infergrade.com/?tab=runs&run_id=${encodeURIComponent(currentAssignmentRunId)}`
        : "https://infergrade.com/?tab=runs";
    }
    return "https://infergrade.com/";
  }
}

function setReadinessFact(name, label, state = "ready") {
  const node = readinessFacts.get(name);
  if (!node) {
    return;
  }
  node.textContent = label;
  node.dataset.state = state;
}

function setRunnerButtonsDisabled(kind, disabled) {
  const buttons = kind === "start" ? startButtons : stopButtons;
  buttons.forEach((button) => {
    button.disabled = disabled;
  });
}

function pairedForUi() {
  return savedTokenAvailable && runnerProfileAvailable;
}

function renderHubDisplay() {
  if (hubUrlDisplay) {
    hubUrlDisplay.textContent = displayHubUrl();
  }
}

function renderLastCheckLabel() {
  if (!lastCheckLabel) {
    return;
  }
  if (!lastReadinessCheckAt) {
    lastCheckLabel.textContent = "Last check pending";
    return;
  }
  const seconds = Math.max(0, Math.round((Date.now() - lastReadinessCheckAt.getTime()) / 1000));
  lastCheckLabel.textContent = seconds < 90 ? `Last check ${seconds}s ago` : `Last check ${lastReadinessCheckAt.toLocaleTimeString()}`;
}

function renderPrimaryReadiness() {
  const paired = pairedForUi();
  const listening = Boolean(childProcess);
  const verified = paired && listening && llamaRuntimeAvailable;
  document.documentElement.dataset.paired = paired ? "true" : "false";
  document.documentElement.dataset.listening = listening ? "true" : "false";
  renderHubDisplay();
  setReadinessFact("hub", paired ? "Hub paired" : "Pair with Hub", paired ? "ready" : "blocked");
  setReadinessFact("runtime", llamaRuntimeAvailable ? "Metal ready" : "Runtime check needed", llamaRuntimeAvailable ? "ready" : "warning");
  setReadinessFact("token", savedTokenAvailable ? "Token secure" : "Token missing", savedTokenAvailable ? "ready" : "blocked");
  if (primaryStateTitle) {
    primaryStateTitle.textContent = verified ? "Ready" : paired ? listening ? "Listening" : "Listening paused" : "Connect this machine";
  }
  if (primaryStateMessage) {
    primaryStateMessage.textContent = verified
      ? "Connected to Hub. Backend verified. Waiting for assigned work."
      : paired && listening
        ? "Connected to Hub. Run a readiness check to verify the local backend before assigned work starts."
      : paired
        ? "Paired with Hub. Start listening when this machine should accept assigned work."
      : "Pair with Hub using a one-time code before this Runner accepts assigned work.";
  }
  if (listenerTitle) {
    listenerTitle.textContent = listening ? "Listening for Hub" : "Listening paused";
  }
  if (listenerMessage) {
    listenerMessage.textContent = listening
      ? "This machine can receive Hub-assigned runs. Keep the app open while work is active."
      : "Pairing is saved. Start listening when this machine should accept Hub-assigned work.";
  }
  if (listenerStatusMark) {
    listenerStatusMark.dataset.state = listening ? "listening" : "paused";
  }
  if (backendRuntimeStatus) {
    backendRuntimeStatus.textContent = llamaRuntimeAvailable ? "ready" : "check";
  }
  if (backendTokenStatus) {
    backendTokenStatus.textContent = savedTokenAvailable ? "secure" : "missing";
  }
  if (backendReconnectStatus) {
    backendReconnectStatus.textContent = paired ? "ready" : "after pair";
  }
  if (backendContainerStatus) {
    const lowered = containerRuntimeReadiness.toLowerCase();
    backendContainerStatus.textContent = lowered.includes("detected") || lowered.includes("found") ? "ready" : "optional";
  }
  renderLastCheckLabel();
}

function formatElapsed(startedAt = assignmentStartedAt) {
  if (!startedAt) {
    return "Elapsed 0:00";
  }
  const elapsedSeconds = Math.max(0, Math.round((Date.now() - startedAt.getTime()) / 1000));
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = String(elapsedSeconds % 60).padStart(2, "0");
  return `Elapsed ${minutes}:${seconds}`;
}

function renderAssignmentTime() {
  if (!assignmentTime) {
    return;
  }
  assignmentTime.textContent = currentAssignmentRemaining
    ? `${formatElapsed()} · ${currentAssignmentRemaining} remaining`
    : formatElapsed();
}

function stopAssignmentClock() {
  if (assignmentClockTimer) {
    window.clearInterval(assignmentClockTimer);
    assignmentClockTimer = null;
  }
}

function startAssignmentClock() {
  if (assignmentClockTimer || !assignmentStartedAt || !assignmentTime) {
    return;
  }
  assignmentClockTimer = window.setInterval(() => {
    if (assignmentPanel?.dataset.state !== "active" || currentAssignmentPhase === "Complete") {
      stopAssignmentClock();
      return;
    }
    renderAssignmentTime();
  }, 1000);
}

function formatBytes(value = 0) {
  const bytes = Number(value) || 0;
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${Math.round(bytes / 1024 / 1024)} MB`;
  }
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function renderAssignmentIdle() {
  if (!assignmentPanel) {
    return;
  }
  assignmentPanel.dataset.state = "idle";
  assignmentStartedAt = null;
  currentAssignmentRemaining = "";
  currentAssignmentRunId = "";
  currentAssignmentPhase = "idle";
  stopAssignmentClock();
  if (assignmentKicker) {
    assignmentKicker.textContent = "Assigned by Hub";
  }
  if (assignmentTitle) {
    assignmentTitle.textContent = "No Hub assignment";
  }
  if (assignmentDescription) {
    assignmentDescription.textContent = "Hub will send work here when a run is queued for this machine.";
  }
  if (assignmentProgressWrap) {
    assignmentProgressWrap.hidden = true;
  }
}

function renderAssignmentActive({
  title = "Hub-assigned run",
  phase = "Preparing",
  description = "Assigned by Hub. Runner is preparing local execution.",
  progress = 12,
  checkName = "",
  startedAt = null,
  remaining = "",
  runId = "",
} = {}) {
  if (!assignmentPanel) {
    return;
  }
  assignmentPanel.dataset.state = "active";
  assignmentStartedAt = startedAt || assignmentStartedAt || new Date();
  currentAssignmentRemaining = remaining;
  currentAssignmentRunId = runId || currentAssignmentRunId;
  currentAssignmentPhase = phase;
  if (assignmentKicker) {
    assignmentKicker.textContent = "Active assignment";
  }
  if (assignmentTitle) {
    assignmentTitle.textContent = title;
  }
  if (assignmentDescription) {
    assignmentDescription.textContent = description;
  }
  if (assignmentProgressWrap) {
    assignmentProgressWrap.hidden = false;
  }
  if (assignmentPhase) {
    assignmentPhase.textContent = phase;
  }
  renderAssignmentTime();
  if (phase === "Complete") {
    stopAssignmentClock();
  } else {
    startAssignmentClock();
  }
  if (assignmentProgressBar) {
    const boundedProgress = Math.max(0, Math.min(100, Number(progress) || 0));
    assignmentProgressBar.style.width = `${boundedProgress}%`;
  }
  if (assignmentCheck) {
    assignmentCheck.hidden = !checkName;
    assignmentCheck.textContent = checkName ? `Current check: ${checkName}` : "";
  }
}

function renderAssignmentFromHandoff() {
  const runId = currentFirstRunUploadRunId();
  if (!runId) {
    renderAssignmentIdle();
    return;
  }
  if (currentAssignmentRunId === runId && currentAssignmentPhase !== "idle" && currentAssignmentPhase !== "Handoff received") {
    return;
  }
  renderAssignmentActive({
    title: `Hub run ${runId}`,
    phase: "Handoff received",
    description: "Hub opened this Runner for an assigned run. The listener will update this when it claims work.",
    progress: 6,
    checkName: "Waiting for listener claim",
    runId,
  });
}

function applyPreviewStateFromUrl() {
  if (isTauriRuntime() || previewStateApplied) {
    return;
  }
  const params = new URLSearchParams(window.location.search || "");
  const mockState = params.get("mock_state");
  const mockAssignment = params.get("mock_assignment");
  const openDetails = params.get("open_details") === "1";
  if (openDetails && supportDetails) {
    supportDetails.open = true;
  }
  if (!mockState && !mockAssignment) {
    return;
  }
  previewStateApplied = true;
  if (mockState === "ready" || mockAssignment === "active") {
    savedTokenAvailable = true;
    runnerProfileAvailable = true;
    childProcess = { preview: true };
    setRunnerButtonsDisabled("start", true);
    setRunnerButtonsDisabled("stop", false);
    llamaRuntimeAvailable = true;
    llamaRuntimeReadiness = "Managed Metal runtime verified.";
    nativeSuiteReadiness = "Backend readiness check passed for local native execution.";
    containerRuntimeReadiness = "Docker not found. Native runtime checks can continue; optional sandboxed support is disabled.";
    setStatus("Listening", "good");
  } else if (mockState === "unpaired") {
    savedTokenAvailable = false;
    runnerProfileAvailable = false;
    childProcess = null;
    setRunnerButtonsDisabled("start", false);
    setRunnerButtonsDisabled("stop", true);
    setStatus("Pairing needed", "warning");
  }
  if (mockAssignment === "active") {
    if (firstRunUploadRunIdInput && !firstRunUploadRunIdInput.value.trim()) {
      firstRunUploadRunIdInput.value = "run_preview_assignment";
    }
    renderAssignmentActive({
      title: "Hub run run_preview_assignment",
      phase: "Running",
      description: "Runner is processing Hub-assigned work.",
      progress: 48,
      checkName: "llama.cpp readiness check",
      remaining: "about 6 min",
      runId: "run_preview_assignment",
    });
  } else {
    renderAssignmentFromHandoff();
  }
  renderLocalReadinessChecklist();
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
    } else if (savedTokenAvailable && runnerProfileAvailable) {
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
  renderFirstRunChecklist();
  renderPrimaryReadiness();
}

function renderModelCache(payload = null) {
  const artifacts = Array.isArray(payload?.artifacts) ? payload.artifacts : [];
  const count = Number(payload?.artifact_count ?? artifacts.length) || 0;
  const bytes = Number(payload?.artifact_bytes) || 0;
  if (modelCacheStatus) {
    modelCacheStatus.textContent = count
      ? `${count} cached model${count === 1 ? "" : "s"} using ${formatBytes(bytes)}.`
      : "No cached model artifacts.";
  }
  if (!modelCacheList) {
    return;
  }
  modelCacheList.replaceChildren();
  artifacts.slice(0, 5).forEach((artifact) => {
    const item = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = artifact.name || "Cached model";
    const size = document.createElement("em");
    size.textContent = formatBytes(artifact.size_bytes);
    item.append(name, size);
    modelCacheList.append(item);
  });
  if (artifacts.length > 5) {
    const item = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = `${artifacts.length - 5} more cached model${artifacts.length - 5 === 1 ? "" : "s"}`;
    item.append(name);
    modelCacheList.append(item);
  }
}

async function refreshModelCache() {
  if (modelCacheStatus) {
    modelCacheStatus.textContent = "Checking local model cache...";
  }
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    renderModelCache({ artifact_count: 0, artifact_bytes: 0, artifacts: [] });
    if (modelCacheStatus) {
      modelCacheStatus.textContent = "Open the desktop app to inspect cached models.";
    }
    return null;
  }
  const payload = await invoke("desktop_model_cache_status");
  renderModelCache(payload);
  return payload;
}

async function clearModelCache() {
  if (!window.confirm("Clear cached model artifacts downloaded by InferGrade? Active downloads are left alone.")) {
    return null;
  }
  if (clearModelCacheButton) {
    clearModelCacheButton.disabled = true;
  }
  try {
    const invoke = await loadTauriInvoke();
    if (!invoke) {
      if (modelCacheStatus) {
        modelCacheStatus.textContent = "Open the desktop app to clear cached models.";
      }
      return null;
    }
    const payload = await invoke("clear_desktop_model_cache");
    renderModelCache(payload.status);
    appendLog(`Cleared ${payload.removed_count || 0} cached model artifact(s), ${formatBytes(payload.removed_bytes)}.`);
    return payload;
  } finally {
    if (clearModelCacheButton) {
      clearModelCacheButton.disabled = false;
    }
  }
}

function setFirstRunStep(name, state, message) {
  const node = firstRunStepNodes.get(name);
  if (!node) {
    return;
  }
  node.dataset.state = state;
  const detail = node.querySelector("span");
  if (detail) {
    detail.textContent = message;
  }
}

function currentFirstRunModelPath() {
  return firstRunModelPathInput?.value.trim() || "";
}

function currentFirstRunUploadRunId() {
  return firstRunUploadRunIdInput?.value.trim() || currentHandoffRunId || "";
}

function hasSelectedModelPath() {
  return currentFirstRunModelPath().toLowerCase().endsWith(".gguf");
}

function renderFirstRunChecklist() {
  const paired = savedTokenAvailable && runnerProfileAvailable;
  const modelSelected = hasSelectedModelPath();
  const localRunComplete = Boolean(lastFirstRunPayload?.artifact?.path && lastFirstRunPayload?.bundle_artifact?.path);
  const uploadSucceeded = lastFirstRunPayload?.upload?.uploaded === true;
  const uploadFailed = Boolean(lastFirstRunPayload?.upload?.error);
  const uploadReady = localRunComplete && Boolean(currentFirstRunUploadRunId()) && !uploadSucceeded;
  const firstRunReady = paired && llamaRuntimeAvailable && modelSelected;

  setFirstRunStep(
    "paired",
    paired ? "done" : "current",
    paired ? "Paired through the OS credential store. Tokens stay out of this browser UI." : "Paste a Hub pairing code to save this machine."
  );
  setFirstRunStep(
    "runtime",
    llamaRuntimeAvailable ? "done" : paired ? "current" : "blocked",
    llamaRuntimeAvailable ? "A local llama.cpp runtime is selected." : "Install the recommended runtime or select an existing llama.cpp binary."
  );
  setFirstRunStep(
    "model",
    modelSelected ? "done" : llamaRuntimeAvailable ? "current" : "blocked",
    modelSelected ? `Selected model: ${currentFirstRunModelPath()}` : "Select a local GGUF model before running."
  );
  setFirstRunStep(
    "ready",
    firstRunReady ? "done" : "blocked",
    firstRunReady ? "Ready to run a local smoke benchmark." : "Pairing, runtime, and a GGUF model are required before running."
  );
  setFirstRunStep(
    "result",
    uploadSucceeded ? "done" : uploadReady || uploadFailed || localRunComplete ? "current" : "blocked",
    uploadSucceeded
      ? `Uploaded bundle ${lastFirstRunPayload.upload.bundle_id} to Hub run ${lastFirstRunPayload.upload.run_id}.`
      : uploadReady
        ? `Local evidence is ready to upload to Hub run ${currentFirstRunUploadRunId()}.`
        : uploadFailed
          ? "Local evidence is saved; retry upload after fixing pairing or run access."
          : localRunComplete
            ? "Local evidence is saved. Hub upload can happen from a handoff or support flow."
            : "Run the assigned local smoke to create evidence."
  );
}

function renderDesktopReadiness(payload = {}) {
  if (!payload.status) {
    llamaRuntimeAvailable = false;
    nativeSuiteReadiness = "Open the desktop app to verify local execution readiness.";
    containerRuntimeReadiness = "Open the desktop app to check Docker/Podman. Docker is optional advanced support.";
    renderLocalReadinessChecklist();
    return;
  }
  lastReadinessCheckAt = new Date();
  nativeSuiteReadiness =
    payload.native_benchmark_message ||
    "Local execution readiness is available for Hub-assigned work.";
  const runtime = payload.llama_cpp_runtime || "";
  const runtimeMessage = payload.llama_cpp_message || "";
  if (runtime === "available") {
    llamaRuntimeAvailable = true;
    llamaRuntimeReadiness = runtimeMessage || "Native llama.cpp runtime is available.";
  } else if (runtime === "missing") {
    llamaRuntimeAvailable = false;
    llamaRuntimeReadiness = runtimeMessage || "Select or install a native llama.cpp runtime before assigned local work.";
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
        : "Docker not found. Select a native runtime before assigned local work; advanced sandboxed benchmarks are disabled.";
  }
  renderLocalReadinessChecklist();
}

function parseDesktopReadinessOutput(stdout) {
  const trimmed = (stdout || "").trim();
  if (!trimmed) {
    return {};
  }
  if (!trimmed.startsWith("{")) {
    return {
      status: "fallback",
      runner_core_message: trimmed,
      native_benchmark_message: nativeSuiteReadiness,
      llama_cpp_message: llamaRuntimeReadiness,
      container_message: containerRuntimeReadiness,
    };
  }
  return JSON.parse(trimmed);
}

async function refreshRunnerCliVersion() {
  const output = await runDesktopSidecarDiagnostic(["--version"]);
  if (!output) {
    renderRunnerCliVersion("available inside the desktop app");
    return;
  }

  try {
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
  const output = await runDesktopSidecarDiagnostic(["desktop-self-test"]);
  if (!output) {
    if (runtimeRunnerVersion) {
      runtimeRunnerVersion.textContent = "Startup self-test runs inside the desktop app.";
    }
    return;
  }
  try {
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
  const output = await runDesktopSidecarDiagnostic(["desktop-readiness"]);
  if (!output) {
    renderDesktopReadiness({});
    setStatus("Development view", "warning");
    return;
  }
  try {
    if (output.code !== 0) {
      throw new Error(output.stderr || output.stdout || `readiness command exited with code ${output.code}`);
    }
    const payload = parseDesktopReadinessOutput(output.stdout);
    renderDesktopReadiness(payload);
    if (payload.status === "fallback") {
      appendLog(`Desktop readiness fallback: ${payload.runner_core_message}`);
    } else {
      appendLog(`Desktop readiness: ${output.stdout.trim()}`);
    }
  } catch (error) {
    containerRuntimeReadiness = "Could not check optional Docker/Podman support. Native benchmark setup can continue.";
    appendLog(`Desktop readiness check failed: ${error.message || error}`);
    renderLocalReadinessChecklist();
  }
}

async function runReadinessCheck() {
  if (readinessCheckButton) {
    readinessCheckButton.disabled = true;
  }
  setStatus("Checking readiness", "warning");
  try {
    await checkRunnerStartupSelfTest();
    await checkDesktopReadiness();
    await inspectRuntimePlan();
    setStatus(childProcess ? "Listening" : pairedForUi() ? "Paused" : "Pairing needed", childProcess ? "good" : "warning");
    appendLog("Readiness check finished.");
  } catch (error) {
    setStatus("Needs attention", "error");
    appendLog(`Readiness check failed: ${error.message || error}`);
    throw error;
  } finally {
    if (readinessCheckButton) {
      readinessCheckButton.disabled = false;
    }
    renderLocalReadinessChecklist();
  }
}

async function openExternalUrl(url) {
  if (isTauriRuntime()) {
    const shell = await import("@tauri-apps/plugin-shell");
    await shell.open(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}

async function openHub(target = "home") {
  const url = hubWebUrl(target);
  appendLog(`Opening Hub: ${url}`);
  await openExternalUrl(url);
}

function showLogs() {
  if (supportDetails) {
    supportDetails.open = true;
    supportDetails.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }
  if (logDisclosure) {
    logDisclosure.open = true;
  }
  window.setTimeout(() => {
    logOutput?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    logOutput?.focus?.();
  }, 80);
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
  setStatus(childProcess ? "Listening" : pairedForUi() ? "Paused" : "Pairing needed", childProcess ? "good" : "warning");
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
    if (payload.type === "assignment_update" || payload.type === "assignment_idle") {
      renderAssignmentFromListenerEvent(payload);
      appendLog(
        payload.type === "assignment_idle"
          ? "No Hub assignment is currently queued for this Runner."
          : `Hub assignment ${payload.phase || "update"}: ${payload.description || payload.run_id || "work updated"}.`
      );
      return;
    }
    if (payload.type === "stdout" || payload.type === "stderr") {
      const line = String(payload.line || "");
      if (line.trim()) {
        renderAssignmentFromListenerLine(line);
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
      setRunnerButtonsDisabled("start", false);
      setRunnerButtonsDisabled("stop", true);
      setStatus("Failed", "error");
      renderLocalReadinessChecklist();
      resolveRunnerStartupWaiters(new Error(String(detail)));
      return;
    }
    if (payload.type === "terminated") {
      const code = payload.code ?? "unknown";
      appendLog(`Runner exited with code ${code}.`);
      childProcess = null;
      setRunnerButtonsDisabled("start", false);
      setRunnerButtonsDisabled("stop", true);
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
    renderAssignmentFromFirstRunEvent(payload);
    if (firstRunStatus) {
      firstRunStatus.textContent = message;
    }
    appendLog(`First-run ${payload.type || "event"}: ${message}`);
  });
}

async function clearStoredToken() {
  const invoke = await loadTauriInvoke();
  if (invoke) {
    await invoke("clear_runner_token");
  }
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
      if (tokenState) {
        if (runnerProfileAvailable && hasToken) {
          tokenState.textContent = `Runner profile and OS token saved${profile.label ? ` for ${profile.label}` : ""}.`;
        } else if (runnerProfileAvailable) {
          tokenState.textContent = `Runner profile saved${profile.label ? ` for ${profile.label}` : ""}, but the OS token is unavailable.`;
        } else if (hasToken) {
          tokenState.textContent = "Runner token is saved in the OS credential store, but no runner profile is saved.";
        } else {
          tokenState.textContent = "No runner profile saved. Paste a Hub pairing code before listening for Hub runs.";
        }
      }
      renderLocalReadinessChecklist();
      return;
    }
    hasToken = false;
  } catch (error) {
    savedTokenAvailable = false;
    runnerProfileAvailable = false;
    if (tokenState) {
      tokenState.textContent = userSafeTokenFailure(error.message || error);
    }
    appendLog(`Could not read saved token: ${error.message || error}`);
    return;
  }
  savedTokenAvailable = hasToken;
  runnerProfileAvailable = false;
  if (isTauriRuntime()) {
    if (tokenState) {
      tokenState.textContent = hasToken
        ? "Runner token saved in the OS credential store."
        : "No token saved. Pair with a Hub one-time code before listening for Hub runs.";
    }
    if (hasToken && pairingReadinessStatus) {
      pairingReadinessStatus.textContent = "Pairing token is saved. Start listening when ready.";
    }
    return;
  }

  if (tokenState) {
    tokenState.textContent = hasToken
      ? "Runner token is available."
      : "Development view does not persist tokens; the app uses the OS credential store.";
  }
}

function setStatus(status, tone = "idle") {
  if (statusText) {
    statusText.textContent = status;
  }
  if (statusDot) {
    statusDot.dataset.tone = tone;
  }
  renderPrimaryReadiness();
}

function redactSecrets(message) {
  return String(message || "")
    .replace(/\bigrp_[^\s"']+/gi, "igrp_[redacted]")
    .replace(/\bigrt_[^\s"']+/gi, "igrt_[redacted]")
    .replace(/\bqbhr_[^\s"']+/gi, "qbhr_[redacted]")
    .replace(/\bIGRP-[A-Za-z0-9-]+/g, "IGRP-[redacted]")
    .replace(/\bBearer\s+[^\s"']+/gi, "Bearer [redacted]")
    .replace(/([?&](?:token|signature|signed|x-amz-signature|x-goog-signature)=)[^&\s"']+/gi, "$1[redacted]")
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
  if (logOutput) {
    logOutput.textContent = logLines.join("\n");
    logOutput.scrollTop = logOutput.scrollHeight;
  }
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

function renderAssignmentFromFirstRunEvent(payload = {}) {
  if (payload.type === "benchmark_started") {
    renderAssignmentActive({
      title: currentFirstRunUploadRunId() ? `Hub run ${currentFirstRunUploadRunId()}` : "Local readiness smoke",
      phase: "Running",
      description: "Runner is executing local work assigned through Hub handoff.",
      progress: 18,
      checkName: "Starting native runtime",
    });
    return;
  }
  if (payload.type === "benchmark_progress") {
    const progress = Number.isFinite(payload.progress_percent) ? payload.progress_percent : 45;
    renderAssignmentActive({
      title: currentFirstRunUploadRunId() ? `Hub run ${currentFirstRunUploadRunId()}` : "Local readiness smoke",
      phase: "Running",
      description: "Runner is executing local work assigned through Hub handoff.",
      progress,
      checkName: payload.message || "Native runtime check",
    });
    return;
  }
  if (payload.type === "benchmark_completed") {
    renderAssignmentActive({
      title: currentFirstRunUploadRunId() ? `Hub run ${currentFirstRunUploadRunId()}` : "Local readiness smoke",
      phase: "Uploading",
      description: "Local execution is complete. Runner is preparing Hub upload or support artifacts.",
      progress: 86,
      checkName: "Bundle artifact",
    });
    return;
  }
  if (payload.type === "error") {
    renderAssignmentActive({
      title: currentFirstRunUploadRunId() ? `Hub run ${currentFirstRunUploadRunId()}` : "Local readiness smoke",
      phase: "Needs attention",
      description: payload.message || "Runner needs attention before this assignment can continue.",
      progress: 100,
      checkName: "See logs for recovery detail",
    });
  }
}

function renderAssignmentFromListenerEvent(payload = {}) {
  if (payload.type === "assignment_idle") {
    if (currentAssignmentPhase !== "Handoff received") {
      renderAssignmentIdle();
    }
    return;
  }
  if (payload.type !== "assignment_update") {
    return;
  }
  const phase = payload.phase || "Running";
  const runId = payload.run_id || payload.runId || "";
  renderAssignmentActive({
    title: redactSecrets(payload.title || (runId ? `Hub run ${runId}` : "Hub assignment")),
    phase,
    description: redactSecrets(payload.description || "Runner is processing Hub-assigned work."),
    progress: Number.isFinite(payload.progress) ? payload.progress : phase === "Complete" ? 100 : 32,
    checkName: redactSecrets(payload.check_name || payload.checkName || payload.stage || ""),
    remaining: redactSecrets(payload.remaining || ""),
    runId,
  });
  if (phase === "Needs attention") {
    setStatus("Needs attention", "error");
  } else if (phase === "Complete") {
    setStatus("Complete", "good");
  } else {
    setStatus("Running assignment", "warning");
  }
}

function renderAssignmentFromListenerLine(line = "") {
  const trimmed = String(line || "").trim();
  if (!trimmed) {
    return false;
  }
  const claimed = trimmed.match(/^Claimed run ([^\.\s]+)\.?/);
  if (claimed) {
    const runId = claimed[1];
    renderAssignmentActive({
      title: `Hub run ${runId}`,
      phase: "Preparing",
      description: "Runner claimed Hub-assigned work and is preparing local execution.",
      progress: 12,
      checkName: "Claim accepted",
      runId,
    });
    setStatus("Running assignment", "warning");
    return true;
  }
  const failed = trimmed.match(/^Run ([^\.\s]+) failed: (.+)$/);
  if (failed) {
    const runId = failed[1];
    renderAssignmentActive({
      title: `Hub run ${runId}`,
      phase: "Needs attention",
      description: failed[2],
      progress: 100,
      checkName: "See logs for recovery detail",
      runId,
    });
    setStatus("Needs attention", "error");
    return true;
  }
  if (trimmed.startsWith("Resolving model artifact")) {
    renderAssignmentActive({
      title: currentAssignmentRunId ? `Hub run ${currentAssignmentRunId}` : "Hub assignment",
      phase: "Downloading",
      description: "Runner is resolving the Hub-assigned model artifact.",
      progress: 24,
      checkName: "Model artifact",
      runId: currentAssignmentRunId,
    });
    setStatus("Running assignment", "warning");
    return true;
  }
  if (trimmed.startsWith("Running capability suite")) {
    renderAssignmentActive({
      title: currentAssignmentRunId ? `Hub run ${currentAssignmentRunId}` : "Hub assignment",
      phase: "Running",
      description: "Runner is executing Hub-assigned checks.",
      progress: 48,
      checkName: "Capability suite",
      runId: currentAssignmentRunId,
    });
    setStatus("Running assignment", "warning");
    return true;
  }
  const capabilityProgress = trimmed.match(/^Capability benchmark (.+?) (?:(started) \((\d+) cases\)|(\d+)\/(\d+) cases|completed(?: with degraded generation quality)?|failed(?: before evaluation produced a trustworthy score)?)\.$/);
  if (capabilityProgress) {
    const benchmarkName = capabilityProgress[1];
    const progressDetail = capabilityProgress[2]
      ? `0/${capabilityProgress[3]}`
      : capabilityProgress[4] && capabilityProgress[5]
        ? `${capabilityProgress[4]}/${capabilityProgress[5]}`
        : capabilityProgress[0].includes("failed")
          ? "failed"
          : "complete";
    renderAssignmentActive({
      title: currentAssignmentRunId ? `Hub run ${currentAssignmentRunId}` : "Hub assignment",
      phase: "Running",
      description: "Runner is executing Hub-assigned benchmark checks.",
      progress: assignmentProgressBar ? Number.parseFloat(assignmentProgressBar.style.width) || 52 : 52,
      checkName: `${benchmarkName} ${progressDetail}`,
      runId: currentAssignmentRunId,
    });
    setStatus("Running assignment", "warning");
    return true;
  }
  const deploymentProfile = trimmed.match(/^Running deployment profile (.+)\.\.\.$/);
  if (deploymentProfile) {
    renderAssignmentActive({
      title: currentAssignmentRunId ? `Hub run ${currentAssignmentRunId}` : "Hub assignment",
      phase: "Running",
      description: "Runner is executing Hub-assigned deployment checks.",
      progress: 62,
      checkName: deploymentProfile[1],
      runId: currentAssignmentRunId,
    });
    setStatus("Running assignment", "warning");
    return true;
  }
  const completed = trimmed.match(/^Completed bundle (.+)$/);
  if (completed) {
    renderAssignmentActive({
      title: currentAssignmentRunId ? `Hub run ${currentAssignmentRunId}` : "Hub assignment",
      phase: "Uploading",
      description: "Execution completed locally. Uploading results to Hub.",
      progress: 94,
      checkName: completed[1],
      runId: currentAssignmentRunId,
    });
    setStatus("Uploading", "warning");
    return true;
  }
  if (trimmed === "No matching run jobs are awaiting execution." && currentAssignmentPhase !== "Handoff received") {
    renderAssignmentIdle();
    return true;
  }
  return false;
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

async function runDesktopSidecarDiagnostic(args) {
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    return null;
  }
  return invoke("desktop_sidecar_diagnostic", { args });
}

async function executeSidecar(args) {
  const output = await runDesktopSidecarDiagnostic(args);
  if (!output) {
    appendLog(`Development view cannot run: infergrade ${args.join(" ")}`);
    setStatus("Development view", "warning");
    return null;
  }
  appendLog(`Running: infergrade ${args.join(" ")}`);
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

function credentialSourceLabel(source = "") {
  if (source === "typed_input") {
    return "typed credentials";
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
    typedTokenPresent: false,
  });
}

function readApiUrl() {
  const normalized = normalizeDesktopApiUrl(form.elements.apiUrl.value);
  form.elements.apiUrl.value = normalized;
  lastNormalizedApiUrl = normalized;
  renderHubDisplay();
  renderLocalReadinessChecklist();
  return normalized;
}

function runtimeCommandArgs(extraArgs = []) {
  const runtimeId = runtimeIdInput?.value.trim();
  const args = ["install-runtime", "--runtime", "llama.cpp"];
  if (runtimeId) {
    args.push("--runtime-id", runtimeId);
  }
  return [...args, ...extraArgs];
}

function runtimePlanSummary(plan = {}) {
  const recommended = plan.recommended_runtime || {};
  const selected = plan.selected_runtime || {};
  const selectedChannel = plan.selected_channel || {};
  const updatePolicy = plan.update_policy || {};
  const selectedText = selected.status === "selected" ? "Selected runtime is recorded." : "No managed runtime is selected yet.";
  const runtimeText = plan.message || "No install command was run. Review the runtime plan before selecting a runtime.";
  const lane = recommended.platform?.human || recommended.platform_label || recommended.platform || recommended.accelerator || "this machine";
  const channel = selectedChannel.label
    ? `Runtime channel: ${selectedChannel.label}.`
    : "";
  const update = updatePolicy.automatic_updates === false
    ? "Updates are manual."
    : "";
  return [runtimeText, `Recommended lane: ${lane}.`, selectedText, channel, update]
    .filter(Boolean)
    .join(" ");
}

function managedRuntimeInstallSummary(result = {}) {
  const selection = result.selection || {};
  const archive = selection.archive || {};
  const runtimeId = selection.runtime_id || "managed llama.cpp runtime";
  const signature = archive.independent_signature_verified
    ? "independent signature verified"
    : "no independent signature";
  return `Managed runtime selected: ${runtimeId}. SHA-256 verified; ${signature}.`;
}

function runtimeRemovalSummary(result = {}) {
  if (result.removed_selection || result.removed_managed_files) {
    return result.message || "Selected llama.cpp runtime removed. Install or select a runtime before native first-run.";
  }
  return result.message || "No selected llama.cpp runtime was recorded. Install or select a runtime before native first-run.";
}

function setRuntimeActionDisabled(disabled) {
  if (runtimeInstallManagedButton) {
    runtimeInstallManagedButton.disabled = disabled;
  }
  if (runtimeReinstallManagedButton) {
    runtimeReinstallManagedButton.disabled = disabled;
  }
  if (runtimeRemoveSelectedButton) {
    runtimeRemoveSelectedButton.disabled = disabled;
  }
  if (runtimeSelectExistingButton) {
    runtimeSelectExistingButton.disabled = disabled;
  }
}

async function inspectRuntimePlan() {
  llamaRuntimeReadiness = "Checking the llama.cpp runtime plan...";
  renderLocalReadinessChecklist();
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    appendLog("Open the desktop app to inspect the native llama.cpp runtime plan.");
    llamaRuntimeReadiness = "Runtime plan is available inside the desktop app.";
    renderLocalReadinessChecklist();
    return null;
  }
  const plan = await invoke("llama_cpp_runtime_plan");
  llamaRuntimeReadiness = runtimePlanSummary(plan);
  renderLocalReadinessChecklist();
  appendLog(`llama.cpp runtime plan: ${JSON.stringify(plan)}`);
  return plan;
}

async function installManagedRuntime({ reinstall = false } = {}) {
  const runtimeId = runtimeIdInput?.value.trim() || null;
  llamaRuntimeReadiness = reinstall
    ? "Replacing the selected llama.cpp runtime with the managed runtime. Local binaries are not deleted."
    : "Installing the recommended llama.cpp runtime. This can take a minute...";
  renderLocalReadinessChecklist();
  setRuntimeActionDisabled(true);
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    appendLog("Open the desktop app to install the managed llama.cpp runtime.");
    llamaRuntimeReadiness = "Managed runtime install is available inside the desktop app.";
    renderLocalReadinessChecklist();
    return null;
  }
  if (reinstall) {
    const removed = await invoke("remove_selected_llama_cpp_runtime", {
      removeManagedFiles: true,
    });
    appendLog(`Cleared selected llama.cpp runtime before reinstall: ${JSON.stringify(removed)}`);
  }
  const result = await invoke("install_managed_llama_cpp_runtime", {
    runtimeId,
  });
  llamaRuntimeReadiness = managedRuntimeInstallSummary(result);
  llamaRuntimeAvailable = true;
  renderLocalReadinessChecklist();
  appendLog(`Installed managed llama.cpp runtime: ${JSON.stringify(result)}`);
  return result;
}

async function removeSelectedRuntime() {
  llamaRuntimeReadiness = "Removing the selected llama.cpp runtime record...";
  renderLocalReadinessChecklist();
  setRuntimeActionDisabled(true);
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    appendLog("Open the desktop app to remove the selected llama.cpp runtime.");
    llamaRuntimeReadiness = "Runtime removal is available inside the desktop app.";
    renderLocalReadinessChecklist();
    return null;
  }
  const result = await invoke("remove_selected_llama_cpp_runtime", {
    removeManagedFiles: true,
  });
  llamaRuntimeReadiness = runtimeRemovalSummary(result);
  llamaRuntimeAvailable = false;
  renderLocalReadinessChecklist();
  appendLog(`Removed selected llama.cpp runtime: ${JSON.stringify(result)}`);
  return result;
}

function readFirstRunModelPath() {
  const modelPath = currentFirstRunModelPath();
  if (!modelPath) {
    throw new Error("Select a local GGUF model file before running assigned local work.");
  }
  if (!modelPath.toLowerCase().endsWith(".gguf")) {
    throw new Error("Use a local GGUF model file for assigned local work.");
  }
  modelPathReadiness = `First-run model selected: ${modelPath}`;
  renderLocalReadinessChecklist();
  return modelPath;
}

function readFirstRunRuntimePath() {
  return firstRunRuntimePathInput?.value.trim() || null;
}

async function downloadStarterGguf() {
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    throw new Error("Open the desktop app to download the starter model.");
  }
  if (downloadStarterGgufButton) {
    downloadStarterGgufButton.disabled = true;
    downloadStarterGgufButton.textContent = "Downloading...";
  }
  modelPathReadiness = "Downloading the starter GGUF into InferGrade's local cache...";
  renderLocalReadinessChecklist();
  const result = await invoke("download_starter_gguf");
  const modelPath = String(result?.path || "").trim();
  if (!modelPath) {
    throw new Error("Starter model download did not return a local path.");
  }
  if (firstRunModelPathInput) {
    firstRunModelPathInput.value = modelPath;
  }
  modelPathReadiness = `Starter model ready: ${modelPath}`;
  renderLocalReadinessChecklist();
  appendLog(`Starter GGUF ready: ${JSON.stringify(result)}`);
  return result;
}

function firstRunHandoffFromUrl() {
  return firstRunHandoffFromParams(new URLSearchParams(window.location.search || ""), (reason) => {
    appendLog(`Ignored first-run handoff with ${reason}.`);
  });
}

function firstRunHandoffFromDeepLinks(urls) {
  const values = Array.isArray(urls) ? urls : [];
  for (const value of values) {
    const handoff = firstRunHandoffFromDeepLink(value, (reason) => {
      appendLog(`Ignored first-run handoff with ${reason}.`);
    });
    if (handoff.runId) {
      return handoff;
    }
  }
  return { runId: "", workerId: "" };
}

function applyFirstRunHandoff(incomingHandoff = null) {
  const urlHandoff = incomingHandoff || firstRunHandoffFromUrl();
  const storedRunId = window.localStorage.getItem(FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY) || "";
  const storedWorkerId = window.localStorage.getItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY) || "";
  const runId = urlHandoff.runId || storedRunId;
  const workerId = urlHandoff.runId ? urlHandoff.workerId : storedWorkerId;
  currentHandoffRunId = runId;
  currentHandoffWorkerId = workerId;
  if (runId && firstRunUploadRunIdInput && !firstRunUploadRunIdInput.value.trim()) {
    firstRunUploadRunIdInput.value = runId;
  }
  if (workerId && firstRunUploadWorkerIdInput && !firstRunUploadWorkerIdInput.value.trim()) {
    firstRunUploadWorkerIdInput.value = workerId;
  }
  if (urlHandoff.runId) {
    window.localStorage.setItem(FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY, urlHandoff.runId);
    if (urlHandoff.workerId) {
      window.localStorage.setItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY, urlHandoff.workerId);
    } else {
      window.localStorage.removeItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY);
      if (firstRunUploadWorkerIdInput) {
        firstRunUploadWorkerIdInput.value = "";
      }
    }
  }
  if (firstRunHandoffStatus) {
    firstRunHandoffStatus.textContent = runId
      ? `Ready to upload this first-run result to Hub run ${runId}.`
      : "If Hub opened Desktop with a run handoff, this fills automatically.";
  }
  renderAssignmentFromHandoff();
  renderLocalReadinessChecklist();
}

async function initFirstRunDeepLinkHandoff() {
  applyFirstRunHandoff();
  if (!isTauriRuntime()) {
    return;
  }
  try {
    const { getCurrent, onOpenUrl } = await import("@tauri-apps/plugin-deep-link");
    const startHandoff = firstRunHandoffFromDeepLinks(await getCurrent());
    if (startHandoff.runId) {
      applyFirstRunHandoff(startHandoff);
      appendLog(`Received Hub first-run handoff for run ${startHandoff.runId}.`);
    }
    await onOpenUrl((urls) => {
      const handoff = firstRunHandoffFromDeepLinks(urls);
      if (!handoff.runId) {
        return;
      }
      applyFirstRunHandoff(handoff);
      setStatus("Hub run handoff received", "good");
      appendLog(`Received Hub first-run handoff for run ${handoff.runId}.`);
    });
  } catch (error) {
    appendLog(`Could not initialize Hub first-run handoff links: ${error.message || error}`);
  }
}

function readFirstRunUploadRunId() {
  const runId = currentFirstRunUploadRunId();
  if (runId) {
    window.localStorage.setItem(FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY, runId);
  }
  return runId || null;
}

function readFirstRunUploadWorkerId() {
  const workerId = firstRunUploadWorkerIdInput?.value.trim() || currentHandoffWorkerId || "";
  if (workerId) {
    window.localStorage.setItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY, workerId);
  }
  return workerId || null;
}

function clearFirstRunHandoff() {
  window.localStorage.removeItem(FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY);
  window.localStorage.removeItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY);
  currentHandoffRunId = "";
  currentHandoffWorkerId = "";
  if (firstRunUploadRunIdInput) {
    firstRunUploadRunIdInput.value = "";
  }
  if (firstRunUploadWorkerIdInput) {
    firstRunUploadWorkerIdInput.value = "";
  }
  if (firstRunHandoffStatus) {
    firstRunHandoffStatus.textContent = "Hub upload complete. Start another run from Hub when you want to add more evidence.";
  }
  renderAssignmentIdle();
}

function firstRunArtifactText(payload = lastFirstRunPayload) {
  const paths = [
    payload?.artifact?.path,
    payload?.bundle_artifact?.path,
  ].filter(Boolean);
  return paths.join("\n");
}

function updateFirstRunSupportActions() {
  const hasArtifact = Boolean(firstRunArtifactText());
  if (firstRunAgainButton) {
    firstRunAgainButton.disabled = !lastFirstRunPayload;
  }
  if (firstRunAnotherModelButton) {
    firstRunAnotherModelButton.disabled = !lastFirstRunPayload && !currentFirstRunModelPath();
  }
  if (copyArtifactPathButton) {
    copyArtifactPathButton.disabled = !hasArtifact;
  }
  if (retryFirstRunUploadButton) {
    const uploaded = lastFirstRunPayload?.upload?.uploaded === true;
    retryFirstRunUploadButton.disabled = !lastFirstRunPayload || uploaded;
  }
}

function clearFirstRunLocalState({ clearModel = false } = {}) {
  lastFirstRunPayload = null;
  if (clearModel && firstRunModelPathInput) {
    firstRunModelPathInput.value = "";
  }
  modelPathReadiness = currentFirstRunModelPath()
    ? `First-run model selected: ${currentFirstRunModelPath()}`
    : "Select a local GGUF model only when recovering a Hub handoff.";
  nativeSuiteReadiness = "Run a readiness check to verify local execution for Hub-assigned work.";
  if (firstRunStatus) {
    firstRunStatus.textContent = clearModel
      ? "Choose another local GGUF model before running."
      : "Ready to run this assigned local smoke again.";
  }
  updateFirstRunSupportActions();
  renderLocalReadinessChecklist();
}

async function copyTextToClipboard(text, label) {
  if (!text) {
    throw new Error(`${label} is not available yet.`);
  }
  if (!navigator.clipboard?.writeText) {
    throw new Error("Clipboard is unavailable in this view.");
  }
  await navigator.clipboard.writeText(text);
  appendLog(`${label} copied.`);
}

async function copyArtifactPath() {
  await copyTextToClipboard(firstRunArtifactText(), "Copy artifact path");
}

async function copySupportSummary() {
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    appendLog("Open the desktop app to copy a support summary.");
    return;
  }
  const payload = await invoke("desktop_support_summary", {
    firstRunArtifact: lastFirstRunPayload,
    recentErrors: logLines.slice(-8),
  });
  await copyTextToClipboard(JSON.stringify(payload, null, 2), "Copy support summary");
}

async function retryFirstRunUpload() {
  if (!lastFirstRunPayload) {
    throw new Error("Retry upload requires completed local assigned work.");
  }
  const uploadRunId = readFirstRunUploadRunId() || lastFirstRunPayload?.upload?.run_id;
  if (!uploadRunId) {
    throw new Error("Enter a Hub run ID before retrying upload.");
  }
  const artifactPath = lastFirstRunPayload?.artifact?.path || "";
  const bundleArtifactPath = lastFirstRunPayload?.bundle_artifact?.path || "";
  if (!artifactPath || !bundleArtifactPath) {
    throw new Error("Retry upload requires saved local result and bundle artifacts.");
  }
  const uploadWorkerId = readFirstRunUploadWorkerId();
  const invoke = await loadTauriInvoke();
  if (!invoke) {
    appendLog("Open the desktop app to retry upload.");
    return;
  }
  retryFirstRunUploadButton.disabled = true;
  firstRunStatus.textContent = "Retrying Hub upload from the local first-run artifact...";
  const payload = await invoke("retry_desktop_native_first_run_upload", {
    artifactPath,
    bundleArtifactPath,
    uploadRunId,
    uploadWorkerId,
  });
  lastFirstRunPayload = payload;
  updateFirstRunSupportActions();
  if (payload?.upload?.uploaded) {
    firstRunStatus.textContent = `Uploaded bundle ${payload.upload.bundle_id} to Hub run ${payload.upload.run_id}.`;
    clearFirstRunHandoff();
    setStatus("First benchmark uploaded", "good");
  } else {
    firstRunStatus.textContent = `Upload failed: ${payload?.upload?.error || "unknown Hub upload error"}`;
    setStatus("Upload failed", "error");
  }
  appendLog(`Retried native first-run upload: ${JSON.stringify(payload)}`);
}

async function startRunner({ confirmStarted = false } = {}) {
  const apiUrl = readApiUrl();
  window.localStorage.setItem(API_URL_STORAGE_KEY, apiUrl);

  if (childProcess) {
    appendLog("Runner is already listening.");
    return;
  }

  setRunnerButtonsDisabled("start", true);
  setStatus("Starting", "warning");

  const invoke = await loadTauriInvoke();
  if (!invoke) {
    setStatus("Development view", "warning");
    appendLog("Open the desktop app to start the local Runner.");
    setRunnerButtonsDisabled("start", false);
    return;
  }

  await ensureRunnerListenerEvents();
  runnerStartupLines = [];
  const output = await invoke("start_runner_listener", {
    apiUrl,
    typedToken: null,
  });
  const plan = output?.plan || {};
  const runner = plan.runner_id ? ` for ${plan.runner_id}` : "";
  appendLog(
    `Runner start plan: ${plan.execution_mode || "default mode"} using ${credentialSourceLabel(plan.credential_source)}${runner}.`
  );
  childProcess = { rustManaged: true, pid: output?.pid || null };
  setRunnerButtonsDisabled("stop", false);
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
  setRunnerButtonsDisabled("start", true);
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
      setRunnerButtonsDisabled("start", false);
    }
  }
}

async function resetPairing() {
  const wasListening = Boolean(childProcess);
  if (wasListening) {
    await stopRunner();
    childProcess = null;
    setRunnerButtonsDisabled("start", false);
    setRunnerButtonsDisabled("stop", true);
  }
  form.elements.pairCode.value = "";
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
    firstRunStatus.textContent = "Open the desktop app to run assigned local work.";
    appendLog("Development view cannot run assigned local work.");
    return;
  }

  await ensureFirstRunEvents();
  firstRunStartButton.disabled = true;
  setStatus("First benchmark running", "warning");
  firstRunStatus.textContent = "Starting assigned local work...";
  try {
    const payload = await invoke("run_desktop_native_first_run", {
      modelPath,
      runtimePath,
      uploadRunId,
      uploadWorkerId,
    });
    lastFirstRunPayload = payload;
    updateFirstRunSupportActions();
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
      renderAssignmentActive({
        title: `Hub run ${payload.upload.run_id}`,
        phase: "Complete",
        description: `Uploaded bundle ${payload.upload.bundle_id} to Hub.`,
        progress: 100,
        checkName: "Upload complete",
      });
    } else {
      applyFirstRunHandoff();
      renderAssignmentActive({
        title: currentFirstRunUploadRunId() ? `Hub run ${currentFirstRunUploadRunId()}` : "Local readiness smoke",
        phase: payload?.upload?.error ? "Needs attention" : "Complete",
        description: payload?.upload?.error
          ? "Local execution completed, but Hub upload needs recovery."
          : "Local execution completed. Open Hub or support details for next steps.",
        progress: 100,
        checkName: payload?.upload?.error ? "Upload recovery" : "Local artifact ready",
      });
    }
    setStatus("First benchmark complete", "good");
    renderLocalReadinessChecklist();
    appendLog(`Native first-run result: ${JSON.stringify(payload)}`);
  } catch (error) {
    const message = error.message || error;
    firstRunStatus.textContent = `Native first-run failed: ${message}`;
    setStatus("First benchmark failed", "error");
    renderAssignmentActive({
      title: currentFirstRunUploadRunId() ? `Hub run ${currentFirstRunUploadRunId()}` : "Local readiness smoke",
      phase: "Needs attention",
      description: "Local execution failed. Logs are available in Details and support.",
      progress: 100,
      checkName: "Failure recovery",
    });
    appendLog(`Native first-run failed: ${message}`);
  } finally {
    firstRunStartButton.disabled = false;
    updateFirstRunSupportActions();
  }
}

async function stopRunner() {
  if (!childProcess) {
    return;
  }

  if (childProcess.preview) {
    childProcess = null;
    setRunnerButtonsDisabled("start", false);
    setRunnerButtonsDisabled("stop", true);
    setStatus("Paused", "warning");
    renderLocalReadinessChecklist();
    appendLog("Preview listener stopped.");
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

resetPairingButtons.forEach((button) => button.addEventListener("click", () => {
  resetPairing().catch((error) => {
    pairState.textContent = "Reset pairing could not finish. You can still paste a fresh code and try again.";
    appendLog(`Could not reset pairing: ${error.message || error}`);
  });
}));

startButtons.forEach((button) => button.addEventListener("click", () => {
  startRunner().catch((error) => {
    setStatus("Failed", "error");
    setRunnerButtonsDisabled("start", false);
    setRunnerButtonsDisabled("stop", true);
    appendLog(`Could not start Runner: ${error.message || error}`);
  });
}));

stopButtons.forEach((button) => button.addEventListener("click", () => {
  stopRunner().catch((error) => appendLog(`Could not stop Runner: ${error.message || error}`));
}));

clearLogsButton.addEventListener("click", () => {
  logLines = [];
  logOutput.textContent = "Waiting for Runner output...";
});

themeChoiceButtons.forEach((button) => {
  button.addEventListener("click", () => chooseThemeMode(button.dataset.themeChoice));
});

runtimePlanButton?.addEventListener("click", () => {
  inspectRuntimePlan().catch((error) => {
    llamaRuntimeReadiness = "Runtime plan unavailable. See logs for the technical detail.";
    renderLocalReadinessChecklist();
    setStatus("Runtime check failed", "error");
    appendLog(`Could not inspect llama.cpp runtime plan: ${error.message || error}`);
  });
});

runtimeInstallManagedButton?.addEventListener("click", () => {
  installManagedRuntime()
    .catch((error) => {
      llamaRuntimeReadiness = "Managed runtime install failed. Retry install, remove the selected runtime, or select an existing llama.cpp binary.";
      renderLocalReadinessChecklist();
      setStatus("Runtime install failed", "error");
      appendLog(`Could not install managed llama.cpp runtime: ${error.message || error}`);
    })
    .finally(() => {
      setRuntimeActionDisabled(false);
    });
});

runtimeReinstallManagedButton?.addEventListener("click", () => {
  installManagedRuntime({ reinstall: true })
    .catch((error) => {
      llamaRuntimeReadiness = "Managed runtime reinstall failed. Remove the selected runtime or select an existing llama.cpp binary.";
      renderLocalReadinessChecklist();
      setStatus("Runtime reinstall failed", "error");
      appendLog(`Could not reinstall managed llama.cpp runtime: ${error.message || error}`);
    })
    .finally(() => {
      setRuntimeActionDisabled(false);
    });
});

runtimeRemoveSelectedButton?.addEventListener("click", () => {
  removeSelectedRuntime()
    .catch((error) => {
      llamaRuntimeReadiness = "Runtime removal failed. See logs for the technical detail.";
      renderLocalReadinessChecklist();
      setStatus("Runtime removal failed", "error");
      appendLog(`Could not remove selected llama.cpp runtime: ${error.message || error}`);
    })
    .finally(() => {
      setRuntimeActionDisabled(false);
    });
});

runtimeSelectExistingButton?.addEventListener("click", () => {
  llamaRuntimeReadiness = "Looking for an installed llama.cpp runtime...";
  renderLocalReadinessChecklist();
  loadTauriInvoke()
    .then((invoke) => {
      if (!invoke) {
        appendLog("Open the desktop app to select an installed llama.cpp runtime.");
        llamaRuntimeReadiness = "Runtime selection is available inside the desktop app.";
        return null;
      }
      return invoke("select_existing_llama_cpp_runtime", {
        runtimePath: readFirstRunRuntimePath(),
      });
    })
    .then((selection) => {
      if (!selection) {
        return;
      }
      llamaRuntimeReadiness = "Installed llama.cpp runtime selected. No install command was run.";
      llamaRuntimeAvailable = true;
      renderLocalReadinessChecklist();
      appendLog(`Selected llama.cpp runtime: ${JSON.stringify(selection)}`);
    })
    .catch((error) => {
      llamaRuntimeReadiness = "No installed llama.cpp runtime selected. See logs for the technical detail.";
      renderLocalReadinessChecklist();
      setStatus("Runtime selection failed", "error");
      appendLog(`Could not select installed llama.cpp runtime: ${error.message || error}`);
    });
});

refreshModelCacheButton?.addEventListener("click", () => {
  refreshModelCache().catch((error) => {
    if (modelCacheStatus) {
      modelCacheStatus.textContent = "Could not inspect cached models.";
    }
    appendLog(`Could not inspect model cache: ${error.message || error}`);
  });
});

clearModelCacheButton?.addEventListener("click", () => {
  clearModelCache().catch((error) => {
    if (modelCacheStatus) {
      modelCacheStatus.textContent = "Could not clear cached models.";
    }
    appendLog(`Could not clear model cache: ${error.message || error}`);
  });
});

downloadStarterGgufButton?.addEventListener("click", () => {
  downloadStarterGguf()
    .then(() => {
      setStatus("Starter model ready", "good");
      if (firstRunStatus) {
        firstRunStatus.textContent = "Starter model downloaded. Run assigned local smoke when the runtime is ready.";
      }
    })
    .catch((error) => {
      const message = error.message || String(error);
      modelPathReadiness = "Starter model download failed. You can still paste a local GGUF path.";
      renderLocalReadinessChecklist();
      setStatus("Model download failed", "error");
      appendLog(`Could not download starter GGUF: ${message}`);
    })
    .finally(() => {
      if (downloadStarterGgufButton) {
        downloadStarterGgufButton.disabled = false;
        downloadStarterGgufButton.textContent = "Download starter model";
      }
      updateFirstRunSupportActions();
    });
});

firstRunModelPathInput?.addEventListener("input", () => {
  const modelPath = currentFirstRunModelPath();
  modelPathReadiness = modelPath
    ? modelPath.toLowerCase().endsWith(".gguf")
      ? `First-run model selected: ${modelPath}`
      : "Use a local GGUF model file for native first-run."
    : "Select a local GGUF model only when recovering a Hub handoff.";
  updateFirstRunSupportActions();
  renderLocalReadinessChecklist();
});

firstRunUploadRunIdInput?.addEventListener("input", () => {
  renderAssignmentFromHandoff();
  renderLocalReadinessChecklist();
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

firstRunAgainButton?.addEventListener("click", () => {
  clearFirstRunLocalState();
  runNativeFirstRun().catch((error) => {
    const message = error.message || String(error);
    if (firstRunStatus) {
      firstRunStatus.textContent = message;
    }
    setStatus("First benchmark blocked", "error");
    appendLog(`Could not rerun native first-run: ${message}`);
  });
});

firstRunAnotherModelButton?.addEventListener("click", () => {
  clearFirstRunLocalState({ clearModel: true });
  setStatus("Choose another model", "idle");
  appendLog("Cleared local first-run result state; choose another GGUF model to run.");
});

retryFirstRunUploadButton?.addEventListener("click", () => {
  retryFirstRunUpload().catch((error) => {
    const message = error.message || String(error);
    if (firstRunStatus) {
      firstRunStatus.textContent = message;
    }
    setStatus("Upload retry blocked", "error");
    appendLog(`Could not retry first-run upload: ${message}`);
    updateFirstRunSupportActions();
  });
});

copyArtifactPathButton?.addEventListener("click", () => {
  copyArtifactPath().catch((error) => appendLog(`Could not copy artifact path: ${error.message || error}`));
});

copySupportSummaryButton?.addEventListener("click", () => {
  copySupportSummary().catch((error) => appendLog(`Could not copy support summary: ${error.message || error}`));
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

readinessCheckButton?.addEventListener("click", () => {
  runReadinessCheck().catch(() => {
    if (supportDetails) {
      supportDetails.open = true;
    }
  });
});

openHubButtons.forEach((button) => {
  button.addEventListener("click", () => {
    openHub(button.dataset.hubTarget || "home").catch((error) => appendLog(`Could not open Hub: ${error.message || error}`));
  });
});

viewLogsButton?.addEventListener("click", showLogs);

initTheme();
initFirstRunDeepLinkHandoff().catch((error) => appendLog(`Could not initialize first-run handoff: ${error.message || error}`));
renderReleaseStatus().catch((error) => appendLog(`Could not render release status: ${error.message || error}`));
refreshRunnerCliVersion().catch((error) => appendLog(`Could not check Runner CLI version: ${error.message || error}`));
checkRunnerStartupSelfTest().catch((error) => appendLog(`Could not run startup self-test: ${error.message || error}`));
checkDesktopReadiness().catch((error) => appendLog(`Could not check desktop readiness: ${error.message || error}`));
refreshModelCache().catch((error) => appendLog(`Could not inspect model cache: ${error.message || error}`));
restoreFormState().catch((error) => appendLog(`Could not restore pairing state: ${error.message || error}`));
setStatus("Idle", "idle");
renderLocalReadinessChecklist();
window.setTimeout(applyPreviewStateFromUrl, 50);
