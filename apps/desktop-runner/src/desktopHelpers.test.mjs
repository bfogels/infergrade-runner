import assert from "node:assert/strict";
import test from "node:test";

import {
  assignmentClockTransition,
  assignmentEventRecovery,
  assignmentFailureRecovery,
  assignmentPreflightPresentation,
  assignmentTitleFromRunId,
  desktopReadinessPresentation,
  hubAuthenticationFailure,
  displayCacheArtifactName,
  firstRunHandoffFromDeepLink,
  firstRunHandoffFromParams,
  handoffListenerStartDisposition,
  isPairingIntentDeepLink,
  isTerminalHandoffStatus,
  normalizeDesktopApiUrl,
  requiredDesktopReadinessFailure,
  shouldPreserveActiveAssignment,
  shouldClearCompletedHandoff,
  shouldAppendAssignmentEventLog,
  userSafeStartFailure,
  userSafeUpdateFailure,
  userSafeTokenFailure,
} from "./desktopHelpers.js";

test("accepts only the non-secret pairing intent deep link", () => {
  assert.equal(isPairingIntentDeepLink("infergrade-runner://open?intent=pair"), true);
  assert.equal(isPairingIntentDeepLink("infergrade-runner://open?intent=run"), false);
  assert.equal(isPairingIntentDeepLink("https://infergrade.com/?intent=pair"), false);
  assert.equal(isPairingIntentDeepLink("not a URL"), false);
});

test("turns runtime failures into actionable assignment recovery", () => {
  const required = assignmentFailureRecovery(
    "Cannot use runtime: requires exact runtime target 'infergrade/prism/runtime.tar.gz' (runtime build aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa)"
  );
  assert.equal(required.kind, "install_reviewed_runtime");
  assert.equal(required.requiredRuntime.targetName, "infergrade/prism/runtime.tar.gz");

  const unsupported = assignmentFailureRecovery(
    "the signed catalog has no valid exact-artifact compatibility assertion for abc"
  );
  assert.equal(unsupported.kind, "choose_reviewed_artifact");
  assert.match(unsupported.description, /choose the reviewed model alternative/i);

  const download = assignmentFailureRecovery("curl failed while downloading model: HTTP 404");
  assert.equal(download.kind, "retry_artifact_download");
  assert.match(download.description, /reconnect Hugging Face/i);
});

test("uses structured runtime requirements without depending on log-text parsing", () => {
  const recovery = assignmentEventRecovery({
    recovery_kind: "specialized_runtime_required",
    description: "This exact model needs a reviewed specialized runtime.",
    required_runtime: {
      target_name: "infergrade/prism/runtime.tar.gz",
      runtime_build_id: "A".repeat(64),
    },
  });
  assert.equal(recovery.kind, "install_reviewed_runtime");
  assert.equal(recovery.requiredRuntime.targetName, "infergrade/prism/runtime.tar.gz");
  assert.equal(recovery.requiredRuntime.runtimeBuildId, "a".repeat(64));

  const unsafe = assignmentEventRecovery({
    recovery_kind: "specialized_runtime_required",
    required_runtime: {
      target_name: "../runtime.tar.gz",
      runtime_build_id: "a".repeat(64),
    },
  });
  assert.equal(unsafe.kind, "unknown");
  assert.equal(unsafe.requiredRuntime, null);
});

test("turns internal assignment ids into compact model-aware titles", () => {
  assert.equal(
    assignmentTitleFromRunId("run_qwen3_5_9b_complete_the_missing_benchmark_evidence_123"),
    "Qwen3.5-9B · benchmark evidence run"
  );
  assert.equal(assignmentTitleFromRunId("run_gemma_4_12b_reasoning_123"), "Gemma 4 12B · benchmark evidence run");
  assert.equal(assignmentTitleFromRunId("run_opaque_123"), "Hub benchmark run");
});

