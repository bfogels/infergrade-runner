const HOSTED_API_URL = "https://api.infergrade.com";
const SENSITIVE_HANDOFF_TEXT = /token|secret|authorization|bearer/i;
const HUB_HANDOFF_ID = /^[A-Za-z0-9_.-]{1,160}$/;
const HUB_HANDOFF_VERSION = /^[A-Za-z0-9_.+-]{1,80}$/;

function isLocalHost(hostname) {
  const host = String(hostname || "").toLowerCase();
  const ipv4Octet = "(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)";
  return host === "localhost" || host === "::1" || host === "[::1]" || new RegExp(`^127(?:\\.${ipv4Octet}){3}$`).test(host);
}

function hasScheme(value) {
  return String(value || "").includes("://") && /^[a-z][a-z0-9+.-]*:/i.test(value);
}

function isApprovedHandoffApiUrl(parsed) {
  if (parsed.username || parsed.password || parsed.search || parsed.hash || parsed.pathname !== "/") {
    return false;
  }
  return (parsed.protocol === "https:" && parsed.hostname === "api.infergrade.com") || isLocalHost(parsed.hostname);
}

export function normalizeDesktopApiUrl(value = "") {
  const raw = String(value || "").trim();
  const candidate = raw || HOSTED_API_URL;
  if (/\s/.test(candidate)) {
    throw new Error("Enter a valid Hub API URL, such as https://api.infergrade.com.");
  }

  let urlText = candidate;
  if (!hasScheme(urlText)) {
    const hostGuess = urlText.split(/[/:]/, 1)[0];
    urlText = isLocalHost(hostGuess) ? `http://${urlText}` : `https://${urlText}`;
  }

  let parsed;
  try {
    parsed = new URL(urlText);
  } catch (_error) {
    throw new Error("Enter a valid Hub API URL, such as https://api.infergrade.com.");
  }

  if (parsed.protocol !== "https:" && !(parsed.protocol === "http:" && isLocalHost(parsed.hostname))) {
    throw new Error("Hosted Hub URLs must use HTTPS. Localhost and 127.0.0.1 can use HTTP for development.");
  }
  if (!parsed.hostname) {
    throw new Error("Enter a valid Hub API URL, such as https://api.infergrade.com.");
  }
  return parsed.href;
}

export function firstRunHandoffFromParams(params, onRejected = () => {}) {
  const searchParams = params instanceof URLSearchParams ? params : new URLSearchParams(params || "");
  const sensitiveKeys = [...searchParams.keys()].filter((key) => SENSITIVE_HANDOFF_TEXT.test(key));
  if (sensitiveKeys.length) {
    onRejected("sensitive handoff parameter");
    return emptyFirstRunHandoff();
  }
  const rawRunId =
    searchParams.get("first_run_run_id") ||
    searchParams.get("firstRunRunId") ||
    searchParams.get("run_id") ||
    searchParams.get("runId") ||
    "";
  const rawWorkerId =
    searchParams.get("first_run_worker_id") || searchParams.get("worker_id") || searchParams.get("workerId") || "";
  const rawApiUrl =
    searchParams.get("first_run_api_url") || searchParams.get("hub_api_url") || searchParams.get("api_url") || "";
  const rawExpectedRunnerVersion =
    searchParams.get("expected_runner_version") || searchParams.get("runner_version") || "";
  const rawExpectedContractVersion =
    searchParams.get("expected_contract_version") || searchParams.get("contract_version") || "";
  const runId = safeHandoffId(rawRunId, onRejected);
  const workerId = safeHandoffId(rawWorkerId, onRejected);
  const apiUrl = safeHandoffApiUrl(rawApiUrl, onRejected);
  const expectedRunnerVersion = safeHandoffVersion(rawExpectedRunnerVersion, onRejected);
  const expectedContractVersion = safeHandoffVersion(rawExpectedContractVersion, onRejected);
  if (runId === null || workerId === null || apiUrl === null || expectedRunnerVersion === null || expectedContractVersion === null) {
    return emptyFirstRunHandoff();
  }
  return {
    runId,
    workerId,
    apiUrl,
    expectedRunnerVersion,
    expectedContractVersion,
  };
}

function emptyFirstRunHandoff() {
  return {
    runId: "",
    workerId: "",
    apiUrl: "",
    expectedRunnerVersion: "",
    expectedContractVersion: "",
  };
}

function safeHandoffId(value, onRejected) {
  const raw = String(value || "");
  if (!raw) {
    return "";
  }
  const trimmed = raw.trim();
  if (
    raw !== trimmed ||
    trimmed === "." ||
    trimmed === ".." ||
    !HUB_HANDOFF_ID.test(trimmed) ||
    SENSITIVE_HANDOFF_TEXT.test(trimmed)
  ) {
    onRejected("unsafe handoff identifier");
    return null;
  }
  return trimmed;
}

