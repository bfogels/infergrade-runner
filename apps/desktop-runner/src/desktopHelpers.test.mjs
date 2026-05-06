import assert from "node:assert/strict";
import test from "node:test";

import {
  firstRunHandoffFromDeepLink,
  firstRunHandoffFromParams,
  normalizeDesktopApiUrl,
  userSafeStartFailure,
  userSafeUpdateFailure,
  userSafeTokenFailure,
} from "./desktopHelpers.js";

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
    firstRunHandoffFromDeepLink("infergrade-runner://first-run?first_run_run_id=run_123&first_run_worker_id=worker_456"),
    { runId: "run_123", workerId: "worker_456" }
  );
  assert.deepEqual(
    firstRunHandoffFromParams(new URLSearchParams("run_id=run_abc&workerId=worker_def")),
    { runId: "run_abc", workerId: "worker_def" }
  );
});

test("rejects first-run handoffs with sensitive parameters", () => {
  const rejected = [];
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "infergrade-runner://first-run?first_run_run_id=run_123&upload_token=secret",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "" }
  );
  assert.equal(rejected[0], "sensitive handoff parameter");
});

test("rejects first-run handoffs from unexpected URL schemes", () => {
  const rejected = [];
  assert.deepEqual(
    firstRunHandoffFromDeepLink(
      "https://example.com/first-run?first_run_run_id=run_123",
      (reason) => rejected.push(reason)
    ),
    { runId: "", workerId: "" }
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
