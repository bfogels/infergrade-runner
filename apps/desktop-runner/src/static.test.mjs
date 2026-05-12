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
  assert.ok(capability.permissions.includes("deep-link:default"));
  assert.ok(shapes.some((shape) => shape.includes('"start"') && shape.includes('"--api-url"')));
  assert.equal(shapes.some((shape) => shape.includes('"pair"') && shape.includes('"--api-url"')), false);
  assert.equal(shapes.includes(JSON.stringify(["install-runtime", "--runtime", "llama.cpp"])), false);
  assert.ok(shapes.some((shape) => shape.includes('"install-runtime"') && shape.includes('"--select-existing"')));
});

test("desktop onboarding exposes paste-code pairing, reset, and bundled runner self-test", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");
  const helpers = readFileSync(new URL("./desktopHelpers.js", import.meta.url), "utf8");

  assert.ok(html.includes('value="https://api.infergrade.com"'));
  assert.ok(html.includes("Paste the one-time code from Hub"));
  assert.ok(html.includes("data-reset-pairing"));
  assert.ok(html.includes("data-runner-self-test"));
  assert.ok(html.includes("Tokens are not shown in this browser UI."));
  assert.equal(html.includes("Advanced token fallback"), false);
  assert.equal(html.includes('name="hubToken"'), false);
  assert.equal(html.includes("data-save-token"), false);
  assert.equal(html.includes("data-clear-token"), false);
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
  assert.equal(js.includes("previewToken"), false);
  assert.equal(js.includes("form.elements.hubToken"), false);
  assert.ok(js.includes("typedToken: null"));
  assert.ok(js.includes("typedTokenPresent: false"));
  assert.ok(js.includes("Runner profile and OS token saved"));
  assert.ok(js.includes("Runner profile is saved, but the token is unavailable. Pair again or reset pairing."));
  assert.ok(js.includes("Runner token is saved, but the profile is unavailable. Pair again or reset pairing."));
  assert.ok(rust.includes("fn redeem_runner_pairing"));
  assert.ok(rust.includes("fn reset_runner_pairing"));
  assert.ok(rust.includes("fn runner_pairing_status"));
  assert.ok(rust.includes("fn listener_start_plan"));
  assert.ok(rust.includes("fn start_runner_listener"));
  assert.ok(rust.includes('const SIDECAR_BINARY_NAME: &str = "infergrade-sidecar"'));
  assert.equal(rust.includes('.sidecar("binaries/infergrade-sidecar")'), false);
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

  assert.ok(html.includes("Diagnostics"));
  assert.ok(html.includes("Setup progress"));
  assert.ok(html.includes("Download starter GGUF"));
  assert.ok(html.includes("data-first-run-step=\"paired\""));
  assert.ok(html.includes("data-first-run-step=\"runtime\""));
  assert.ok(html.includes("data-first-run-step=\"model\""));
  assert.ok(html.includes("data-first-run-step=\"ready\""));
  assert.ok(html.includes("data-first-run-step=\"result\""));
  assert.ok(html.includes("data-first-run-again"));
  assert.ok(html.includes("Run again"));
  assert.ok(html.includes("data-first-run-another-model"));
  assert.ok(html.includes("Run another model"));
  assert.ok(html.includes("data-hub-connection-status"));
  assert.ok(html.includes("data-pairing-readiness-status"));
  assert.ok(html.includes("data-runtime-llama-status"));
  assert.ok(html.includes("data-runtime-install-managed"));
  assert.ok(html.includes("data-runtime-reinstall-managed"));
  assert.ok(html.includes("data-runtime-remove-selected"));
  assert.ok(html.includes("data-model-path-status"));
  assert.ok(html.includes("Select a local GGUF model for the first benchmark."));
  assert.ok(js.includes("renderLocalReadinessChecklist"));
  assert.ok(js.includes("renderFirstRunChecklist"));
  assert.ok(js.includes("firstRunStepNodes"));
  assert.ok(js.includes("firstRunModelPathInput"));
  assert.ok(js.includes("firstRunUploadRunIdInput"));
  assert.equal(js.includes("form.elements.firstRunModelPath"), false);
  assert.equal(js.includes("form.elements.firstRunUploadRunId"), false);
  assert.equal(js.includes("form.elements.runtimeId"), false);
  assert.ok(js.includes("Paired through the OS credential store. Tokens stay out of this browser UI."));
  assert.ok(js.includes("Ready to run a local smoke benchmark."));
  assert.ok(js.includes("Run the first local benchmark to create evidence."));
  assert.ok(js.includes("clearFirstRunLocalState"));
  assert.ok(js.includes("Ready to run this local GGUF model again."));
  assert.ok(js.includes("choose another GGUF model"));
  assert.ok(js.includes("updateFirstRunSupportActions();\n  renderLocalReadinessChecklist();"));
  assert.ok(js.includes("await stopRunner()"));
  assert.ok(js.includes('invoke("llama_cpp_runtime_plan"'));
  assert.ok(js.includes('invoke("install_managed_llama_cpp_runtime"'));
  assert.ok(js.includes('invoke("remove_selected_llama_cpp_runtime"'));
  assert.ok(js.includes('invoke("select_existing_llama_cpp_runtime"'));
  assert.ok(js.includes("SHA-256 verified"));
  assert.ok(js.includes("no independent signature"));
  assert.ok(js.includes("Retry install, remove the selected runtime, or select an existing llama.cpp binary."));
  assert.ok(html.includes("Replace selection with managed runtime"));
  assert.ok(js.includes("Replacing the selected llama.cpp runtime with the managed runtime. Local binaries are not deleted."));
  assert.equal(js.includes("executeSidecar(runtimeCommandArgs([\"--select-existing\"])"), false);
  assert.ok(rust.includes("fn llama_cpp_runtime_plan"));
  assert.ok(rust.includes("fn install_managed_llama_cpp_runtime"));
  assert.ok(rust.includes("engine_install_managed_llama_cpp_runtime"));
  assert.ok(rust.includes("fn remove_selected_llama_cpp_runtime"));
  assert.ok(rust.includes("engine_remove_selected_llama_cpp_runtime"));
  assert.ok(rust.includes("fn select_existing_llama_cpp_runtime"));
  assert.ok(rust.includes("engine_select_existing_llama_cpp_runtime"));
  assert.ok(engine.includes("fn install_managed_llama_cpp_runtime"));
  assert.ok(engine.includes("fn remove_selected_llama_cpp_runtime"));
  assert.ok(engine.includes("fn select_existing_llama_cpp_runtime"));
  assert.ok(engine.includes("selected_existing"));
  assert.ok(engine.includes("fn verify_runtime_download_manifest"));
  assert.ok(engine.includes("signature_url"));
  assert.ok(engine.includes("rollback_runtime_id"));
  assert.ok(js.includes("recommended.platform?.human"));
  assert.ok(js.includes("selected_channel"));
  assert.ok(js.includes("Runtime channel:"));
  assert.ok(js.includes("Updates are manual."));
});