function safeHandoffApiUrl(value, onRejected) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "";
  }
  if (SENSITIVE_HANDOFF_TEXT.test(raw)) {
    onRejected("unsafe handoff API URL");
    return null;
  }
  try {
    const normalized = normalizeDesktopApiUrl(raw);
    const parsed = new URL(normalized);
    if (!isApprovedHandoffApiUrl(parsed)) {
      onRejected("unapproved handoff API URL");
      return null;
    }
    return normalized;
  } catch (_error) {
    onRejected("invalid handoff API URL");
    return null;
  }
}

function safeHandoffVersion(value, onRejected) {
  const trimmed = String(value || "").trim();
  if (!trimmed) {
    return "";
  }
  if (SENSITIVE_HANDOFF_TEXT.test(trimmed) || !HUB_HANDOFF_VERSION.test(trimmed)) {
    onRejected("unsafe handoff version");
    return null;
  }
  return trimmed;
}

export function firstRunHandoffFromDeepLink(value, onRejected = () => {}) {
  if (!value || typeof value !== "string") {
    return emptyFirstRunHandoff();
  }
  let parsed;
  try {
    parsed = new URL(value);
  } catch (_error) {
    onRejected("invalid first-run handoff URL");
    return emptyFirstRunHandoff();
  }
  if (parsed.protocol !== "infergrade-runner:") {
    onRejected("unexpected first-run handoff URL scheme");
    return emptyFirstRunHandoff();
  }
  return firstRunHandoffFromParams(parsed.searchParams, onRejected);
}

export function userSafeUpdateFailure(_message = "") {
  return "Update status is unavailable. You can still pair and start the Runner.";
}

export function assignmentFailureRecovery(message = "") {
  const detail = String(message || "").trim();
  const runtimeMatch = detail.match(/requires exact runtime target '([^']+)' \(runtime build ([0-9a-f]{64})\)/i);
  if (runtimeMatch) {
    return {
      kind: "install_reviewed_runtime",
      description: `This model needs a reviewed specialized runtime (${runtimeMatch[2].slice(0, 12).toLowerCase()}…). Install it here, then retry the benchmark from Hub.`,
      checkName: "Specialized runtime required",
      requiredRuntime: { targetName: runtimeMatch[1], runtimeBuildId: runtimeMatch[2].toLowerCase() },
    };
  }
  if (/no valid exact-artifact compatibility assertion/i.test(detail)) {
    return {
      kind: "choose_reviewed_artifact",
      description: "InferGrade does not have a reviewed runtime for this exact specialized GGUF. Open Hub and choose the reviewed model alternative, then retry.",
      checkName: "Choose reviewed artifact in Hub",
      requiredRuntime: null,
    };
  }
  if (/curl failed while downloading|artifact download|http (?:get|error)|\b(?:404|403)\b/i.test(detail)) {
    return {
      kind: "retry_artifact_download",
      description: "The model download did not complete. Check the artifact in Hub, reconnect Hugging Face if it is gated, then retry.",
      checkName: "Model download failed",
      requiredRuntime: null,
    };
  }
  return {
    kind: "unknown",
    description: detail,
    checkName: "See logs for recovery detail",
    requiredRuntime: null,
  };
}

export function hubAuthenticationFailure(message = "") {
  const text = String(message || "");
  if (/runner_token_expired|runner token (?:has )?expired/i.test(text)) {
    return {
      invalid: true,
      title: "Pairing expired",
      message: "This machine's Hub pairing expired. Pair it again to resume benchmark work.",
      status: "Pair again",
    };
  }
  if (/runner_token_revoked|runner token (?:was |has been )?revoked/i.test(text)) {
    return {
      invalid: true,
      title: "Pairing revoked",
      message: "This machine's Hub pairing was revoked. Pair it again before accepting benchmark work.",
      status: "Pair again",
    };
  }
  return { invalid: false, title: "", message: "", status: "" };
}

export function assignmentTitleFromRunId(value = "") {
  const runId = String(value || "").trim();
  if (!runId) {
    return "Hub benchmark run";
  }
  const qwen = runId.match(/(?:^|_)qwen(\d+)(?:_(\d+))?_(\d+)(?:_(\d+))?b(?:_|$)/i);
  if (qwen) {
    const generation = qwen[2] ? `${qwen[1]}.${qwen[2]}` : qwen[1];
    const size = qwen[4] ? `${qwen[3]}.${qwen[4]}` : qwen[3];
    return `Qwen${generation}-${size}B · benchmark evidence run`;
  }
  const gemma = runId.match(/(?:^|_)gemma(?:_|-)?(\d+)(?:_|-)(\d+)(?:_|-)?b(?:_|$)/i);
  if (gemma) {
    return `Gemma ${gemma[1]} ${gemma[2]}B · benchmark evidence run`;
  }
  return "Hub benchmark run";
}

