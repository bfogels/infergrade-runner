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
  assert.ok(js.includes('invoke("start_runner_listener"'));
  assert.ok(js.includes('invoke("stop_runner_listener"'));
  assert.ok(js.includes('listen("runner-listener-event"'));
  assert.equal(js.includes('Command.sidecar(SIDECAR_NAME, ["start"'), false);
  assert.equal(js.includes('invoke("load_runner_token"'), false);
  assert.ok(js.includes("Runner profile and OS token saved"));
  assert.ok(js.includes("Runner profile is saved, but the token is unavailable. Pair again or reset pairing."));
  assert.ok(js.includes("Runner token is saved, but the profile is unavailable. Pair again or reset pairing."));
  assert.ok(rust.includes("fn redeem_runner_pairing"));
  assert.ok(rust.includes("fn reset_runner_pairing"));
  assert.ok(rust.includes("fn runner_pairing_status"));
  assert.ok(rust.includes("fn listener_start_plan"));
  assert.ok(rust.includes("fn start_runner_listener"));
  assert.ok(rust.includes("fn stop_runner_listener"));
  assert.ok(rust.includes("fn worker_protocol_preview"));
  assert.ok(rust.includes("fn worker_protocol_ping"));
  assert.ok(rust.includes("send_worker_json_request"));
  assert.ok(rust.includes("runner_register_payload"));
  assert.ok(rust.includes("claim_run_job_payload"));
  assert.ok(rust.includes("runner-listener-event"));
  assert.equal(rust.includes("#[tauri::command]\nfn load_runner_token"), false);
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

test("desktop runtime panel shows local readiness and explicit first-run model selection", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");
  const engine = readFileSync(new URL("../../../crates/runner-engine/src/lib.rs", import.meta.url), "utf8");

  assert.ok(html.includes("Local readiness checklist"));
  assert.ok(html.includes("data-hub-connection-status"));
  assert.ok(html.includes("data-pairing-readiness-status"));
  assert.ok(html.includes("data-runtime-llama-status"));
  assert.ok(html.includes("data-model-path-status"));
  assert.ok(html.includes("Select a local GGUF model for the first benchmark."));
  assert.ok(js.includes("renderLocalReadinessChecklist"));
  assert.ok(js.includes("await stopRunner()"));
  assert.ok(js.includes('invoke("llama_cpp_runtime_plan"'));
  assert.ok(rust.includes("fn llama_cpp_runtime_plan"));
  assert.ok(engine.includes("No install command was run"));
  assert.ok(engine.includes("fn verify_runtime_download_manifest"));
  assert.ok(engine.includes("signature_url"));
  assert.ok(engine.includes("rollback_runtime_id"));
});

test("desktop runtime panel keeps native first-run readiness truthful and Docker optional", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const capability = JSON.parse(
    readFileSync(new URL("../src-tauri/capabilities/default.json", import.meta.url), "utf8")
  );
  const permissions = capability.permissions.flatMap((permission) => permission.allow || []);
  const shapes = permissions.map((entry) => JSON.stringify(entry.args || []));

  assert.ok(html.includes("Native benchmark suite"));
  assert.ok(html.includes("Native first-run can run with a local GGUF model and selected llama.cpp runtime."));
  assert.ok(html.includes("Docker is optional for advanced sandboxed benchmarks"));
  assert.ok(html.includes("data-native-suite-status"));
  assert.ok(html.includes("data-container-runtime-status"));
  assert.ok(html.includes("data-first-run-start"));
  assert.ok(html.includes("data-first-run-status"));
  assert.ok(js.includes("desktop-readiness"));
  assert.ok(js.includes("renderDesktopReadiness"));
  assert.ok(shapes.includes(JSON.stringify(["desktop-readiness"])));
});

test("desktop readiness copy does not overclaim when native runtime is missing", () => {
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");

  assert.ok(js.includes("runtime === \"available\""));
  assert.ok(js.includes("Select a native runtime before first-run benchmark support"));
  assert.ok(js.includes("Upload is not wired yet"));
  assert.equal(js.includes("Docker not found. Native benchmarks are available; advanced sandboxed benchmarks are disabled.\";"), false);
});

test("desktop first-run UI calls runner-engine through Tauri and keeps upload disabled", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");

  assert.ok(html.includes("First local benchmark"));
  assert.ok(html.includes("name=\"firstRunModelPath\""));
  assert.ok(html.includes("name=\"firstRunRuntimePath\""));
  assert.ok(html.includes("Run native first benchmark"));
  assert.ok(html.includes("write a local result"));
  assert.ok(html.includes("Upload is not wired yet."));
  assert.ok(js.includes('listen("runner-first-run-event"'));
  assert.ok(js.includes('invoke("run_desktop_native_first_run"'));
  assert.ok(js.includes("readFirstRunModelPath"));
  assert.ok(js.includes(".endsWith(\".gguf\")"));
  assert.ok(js.includes("native_first_run evidence"));
  assert.ok(js.includes("payload?.artifact?.path"));
  assert.ok(rust.includes("fn native_first_run_input"));
  assert.ok(rust.includes("async fn run_desktop_native_first_run"));
  assert.ok(rust.includes("fn desktop_first_run_artifact_dir"));
  assert.ok(rust.includes("write_native_first_run_artifact"));
  assert.ok(rust.includes("LlamaCppRuntime::resolve"));
  assert.ok(rust.includes("engine_run_native_first_run_with_events"));
  assert.ok(rust.includes("RunnerEvent::Error"));
  assert.ok(rust.includes("upload: false"));
});

test("desktop runner engine logic is separated from the Tauri adapter", () => {
  const tauriCargo = readFileSync(new URL("../src-tauri/Cargo.toml", import.meta.url), "utf8");
  const tauriRust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");
  const rootCargo = readFileSync(new URL("../../../Cargo.toml", import.meta.url), "utf8");
  const cliCargo = readFileSync(new URL("../../../apps/runner-cli/Cargo.toml", import.meta.url), "utf8");
  const cliRust = readFileSync(new URL("../../../apps/runner-cli/src/main.rs", import.meta.url), "utf8");

  assert.ok(tauriCargo.includes("infergrade_runner_engine"));
  assert.ok(tauriRust.includes("use infergrade_runner_engine::"));
  assert.equal(tauriRust.includes("fn runner_register_payload("), false);
  assert.equal(tauriRust.includes("fn verify_runtime_download_manifest("), false);
  assert.equal(tauriRust.includes("fn normalize_desktop_api_url("), false);
  assert.ok(rootCargo.includes("crates/runner-engine"));
  assert.ok(rootCargo.includes("apps/runner-cli"));
  assert.ok(cliCargo.includes("infergrade_runner_engine"));
  assert.ok(cliRust.includes("runtime plan"));
  assert.ok(cliRust.includes("llama_cpp_runtime_plan"));
});