test("desktop runtime panel keeps native first-run readiness truthful and Docker optional", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");
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
  assert.ok(js.includes("parseDesktopReadinessOutput"));
  assert.ok(js.includes("Desktop readiness fallback"));
  assert.ok(js.includes('invoke("desktop_sidecar_diagnostic", { args })'));
  assert.ok(js.includes('runDesktopSidecarDiagnostic(["desktop-readiness"])'));
  assert.ok(js.includes('runDesktopSidecarDiagnostic(["desktop-self-test"])'));
  assert.ok(js.includes('runDesktopSidecarDiagnostic(["--version"])'));
  assert.ok(rust.includes("desktop_sidecar_diagnostic"));
  assert.ok(rust.includes('["--version", "desktop-self-test", "desktop-readiness"]'));
  assert.ok(shapes.includes(JSON.stringify(["desktop-readiness"])));
});

test("desktop readiness copy does not overclaim when native runtime is missing", () => {
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");

  assert.ok(js.includes("runtime === \"available\""));
  assert.ok(js.includes("Select a native runtime before first-run benchmark support"));
  assert.ok(js.includes("Not uploaded; enter a Hub run ID"));
  assert.equal(js.includes("Docker not found. Native benchmarks are available; advanced sandboxed benchmarks are disabled.\";"), false);
});