test("hides cache-address prefixes from model filenames", () => {
  assert.equal(displayCacheArtifactName("03b74727a860a563-Qwen3.5-9B-Q4_K_M.gguf"), "Qwen3.5-9B-Q4_K_M.gguf");
  assert.equal(displayCacheArtifactName("Qwen3.5-9B-Q4_K_M.gguf"), "Qwen3.5-9B-Q4_K_M.gguf");
});

test("maps expired and revoked Hub pairings to direct recovery copy", () => {
  assert.deepEqual(hubAuthenticationFailure('HTTP 401: {"error":"runner_token_expired"}'), {
    invalid: true,
    title: "Pairing expired",
    message: "This machine's Hub pairing expired. Pair it again to resume benchmark work.",
    status: "Pair again",
  });
  assert.equal(hubAuthenticationFailure("runner_token_revoked").title, "Pairing revoked");
  assert.equal(hubAuthenticationFailure("network unavailable").invalid, false);
});

test("expired pairing takes precedence over otherwise saved readiness state", () => {
  const presentation = desktopReadinessPresentation({
    paired: true,
    listening: false,
    runtimeAvailable: true,
    hubVerified: false,
    authFailure: hubAuthenticationFailure("runner_token_expired"),
  });
  assert.equal(presentation.title, "Pairing expired");
  assert.equal(presentation.hubFactState, "blocked");
  assert.equal(presentation.ready, false);
});

test("assignment clocks begin on claim, reset for a new run, and freeze on terminal phases", () => {
  const firstStart = new Date("2026-07-17T12:00:00Z");
  const claimTime = new Date("2026-07-17T12:01:00Z");
  const secondClaimTime = new Date("2026-07-17T12:05:00Z");

  assert.deepEqual(
    assignmentClockTransition({ runId: "run_1", phase: "Ready to claim", now: claimTime }),
    { startedAt: null, shouldRun: false }
  );
  assert.deepEqual(
    assignmentClockTransition({ previousStartedAt: firstStart, previousRunId: "run_1", runId: "run_2", phase: "Running", now: secondClaimTime }),
    { startedAt: secondClaimTime, shouldRun: true }
  );
  assert.deepEqual(
    assignmentClockTransition({ previousStartedAt: firstStart, previousRunId: "run_1", runId: "run_1", phase: "Needs attention", now: secondClaimTime }),
    { startedAt: firstStart, shouldRun: false }
  );
});

test("only a matching completed listener run clears its stored handoff", () => {
  assert.equal(shouldClearCompletedHandoff({ phase: "Complete", runId: "run_1", handoffRunId: "run_1" }), true);
  assert.equal(shouldClearCompletedHandoff({ phase: "Running", runId: "run_1", handoffRunId: "run_1" }), false);
  assert.equal(shouldClearCompletedHandoff({ phase: "Complete", runId: "run_2", handoffRunId: "run_1" }), false);
});

test("recognizes every terminal Hub handoff status", () => {
  assert.equal(isTerminalHandoffStatus("completed"), true);
  assert.equal(isTerminalHandoffStatus("failed"), true);
  assert.equal(isTerminalHandoffStatus("cancelled"), true);
  assert.equal(isTerminalHandoffStatus("running"), false);
  assert.equal(isTerminalHandoffStatus("queued"), false);
});

test("turns app-first preflight state into one honest next action", () => {
  assert.deepEqual(
    assignmentPreflightPresentation({ staleRuntimeCleared: true }),
    {
      kind: "runtime_repaired",
      blocking: true,
      phase: "Runtime needed",
      description:
        "InferGrade cleared a selected executable that no longer exists. Immutable runtime files were retained; choose the managed runtime or select an installed llama.cpp binary.",
      checkName: "Stale runtime selection cleared",
      progress: 100,
      waitingForListener: true,
    }
  );
  const queued = assignmentPreflightPresentation({
    runId: "run_queued",
    status: "awaiting_execution",
    listening: false,
    setupReady: true,
  });
  assert.equal(queued.kind, "assignment_ready_to_start");
  assert.match(queued.description, /exact artifact digest and model load remain pending/i);
  const ready = assignmentPreflightPresentation({
    runId: "run_queued",
    status: "awaiting_execution",
    listening: true,
    setupReady: true,
  });
  assert.equal(ready.kind, "assignment_ready_to_claim");
  assert.match(ready.description, /bind an immutable runtime/i);
  const terminal = assignmentPreflightPresentation({
    runId: "run_done",
    status: "completed",
    terminal: true,
    setupReady: true,
  });
  assert.equal(terminal.kind, "terminal_handoff_cleared");
  assert.match(terminal.description, /cleared the stale handoff/i);
});

