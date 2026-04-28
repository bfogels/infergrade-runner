import "./styles.css";

const SIDECAR_NAME = "binaries/infergrade-sidecar";
const TOKEN_STORAGE_KEY = "infergrade.runner.prototypeToken";
const API_URL_STORAGE_KEY = "infergrade.runner.apiUrl";

const form = document.querySelector("[data-runner-form]");
const startButton = document.querySelector("[data-start-runner]");
const stopButton = document.querySelector("[data-stop-runner]");
const saveTokenButton = document.querySelector("[data-save-token]");
const clearTokenButton = document.querySelector("[data-clear-token]");
const clearLogsButton = document.querySelector("[data-clear-logs]");
const statusText = document.querySelector("[data-runner-status]");
const statusDot = document.querySelector("[data-status-dot]");
const tokenState = document.querySelector("[data-token-state]");
const logOutput = document.querySelector("[data-log-output]");

let childProcess = null;
let logLines = [];

function restoreFormState() {
  const savedApiUrl = window.localStorage.getItem(API_URL_STORAGE_KEY);
  const savedToken = window.localStorage.getItem(TOKEN_STORAGE_KEY);

  if (savedApiUrl) {
    form.elements.apiUrl.value = savedApiUrl;
  }
  if (savedToken) {
    form.elements.hubToken.value = savedToken;
  }

  updateTokenState();
}

function updateTokenState() {
  const hasToken = Boolean(window.localStorage.getItem(TOKEN_STORAGE_KEY));
  tokenState.textContent = hasToken
    ? "Prototype token saved locally. Replace with OS secure storage before beta."
    : "No token saved. Paste a paired runner token before listening for Hub jobs.";
}

function setStatus(status, tone = "idle") {
  statusText.textContent = status;
  statusDot.dataset.tone = tone;
}

function appendLog(message) {
  const normalized = String(message || "").trimEnd();
  if (!normalized) {
    return;
  }

  const timestamp = new Date().toLocaleTimeString();
  logLines = [...logLines, `[${timestamp}] ${normalized}`].slice(-400);
  logOutput.textContent = logLines.join("\n");
  logOutput.scrollTop = logOutput.scrollHeight;
}

async function loadTauriShell() {
  if (!("__TAURI_INTERNALS__" in window)) {
    return null;
  }

  const shell = await import("@tauri-apps/plugin-shell");
  return shell.Command;
}

function runnerEnvironment() {
  const savedToken = window.localStorage.getItem(TOKEN_STORAGE_KEY);
  return savedToken ? { INFERGRADE_HUB_TOKEN: savedToken } : {};
}

async function startRunner() {
  const apiUrl = form.elements.apiUrl.value.trim() || "http://127.0.0.1:8000";
  window.localStorage.setItem(API_URL_STORAGE_KEY, apiUrl);

  const Command = await loadTauriShell();
  if (!Command) {
    setStatus("Preview mode", "warning");
    appendLog("Tauri runtime not detected. Browser preview cannot start the Runner sidecar.");
    return;
  }

  if (childProcess) {
    appendLog("Runner is already listening.");
    return;
  }

  const command = Command.sidecar(SIDECAR_NAME, ["start", "--api-url", apiUrl], {
    env: runnerEnvironment()
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
  startButton.disabled = true;
  stopButton.disabled = false;
  setStatus("Listening", "good");
  appendLog(`Started infergrade listener for ${apiUrl}.`);
}

async function stopRunner() {
  if (!childProcess) {
    return;
  }

  await childProcess.kill();
  appendLog("Stop requested.");
}

saveTokenButton.addEventListener("click", () => {
  const token = form.elements.hubToken.value.trim();
  if (token) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  }
  window.localStorage.setItem(API_URL_STORAGE_KEY, form.elements.apiUrl.value.trim());
  updateTokenState();
});

clearTokenButton.addEventListener("click", () => {
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  form.elements.hubToken.value = "";
  updateTokenState();
});

startButton.addEventListener("click", () => {
  startRunner().catch((error) => {
    setStatus("Failed", "error");
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

restoreFormState();
setStatus("Idle", "idle");