test("desktop first-run UI calls runner-engine through Tauri and keeps upload token out of browser state", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const helpers = readFileSync(new URL("./desktopHelpers.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");
  const tauriConfig = readFileSync(new URL("../src-tauri/tauri.conf.json", import.meta.url), "utf8");
  const tauriCargo = readFileSync(new URL("../src-tauri/Cargo.toml", import.meta.url), "utf8");
  const packageJson = readFileSync(new URL("../package.json", import.meta.url), "utf8");

  assert.ok(html.includes("Run first local benchmark"));
  assert.ok(html.includes("name=\"firstRunModelPath\""));
  assert.ok(html.includes("name=\"firstRunRuntimePath\""));
  assert.ok(html.includes("name=\"firstRunUploadRunId\""));
  assert.ok(html.includes("name=\"firstRunUploadWorkerId\""));
  assert.ok(html.includes("data-first-run-handoff-status"));
  assert.ok(html.includes("Run native first benchmark"));
  assert.ok(html.includes("Pick the downloaded GGUF file"));
  assert.ok(html.includes("Tokens are not shown in this browser UI."));
  assert.ok(js.includes('listen("runner-first-run-event"'));
  assert.ok(js.includes('invoke("run_desktop_native_first_run"'));
  assert.ok(js.includes("readFirstRunModelPath"));
  assert.ok(js.includes("readFirstRunUploadRunId"));
  assert.ok(js.includes("firstRunHandoffFromUrl"));
  assert.ok(js.includes("firstRunHandoffFromDeepLink"));
  assert.ok(js.includes("initFirstRunDeepLinkHandoff"));
  assert.ok(helpers.includes("infergrade-runner:"));
  assert.ok(js.includes("@tauri-apps/plugin-deep-link"));
  assert.ok(helpers.includes("first_run_run_id"));
  assert.ok(helpers.includes("first_run_worker_id"));
  assert.ok(helpers.includes("sensitive handoff parameter"));
  assert.ok(js.includes("URLSearchParams(window.location.search"));
  assert.ok(js.includes("FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY"));
  assert.ok(js.includes("urlHandoff.runId ? urlHandoff.workerId : storedWorkerId"));
  assert.ok(js.includes("removeItem(FIRST_RUN_HANDOFF_WORKER_ID_STORAGE_KEY)"));
  assert.ok(js.includes("applyFirstRunHandoff();"));
  assert.ok(js.includes(".endsWith(\".gguf\")"));
  assert.ok(js.includes("native_first_run evidence"));
  assert.ok(js.includes("payload?.artifact?.path"));
  assert.ok(js.includes("payload?.bundle_artifact?.path"));
  assert.equal(html.includes("firstRunUploadToken"), false);
  assert.equal(js.includes("firstRunUploadToken"), false);
  assert.equal(js.includes('params.get("access_token")'), false);
  assert.equal(js.includes("FIRST_RUN_HANDOFF_TOKEN"), false);
  assert.ok(tauriConfig.includes('"deep-link"'));
  assert.ok(tauriConfig.includes('"schemes": ["infergrade-runner"]'));
  assert.ok(tauriCargo.includes("tauri-plugin-deep-link"));
  assert.ok(packageJson.includes("@tauri-apps/plugin-deep-link"));
  assert.ok(rust.includes("fn native_first_run_input"));
  assert.ok(rust.includes("async fn run_desktop_native_first_run"));
  assert.ok(rust.includes("fn desktop_first_run_artifact_dir"));
  assert.ok(rust.includes("write_native_first_run_artifact"));
  assert.ok(rust.includes("write_native_first_run_bundle_payload"));
  assert.ok(rust.includes("native_first_run_bundle_payload"));
  assert.ok(rust.includes("LlamaCppRuntime::resolve"));
  assert.ok(rust.includes("engine_run_native_first_run_with_events"));
  assert.ok(rust.includes("build_run_claim_request"));
  assert.ok(rust.includes("build_run_bundle_upload_request"));
  assert.ok(rust.includes("execute_hub_json_request"));
  assert.ok(rust.includes("DesktopTokenStore"));
  assert.ok(rust.includes("RunnerEvent::Error"));
  assert.ok(rust.includes("upload: false"));
  assert.ok(rust.includes("tauri_plugin_deep_link::init()"));
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
  assert.ok(cliRust.includes("runtime select-existing --runtime-path <path>"));
  assert.ok(cliRust.includes("select_existing_llama_cpp_runtime"));
  assert.ok(cliRust.includes("llama_cpp_runtime_plan"));
});

