import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("desktop shell permission shapes keep version separate from URL-scoped commands", () => {
  const capability = JSON.parse(
    readFileSync(new URL("../src-tauri/capabilities/default.json", import.meta.url), "utf8")
  );
  const permissions = capability.permissions.flatMap((permission) => permission.allow || []);
  const shapes = permissions.map((entry) => JSON.stringify(entry.args || []));

  assert.ok(shapes.includes(JSON.stringify(["--version"])));
  assert.ok(shapes.includes(JSON.stringify(["desktop-self-test"])));
  assert.ok(shapes.some((shape) => shape.includes('"start"') && shape.includes('"--api-url"')));
  assert.equal(shapes.some((shape) => shape.includes('"pair"') && shape.includes('"--api-url"')), false);
  assert.equal(shapes.includes(JSON.stringify(["install-runtime", "--runtime", "llama.cpp"])), false);
  assert.ok(shapes.some((shape) => shape.includes('"install-runtime"') && shape.includes('"--select-existing"')));
});

test("desktop onboarding exposes paste-code pairing, reset, and bundled runner self-test", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");

  assert.ok(html.includes('value="https://api.infergrade.com"'));
  assert.ok(html.includes("Paste the one-time code from Hub"));
  assert.ok(html.includes("data-reset-pairing"));
  assert.ok(html.includes("data-runner-self-test"));
  assert.ok(js.includes("normalizeDesktopApiUrl"));
  assert.ok(js.includes("desktop-self-test"));
  assert.ok(js.includes('invoke("redeem_runner_pairing"'));
  assert.ok(js.includes('invoke("reset_runner_pairing"'));
  assert.ok(js.includes('invoke("runner_pairing_status"'));
  assert.ok(js.includes('invoke("listener_start_plan"'));
  assert.equal(js.includes('invoke("load_runner_token"'), false);
  assert.ok(js.includes("Runner profile and OS token saved"));
  assert.ok(js.includes("Runner profile is saved, but the token is unavailable. Pair again or reset pairing."));
  assert.ok(js.includes("Runner token is saved, but the profile is unavailable. Pair again or reset pairing."));
  assert.ok(rust.includes("fn redeem_runner_pairing"));
  assert.ok(rust.includes("fn reset_runner_pairing"));
  assert.ok(rust.includes("fn runner_pairing_status"));
  assert.ok(rust.includes("fn listener_start_plan"));
  assert.equal(rust.includes("fn load_runner_token"), false);
  assert.ok(rust.includes("save_runner_profile"));
  assert.ok(rust.includes("clear_runner_profile"));
  assert.ok(rust.includes("load_runner_profile"));
});

test("desktop pairing keeps successful pairing when automatic start fails", () => {
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");

  assert.ok(js.includes("userSafeStartFailure"));
  assert.ok(js.includes("Paired. Runner could not start automatically."));
  assert.ok(js.includes("await startRunner({ confirmStarted: true });"));
  assert.ok(js.includes("Runner exited with code"));
  assert.ok(js.includes("before listening"));
  assert.equal(js.includes("pairState.textContent = \"Pairing failed. Check that the code has not expired, then try again.\";"), false);
  assert.ok(js.includes("checkRunnerStartupSelfTest"));
  assert.ok(js.includes("Checking Runner startup self-test"));
});

test("desktop runtime panel shows local readiness without owning model selection", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");

  assert.ok(html.includes("Local readiness checklist"));
  assert.ok(html.includes("data-hub-connection-status"));
  assert.ok(html.includes("data-pairing-readiness-status"));
  assert.ok(html.includes("data-runtime-llama-status"));
  assert.ok(html.includes("data-model-path-status"));
  assert.ok(html.includes("Chosen in Hub run plans"));
  assert.ok(js.includes("renderLocalReadinessChecklist"));
  assert.ok(js.includes("await stopRunner()"));
  assert.ok(js.includes('invoke("llama_cpp_runtime_plan"'));
  assert.ok(rust.includes("fn llama_cpp_runtime_plan"));
  assert.ok(rust.includes("No install command was run"));
  assert.ok(rust.includes("fn verify_runtime_download_manifest"));
  assert.ok(rust.includes("signature_url"));
  assert.ok(rust.includes("rollback_runtime_id"));
});

test("desktop runtime panel makes native first-run readiness primary and Docker optional", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const capability = JSON.parse(
    readFileSync(new URL("../src-tauri/capabilities/default.json", import.meta.url), "utf8")
  );
  const permissions = capability.permissions.flatMap((permission) => permission.allow || []);
  const shapes = permissions.map((entry) => JSON.stringify(entry.args || []));

  assert.ok(html.includes("Native benchmark suite"));
  assert.ok(html.includes("Docker is not required for your first local benchmark."));
  assert.ok(html.includes("data-native-suite-status"));
  assert.ok(html.includes("data-container-runtime-status"));
  assert.ok(js.includes("desktop-readiness"));
  assert.ok(js.includes("renderDesktopReadiness"));
  assert.ok(shapes.includes(JSON.stringify(["desktop-readiness"])));
});

test("desktop readiness copy does not overclaim when native runtime is missing", () => {
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");

  assert.ok(js.includes("runtime === \"available\""));
  assert.ok(js.includes("Select a native runtime for first-run benchmarks"));
  assert.equal(js.includes("Docker not found. Native benchmarks are available; advanced sandboxed benchmarks are disabled.\";"), false);
});