test("preflight never treats an unobserved queue or running orphan as ready", () => {
  const noHandoff = assignmentPreflightPresentation({ setupReady: true });
  assert.equal(noHandoff.kind, "queue_unconfirmed");
  assert.match(noHandoff.description, /Open Hub to queue/i);

  const observedIdle = assignmentPreflightPresentation({ setupReady: true, observedIdle: true });
  assert.equal(observedIdle.kind, "queue_empty");
  assert.match(observedIdle.description, /no matching queued benchmark/i);

  const running = assignmentPreflightPresentation({
    runId: "run_stale_running",
    status: "running",
    setupReady: true,
    listening: false,
  });
  assert.equal(running.kind, "assignment_already_running");
  assert.match(running.description, /instead of starting duplicate work/i);
});

test("every listener start path blocks paused and already-running Hub handoffs", () => {
  const paused = handoffListenerStartDisposition({ runId: "run_paused", status: "paused" });
  assert.equal(paused.allowed, false);
  assert.equal(paused.kind, "assignment_paused");
  assert.equal(paused.presentation.blocking, true);
  assert.equal(
    assignmentPreflightPresentation({ runId: "run_paused", status: "paused", setupReady: false }).kind,
    "assignment_paused"
  );

  const running = handoffListenerStartDisposition({ runId: "run_running", status: "running" });
  assert.equal(running.allowed, false);
  assert.equal(running.kind, "assignment_already_running");
  assert.equal(running.presentation.blocking, true);
  assert.equal(
    assignmentPreflightPresentation({ runId: "run_running", status: "running", setupReady: false }).kind,
    "assignment_already_running"
  );

  const queued = handoffListenerStartDisposition({ runId: "run_queued", status: "awaiting_execution" });
  assert.equal(queued.allowed, true);
  assert.equal(queued.kind, "assignment_ready_to_start");
});

test("readiness checks preserve active assignment phases", () => {
  for (const phase of ["Preparing", "Downloading", "Running", "Uploading"]) {
    assert.equal(
      shouldPreserveActiveAssignment({ listening: true, runId: "run_active", phase }),
      true
    );
  }
  assert.equal(shouldPreserveActiveAssignment({ listening: false, runId: "run_active", phase: "Running" }), false);
  assert.equal(shouldPreserveActiveAssignment({ listening: true, runId: "", phase: "Running" }), false);
  assert.equal(shouldPreserveActiveAssignment({ listening: true, runId: "run_queued", phase: "Ready to claim" }), false);
});

test("logs assignment idle once per idle transition", () => {
  assert.equal(shouldAppendAssignmentEventLog("", "assignment_idle"), true);
  assert.equal(shouldAppendAssignmentEventLog("assignment_idle", "assignment_idle"), false);
  assert.equal(shouldAppendAssignmentEventLog("assignment_idle", "assignment_update"), true);
  assert.equal(shouldAppendAssignmentEventLog("assignment_update", "assignment_idle"), true);
});