test("desktop first-run handoff stays token-free and uploads through secure Rust adapter", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const helpers = readFileSync(new URL("./desktopHelpers.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");

  assert.ok(html.includes("data-first-run-handoff-status"));
  assert.ok(html.includes('name="firstRunUploadRunId"'));
  assert.ok(html.includes("The app reads the saved runner token from secure storage."));
  assert.ok(html.includes("Tokens are not shown in this browser UI."));
  assert.ok(js.includes("FIRST_RUN_HANDOFF_RUN_ID_STORAGE_KEY"));
  assert.ok(js.includes("firstRunHandoffFromParams"));
  assert.ok(js.includes("firstRunHandoffFromDeepLink"));
  assert.ok(js.includes("Ignored first-run handoff with"));
  assert.ok(js.includes('invoke("run_desktop_native_first_run"'));
  assert.ok(js.includes("uploadRunId"));
  assert.ok(js.includes("uploadWorkerId"));
  assert.ok(js.includes("clearFirstRunHandoff();"));
  assert.ok(js.includes("Ready to upload this first-run result to Hub run"));
  assert.equal(js.includes("uploadToken"), false);
  assert.equal(js.includes("execution_token"), false);
  assert.equal(js.includes("runnerToken"), false);
  assert.ok(helpers.includes("sensitiveKeys"));
  assert.ok(helpers.includes("token|secret|authorization|bearer"));
  assert.ok(helpers.includes("authorization"));
  assert.ok(helpers.includes("bearer"));
  assert.ok(rust.includes("fn upload_desktop_native_first_run"));
  assert.ok(rust.includes(".load_runner_token()"));
  assert.ok(rust.includes("build_run_claim_request"));
  assert.ok(rust.includes("build_run_bundle_upload_request"));
  assert.ok(rust.includes("build_run_completion_request"));
  assert.ok(rust.includes("Pair with Hub before uploading a native first-run result."));
  assert.equal(rust.includes("runner_token: String"), false);
});

test("desktop first-run UI renders progress, artifacts, upload state, and selected-runtime guidance", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");

  assert.ok(html.includes("Run native first benchmark"));
  assert.ok(html.includes("Choose a model and selected llama.cpp runtime before running."));
  assert.ok(html.includes("Leave blank to use the selected llama.cpp runtime"));
  assert.ok(js.includes("ensureFirstRunEvents"));
  assert.ok(js.includes('listen("runner-first-run-event"'));
  assert.ok(js.includes("firstRunMessageFromEvent"));
  assert.ok(js.includes("Native first-run started."));
  assert.ok(js.includes("Native first-run completed."));
  assert.ok(js.includes("Artifact: ${payload.artifact.path}."));
  assert.ok(js.includes("Bundle payload: ${payload.bundle_artifact.path}."));
  assert.ok(js.includes("Uploaded bundle ${payload.upload.bundle_id} to Hub run ${payload.upload.run_id}."));
  assert.ok(js.includes("Native first-run completed and uploaded to Hub with native_first_run evidence."));
  assert.ok(js.includes("Native first-run completed locally, but Hub upload failed."));
  assert.ok(js.includes("Select a local GGUF model file before running the first benchmark."));
  assert.ok(js.includes("Use a local GGUF model file for the native first-run benchmark."));
  assert.ok(js.includes("Installed llama.cpp runtime selected. No install command was run."));
  assert.ok(rust.includes("runner-first-run-event"));
  assert.ok(rust.includes("write_native_first_run_artifact"));
  assert.ok(rust.includes("write_native_first_run_bundle_payload"));
  assert.ok(rust.includes("mark_desktop_native_first_run_upload_failed"));
  assert.ok(js.includes("Native first-run completed locally, but Hub upload failed."));
});

test("desktop first-run support actions stay token-free and reuse local artifacts", () => {
  const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const js = readFileSync(new URL("./main.js", import.meta.url), "utf8");
  const rust = readFileSync(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");

  assert.ok(html.includes("data-copy-support-summary"));
  assert.ok(html.includes("data-copy-artifact-path"));
  assert.ok(html.includes("data-retry-first-run-upload"));
  assert.ok(js.includes("lastFirstRunPayload"));
  assert.ok(js.includes('invoke("desktop_support_summary"'));
  assert.ok(js.includes('invoke("retry_desktop_native_first_run_upload"'));
  assert.ok(js.includes("artifactPath"));
  assert.ok(js.includes("bundleArtifactPath"));
  assert.equal(js.includes("payload: lastFirstRunPayload"), false);
  assert.ok(js.includes("Retry upload requires saved local result and bundle artifacts."));
  assert.ok(js.includes("navigator.clipboard.writeText"));
  assert.ok(js.includes("Copy support summary"));
  assert.ok(js.includes("Copy artifact path"));
  assert.ok(js.includes("Retry upload"));
  assert.equal(js.includes("firstRunUploadToken"), false);
  assert.equal(js.includes("runnerToken"), false);
  assert.ok(rust.includes("fn desktop_support_summary"));
  assert.ok(rust.includes("build_support_summary"));
  assert.ok(rust.includes("fn retry_desktop_native_first_run_upload"));
  assert.ok(rust.includes("artifact_path_under_root"));
  assert.ok(rust.includes("load_retry_first_run_payload"));
  assert.ok(rust.includes("load_retry_bundle_payload"));
  assert.ok(rust.includes("upload_desktop_native_first_run"));
});
