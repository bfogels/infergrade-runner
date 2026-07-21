import assert from "node:assert/strict";
import test from "node:test";

import {
  assignmentClockTransition,
  assignmentTitleFromRunId,
  displayCacheArtifactName,
  firstRunHandoffFromDeepLink,
  firstRunHandoffFromParams,
  isTerminalHandoffStatus,
  normalizeDesktopApiUrl,
  shouldClearCompletedHandoff,
  shouldAppendAssignmentEventLog,
  userSafeStartFailure,
  userSafeUpdateFailure,
  userSafeTokenFailure,
} from "./desktopHelpers.js";

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

test("logs assignment idle once per idle transition", () => {
  assert.equal(shouldAppendAssignmentEventLog("", "assignment_idle"), true);
  assert.equal(shouldAppendAssignmentEventLog("assignment_idle", "assignment_idle"), false);
  assert.equal(shouldAppendAssignmentEventLog("assignment_idle", "assignment_update"), true);
  assert.equal(shouldAppendAssignmentEventLog("assignment_update", "assignment_idle"), true);
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
