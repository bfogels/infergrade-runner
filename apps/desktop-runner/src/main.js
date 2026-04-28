import "./styles.css";

const SIDECAR_NAME = "binaries/infergrade-sidecar";
const TOKEN_STORAGE_KEY = "infergrade.runner.prototypeToken";
const API_URL_STORAGE_KEY = "infergrade.runner.apiUrl";

const form = document.querySelector("[data-runner-form]");
const startButton = document.querySelector("[data-start-runner]");
const stopButton = document.querySelector("[data-stop-runner]");
const pairButton = document.querySelector("[data-pair-runner]");
const saveTokenButton = document.querySelector("[data-save-token]");
const clearTokenButton = document.querySelector("[data-clear-token]");
const clearLogsButton = document.querySelector("[data-clear-logs]");
const statusText = document.querySelector("[data-runner-status]");
const statusDot = document.querySelector("[data-status-dot]");
const pairState = document.querySelector("[data-pair-state]");
const tokenState = document.querySelector("[data-token-state]");
const logOutput = document.querySelector("[data-log-output]");

let childProcess = null;
let logLines = [];
let tauriInvoke = null;

function isTauriRuntime() {
  return "__TAURI_INTERNALS__" in window;
}

async function restoreFormState() {
  const savedApiUrl = window.localStorage.getItem(API_URL_STORAGE_KEY);

  if (savedApiUrl) {
    form.elements.apiUrl.value = savedApiUrl;
  }

  if (!isTauriRuntime()) {
    const savedPreviewToken = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (savedPreviewToken) {
      form.elements.hubToken.value = savedPreviewToken;
    }
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
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

async function saveStoredToken(token) {
  const invoke = await loadTauriInvoke();
  if (invoke) {
    await invoke("save_runner_token", { token });
    return;
  }
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

async function clearStoredToken() {
  const invoke = await loadTauriInvoke();
  if (invoke) {
    await invoke("clear_runner_token");
    return;
  }
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
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
    ? "Preview token saved in local browser storage."
    : "Preview mode uses browser storage only; the app uses the OS credential store.";
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
  if (!["http:", "https:"].includes(parsed.protocol)) {
    throw new Error("Hub URL must start with http:// or https://.");
  }
  return parsed.href;
}

async function startRunner() {
  const apiUrl = readApiUrl();
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
  startButton.disabled = true;
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
      throw new Error(output.stderr || output.stdout || `Pairing command exited with code ${output.code}.`);
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

restoreFormState().catch((error) => appendLog(`Could not restore pairing state: ${error.message || error}`));
setStatus("Idle", "idle");