test("requires an authenticated Hub check before presenting the Runner as ready", () => {
  assert.deepEqual(
    desktopReadinessPresentation({ paired: true, listening: true, runtimeAvailable: true, hubVerified: false }),
    {
      ready: false,
      title: "Verify Hub connection",
      message: "Pairing and runtime are available. Run the readiness check to verify Hub access.",
      hubFact: "Hub check needed",
      hubFactState: "warning",
    }
  );
  assert.equal(
    desktopReadinessPresentation({ paired: true, listening: true, runtimeAvailable: true, hubVerified: true }).ready,
    true
  );
  assert.equal(
    desktopReadinessPresentation({ paired: true, listening: false, runtimeAvailable: true, hubVerified: true }).title,
    "Ready to listen"
  );
  assert.equal(
    desktopReadinessPresentation({ paired: true, listening: true, runtimeAvailable: false, hubVerified: true }).title,
    "Runtime needed"
  );
});

test("explicit app preflight requires structured desktop readiness", () => {
  assert.match(requiredDesktopReadinessFailure(), /only available inside the desktop app/i);
  assert.match(
    requiredDesktopReadinessFailure({ sidecarAvailable: true, status: "fallback" }),
    /did not return a successful structured status/i
  );
  assert.match(
    requiredDesktopReadinessFailure({ sidecarAvailable: true, status: "error" }),
    /did not return a successful structured status/i
  );
  assert.equal(requiredDesktopReadinessFailure({ sidecarAvailable: true, status: "ok" }), null);
});

test("normalizes hosted and local desktop API URLs before sidecar invocation", () => {
  assert.equal(normalizeDesktopApiUrl(""), "https://api.infergrade.com/");
  assert.equal(normalizeDesktopApiUrl("api.infergrade.com"), "https://api.infergrade.com/");
  assert.equal(normalizeDesktopApiUrl("https://api.infergrade.com"), "https://api.infergrade.com/");
  assert.equal(normalizeDesktopApiUrl("localhost:8000"), "http://localhost:8000/");
  assert.equal(normalizeDesktopApiUrl("127.0.0.1:8000"), "http://127.0.0.1:8000/");
  assert.equal(normalizeDesktopApiUrl("http://127.0.0.1:8000"), "http://127.0.0.1:8000/");
});

test("rejects invalid or unsafe desktop API URLs with user-facing guidance", () => {
  assert.throws(
    () => normalizeDesktopApiUrl("api.infergrade.com bad"),
    /Enter a valid Hub API URL/
  );
  assert.throws(
    () => normalizeDesktopApiUrl("http://api.infergrade.com"),
    /Hosted Hub URLs must use HTTPS/
  );
});

test("parses token-free first-run handoff URLs", () => {
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "infergrade-runner://first-run?first_run_run_id=run_123&first_run_worker_id=worker_456&first_run_api_url=https%3A%2F%2Fapi.infergrade.com&expected_runner_version=0.3.6&expected_contract_version=0.3.5"
    ),
    {
      runId: "run_123",
      workerId: "worker_456",
      apiUrl: "https://api.infergrade.com/",
      expectedRunnerVersion: "0.3.6",
      expectedContractVersion: "0.3.5",
    }
  );
  assert.deepEqual(
    firstRunHandoffFromParams(new URLSearchParams("run_id=run_abc&workerId=worker_def")),
    {
      runId: "run_abc",
      workerId: "worker_def",
      apiUrl: "",
      expectedRunnerVersion: "",
      expectedContractVersion: "",
    }
  );
});

test("parses localhost API URL handoffs for local Hub dogfood", () => {
  assert.deepEqual(
    firstRunHandoffFromParams(new URLSearchParams("run_id=run_local&first_run_api_url=http%3A%2F%2F127.0.0.1%3A8000")),
    {
      runId: "run_local",
      workerId: "",
      apiUrl: "http://127.0.0.1:8000/",
      expectedRunnerVersion: "",
      expectedContractVersion: "",
    }
  );
});

test("rejects first-run handoffs with sensitive parameters", () => {
  const rejected = [];
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "infergrade-runner://first-run?first_run_run_id=run_123&upload_token=secret",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "", apiUrl: "", expectedRunnerVersion: "", expectedContractVersion: "" }
  );
  assert.equal(rejected[0], "sensitive handoff parameter");
});