export function displayCacheArtifactName(value = "") {
  const name = String(value || "").trim();
  return name.replace(/^[a-f0-9]{12,64}-/i, "") || "Cached model";
}

const TERMINAL_ASSIGNMENT_PHASES = new Set(["complete", "needs attention", "interrupted", "failed", "cancelled"]);

export function assignmentClockTransition({
  previousStartedAt = null,
  previousRunId = "",
  runId = "",
  phase = "",
  waitingForListener = false,
  startedAt = null,
  now = new Date(),
} = {}) {
  const normalizedPhase = String(phase || "").trim().toLowerCase();
  const hasStarted = !waitingForListener && !["handoff received", "ready to claim"].includes(normalizedPhase);
  const runChanged = Boolean(runId && previousRunId && runId !== previousRunId);
  const nextStartedAt = hasStarted ? startedAt || (runChanged ? now : previousStartedAt) || now : null;
  return {
    startedAt: nextStartedAt,
    shouldRun: Boolean(nextStartedAt) && !TERMINAL_ASSIGNMENT_PHASES.has(normalizedPhase),
  };
}

export function shouldClearCompletedHandoff({ phase = "", runId = "", handoffRunId = "" } = {}) {
  return String(phase || "").trim().toLowerCase() === "complete" && Boolean(runId) && runId === handoffRunId;
}

export function isTerminalHandoffStatus(status = "") {
  return ["completed", "failed", "cancelled"].includes(String(status || "").trim().toLowerCase());
}

export function shouldAppendAssignmentEventLog(previousType = "", nextType = "") {
  return nextType !== "assignment_idle" || previousType !== "assignment_idle";
}

export function desktopReadinessPresentation({
  paired = false,
  listening = false,
  runtimeAvailable = false,
  hubVerified = false,
  authFailure = null,
} = {}) {
  if (authFailure?.invalid) {
    return {
      ready: false,
      title: authFailure.title,
      message: authFailure.message,
      hubFact: authFailure.status,
      hubFactState: "blocked",
    };
  }
  if (!paired) {
    return {
      ready: false,
      title: "Connect this machine",
      message: "Pair with Hub using a one-time code before this Runner accepts assigned work.",
      hubFact: "Pair with Hub",
      hubFactState: "blocked",
    };
  }
  if (!runtimeAvailable) {
    return {
      ready: false,
      title: "Runtime needed",
      message: "Pairing is saved. Select a llama.cpp runtime before this machine runs assigned work.",
      hubFact: hubVerified ? "Hub verified" : "Hub check needed",
      hubFactState: hubVerified ? "ready" : "warning",
    };
  }
  if (!hubVerified) {
    return {
      ready: false,
      title: "Verify Hub connection",
      message: "Pairing and runtime are available. Run the readiness check to verify Hub access.",
      hubFact: "Hub check needed",
      hubFactState: "warning",
    };
  }
  if (!listening) {
    return {
      ready: false,
      title: "Ready to listen",
      message: "Readiness checks passed. Start listening when this machine should accept assigned work.",
      hubFact: "Hub verified",
      hubFactState: "ready",
    };
  }
  return {
    ready: true,
    title: "Ready",
    message: "Connected to Hub. Backend verified. Waiting for assigned work.",
    hubFact: "Hub verified",
    hubFactState: "ready",
  };
}

export function isCredentialCanceled(message = "") {
  return /cancelled|canceled|user interaction|user.*cancel/i.test(String(message || ""));
}

export function userSafeTokenFailure(message = "") {
  if (isCredentialCanceled(message)) {
    return "Credential storage was canceled. You can retry, reset pairing, or paste a fresh code.";
  }
  if (/already exists|duplicate|ambiguous/i.test(String(message || ""))) {
    return "Credential storage needs to replace the saved token. Try Reset Pairing, then pair again.";
  }
  return "Credential storage is unavailable. You can retry, reset pairing, or paste a fresh code.";
}

export function userSafeStartFailure(message = "") {
  const text = String(message || "");
  if (/runner core|runner-core|packaged runner|infergrade.*not found|not found on PATH/i.test(text)) {
    return "Pairing is saved. Runner core is not available yet; run the startup self-test or runtime check, then start listening again.";
  }
  if (/runtime|llama|docker|container|metal|backend/i.test(text)) {
    return "Pairing is saved. A local runtime is missing; inspect the Runtime panel, then start listening again.";
  }
  return "Pairing is saved. Runner could not start automatically; inspect Logs, then start listening again.";
}
