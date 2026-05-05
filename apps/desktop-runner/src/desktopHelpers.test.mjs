import assert from "node:assert/strict";
import test from "node:test";

import {
  normalizeDesktopApiUrl,
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