test("rejects first-run handoffs with unsafe API URLs or version text", () => {
  const rejected = [];
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "infergrade-runner://first-run?first_run_run_id=run_123&first_run_api_url=http%3A%2F%2Fapi.infergrade.com",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "", apiUrl: "", expectedRunnerVersion: "", expectedContractVersion: "" }
  );
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "infergrade-runner://first-run?first_run_run_id=run_123&first_run_api_url=https%3A%2F%2Fevil.example",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "", apiUrl: "", expectedRunnerVersion: "", expectedContractVersion: "" }
  );
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "infergrade-runner://first-run?first_run_run_id=run_123&first_run_api_url=https%3A%2F%2Fuser%3Apass%40api.infergrade.com",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "", apiUrl: "", expectedRunnerVersion: "", expectedContractVersion: "" }
  );
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "infergrade-runner://first-run?first_run_run_id=run_123&first_run_api_url=https%3A%2F%2Fapi.infergrade.com%2F%3Fapi_key%3Dabc",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "", apiUrl: "", expectedRunnerVersion: "", expectedContractVersion: "" }
  );
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "infergrade-runner://first-run?first_run_run_id=run_123&expected_runner_version=bearer-secret",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "", apiUrl: "", expectedRunnerVersion: "", expectedContractVersion: "" }
  );
  assert.equal(rejected[0], "invalid handoff API URL");
  assert.equal(rejected[1], "unapproved handoff API URL");
  assert.equal(rejected[2], "unapproved handoff API URL");
  assert.equal(rejected[3], "unapproved handoff API URL");
  assert.equal(rejected[4], "unsafe handoff version");
});

test("rejects first-run handoffs with unsafe or sensitive identifier values", () => {
  const rejected = [];
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "infergrade-runner://first-run?first_run_run_id=igrt_secret_token&first_run_worker_id=worker_456",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "", apiUrl: "", expectedRunnerVersion: "", expectedContractVersion: "" }
  );
  assert.deepEqual(
    firstRunHandoffFromParams(new URLSearchParams("run_id=run_abc/../../secret&workerId=worker_def")),
    { runId: "", workerId: "", apiUrl: "", expectedRunnerVersion: "", expectedContractVersion: "" }
  );
  assert.equal(rejected[0], "unsafe handoff identifier");
});

test("rejects first-run handoffs from unexpected URL schemes", () => {
  const rejected = [];
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "https://example.com/first-run?first_run_run_id=run_123",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "", apiUrl: "", expectedRunnerVersion: "", expectedContractVersion: "" }
  );
  assert.equal(rejected[0], "unexpected first-run handoff URL scheme");
});

test("maps noisy update and token storage failures to recoverable UI copy", () => {
  assert.equal(
    userSafeUpdateFailure("invalid release JSON"),
    "Update status is unavailable. You can still pair and start the Runner."
  );
  assert.equal(
    userSafeTokenFailure("keychain user canceled"),
    "Credential storage was canceled. You can retry, reset pairing, or paste a fresh code."
  );
  assert.equal(
    userSafeTokenFailure("keychain item already exists"),
    "Credential storage needs to replace the saved token. Try Reset Pairing, then pair again."
  );
});

test("maps auto-start failures to paired-but-recoverable UI copy", () => {
  assert.equal(
    userSafeStartFailure("Packaged Runner core is unavailable"),
    "Pairing is saved. Runner core is not available yet; run the startup self-test or runtime check, then start listening again."
  );
  assert.equal(
    userSafeStartFailure("llama.cpp runtime missing"),
    "Pairing is saved. A local runtime is missing; inspect the Runtime panel, then start listening again."
  );
  assert.equal(
    userSafeStartFailure("something else"),
    "Pairing is saved. Runner could not start automatically; inspect Logs, then start listening again."
  );
});
