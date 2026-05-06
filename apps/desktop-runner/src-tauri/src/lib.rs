use infergrade_runner_engine::{
    build_hub_json_request, build_listener_start_plan, build_pairing_redeem_request,
    build_run_bundle_upload_request, build_run_completion_request, complete_pairing_response,
    desktop_environment, execute_hub_json_request, hostname,
    llama_cpp_runtime_plan as engine_llama_cpp_runtime_plan, native_first_run_bundle_payload,
    normalize_api_url, pairing_error_detail, pairing_status_payload, preferred_execution_mode,
    profile_string, redact_listener_text, redact_worker_response, reset_pairing_state,
    run_native_first_run_with_events as engine_run_native_first_run_with_events,
    runner_id_from_profile, selected_llama_cpp_runtime_path, worker_request_url,
    write_native_first_run_artifact, write_native_first_run_bundle_payload, HubMethod,
    LlamaCppRuntime, NativeFirstRunBundleOptions, NativeFirstRunInput, NativeFirstRunResult,
    PairingInput, ProfileStore, RunnerError, RunnerEvent, RunnerProfile, RunnerProtocolPingInput,
    RunnerProtocolPreviewInput, TokenStore,
};
use keyring::{Entry, Error as KeyringError};
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

const KEYRING_SERVICE: &str = "com.infergrade.runner";
const KEYRING_USER: &str = "hub-runner-token";

#[derive(Default)]
struct ListenerProcess {
    child: Mutex<Option<CommandChild>>,
}

struct DesktopProfileStore;

impl ProfileStore for DesktopProfileStore {
    fn save_profile(&self, profile: &RunnerProfile) -> Result<(), RunnerError> {
        let value = serde_json::to_value(profile).map_err(|error| {
            RunnerError::new(
                "profile_serialize_failed",
                format!("could not serialize Runner profile: {error}"),
            )
        })?;
        save_runner_profile(&value)
            .map(|_| ())
            .map_err(|error| RunnerError::new("profile_save_failed", error))
    }

    fn load_profile(&self) -> Result<Option<RunnerProfile>, RunnerError> {
        load_runner_profile()?
            .map(serde_json::from_value)
            .transpose()
            .map_err(|error| {
                RunnerError::new(
                    "profile_parse_failed",
                    format!("could not parse Runner profile: {error}"),
                )
            })
    }

    fn clear_profile(&self) -> Result<bool, RunnerError> {
        clear_runner_profile()
            .and_then(|value| {
                value
                    .get("removed")
                    .and_then(Value::as_bool)
                    .ok_or_else(|| {
                        "profile reset result did not include removed status".to_string()
                    })
            })
            .map_err(|error| RunnerError::new("profile_clear_failed", error))
    }
}

struct DesktopTokenStore;

impl TokenStore for DesktopTokenStore {
    fn save_runner_token(&self, token: &str) -> Result<(), RunnerError> {
        save_runner_token_value(token).map_err(|error| RunnerError::new("token_save_failed", error))
    }

    fn load_runner_token(&self) -> Result<Option<String>, RunnerError> {
        load_runner_token_value().map_err(|error| RunnerError::new("token_load_failed", error))
    }

    fn clear_runner_token(&self) -> Result<bool, RunnerError> {
        let had_token = load_runner_token_value()
            .map_err(|error| RunnerError::new("token_load_failed", error))?
            .is_some();
        clear_runner_token()
            .map(|_| had_token)
            .map_err(|error| RunnerError::new("token_clear_failed", error))
    }
}

fn runner_token_entry() -> Result<Entry, String> {
    Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .map_err(|error| format!("could not open OS credential store: {error}"))
}

fn is_user_canceled(error: &KeyringError) -> bool {
    let message = error.to_string().to_lowercase();
    message.contains("cancel") || message.contains("user interaction")
}

fn runner_config_dir() -> Result<PathBuf, String> {
    if let Ok(value) = env::var("INFERGRADE_CONFIG_DIR") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }
    if let Ok(value) = env::var("XDG_CONFIG_HOME") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed).join("infergrade"));
        }
    }
    if cfg!(windows) {
        if let Ok(value) = env::var("APPDATA") {
            let trimmed = value.trim();
            if !trimmed.is_empty() {
                return Ok(PathBuf::from(trimmed).join("infergrade"));
            }
        }
    }
    let home = env::var("HOME")
        .or_else(|_| env::var("USERPROFILE"))
        .map_err(|_| "Could not resolve a home directory for the Runner profile.".to_string())?;
    Ok(PathBuf::from(home).join(".config").join("infergrade"))
}

fn runner_profile_path() -> Result<PathBuf, String> {
    Ok(runner_config_dir()?.join("runner_profile.json"))
}

fn desktop_first_run_artifact_dir() -> Result<PathBuf, String> {
    Ok(runner_config_dir()?
        .join("first-run-artifacts")
        .join("native-first-run"))
}

fn selected_llama_cpp_runtime() -> Value {
    match selected_llama_cpp_runtime_path()
        .ok()
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
    {
        Some(selection) => json!({"status": "selected", "selection": selection}),
        None => json!({"status": "not_selected", "selection": Value::Null}),
    }
}

fn load_runner_profile() -> Result<Option<Value>, String> {
    let path = runner_profile_path()?;
    match fs::read_to_string(&path) {
        Ok(text) => serde_json::from_str::<Value>(&text)
            .map(Some)
            .map_err(|error| format!("could not parse Runner profile: {error}")),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!("could not read Runner profile: {error}")),
    }
}

async fn send_worker_json_request(
    api_url: &str,
    path: &str,
    payload: &Value,
    token: &str,
) -> Result<Value, String> {
    let url = worker_request_url(api_url, path)?;
    let token = token.trim();
    let client = reqwest::Client::new();
    let mut request = client.post(url).json(payload);
    if !token.is_empty() {
        request = request.bearer_auth(token);
    }
    let response = request
        .send()
        .await
        .map_err(|error| format!("Could not reach Hub worker endpoint: {error}"))?;
    let status = response.status();
    let text = response
        .text()
        .await
        .map_err(|error| format!("Could not read Hub worker response: {error}"))?;
    let parsed = serde_json::from_str::<Value>(&text).unwrap_or_else(|_| json!({"error": text}));
    if !status.is_success() {
        let redacted = redact_worker_response(parsed, &[token.to_string()]);
        return Err(format!(
            "Hub worker request failed: HTTP {}: {}",
            status.as_u16(),
            pairing_error_detail(&redacted).unwrap_or("no detail")
        ));
    }
    Ok(redact_worker_response(parsed, &[token.to_string()]))
}

fn save_runner_profile(profile: &Value) -> Result<PathBuf, String> {
    let path = runner_profile_path()?;
    let parent = path
        .parent()
        .ok_or_else(|| "Runner profile path has no parent directory.".to_string())?;
    fs::create_dir_all(parent)
        .map_err(|error| format!("could not create Runner profile directory: {error}"))?;
    let text = serde_json::to_string_pretty(profile)
        .map_err(|error| format!("could not serialize Runner profile: {error}"))?
        + "\n";
    fs::write(&path, text).map_err(|error| format!("could not save Runner profile: {error}"))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(&path, fs::Permissions::from_mode(0o600));
    }
    Ok(path)
}

fn clear_runner_profile() -> Result<Value, String> {
    let path = runner_profile_path()?;
    let removed = match fs::remove_file(&path) {
        Ok(()) => true,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
        Err(error) => return Err(format!("could not remove Runner profile: {error}")),
    };
    Ok(json!({
        "removed": removed,
        "profile_path": path.display().to_string(),
    }))
}

fn save_runner_token_value(token: &str) -> Result<(), String> {
    let token = token.trim();
    if token.is_empty() {
        return Err("runner token cannot be empty".to_string());
    }

    let entry = runner_token_entry()?;
    match entry.set_password(token) {
        Ok(()) => Ok(()),
        Err(first_error) if is_user_canceled(&first_error) => {
            Err(format!("credential storage was canceled: {first_error}"))
        }
        Err(first_error) => {
            let _ = entry.delete_credential();
            entry.set_password(token).map_err(|second_error| {
                format!("could not replace runner token after {first_error}: {second_error}")
            })
        }
    }
}

#[tauri::command]
fn save_runner_token(token: String) -> Result<(), String> {
    save_runner_token_value(&token)
}

fn runner_token_available() -> Result<bool, String> {
    Ok(load_runner_token_value()?.is_some())
}

fn load_runner_token_value() -> Result<Option<String>, String> {
    match runner_token_entry()?.get_password() {
        Ok(token) => {
            let token = token.trim().to_string();
            Ok(if token.is_empty() { None } else { Some(token) })
        }
        Err(KeyringError::NoEntry) => Ok(None),
        Err(error) if is_user_canceled(&error) => Ok(None),
        Err(error) => Err(format!("could not load runner token: {error}")),
    }
}

#[tauri::command]
fn clear_runner_token() -> Result<(), String> {
    match runner_token_entry()?.delete_credential() {
        Ok(()) | Err(KeyringError::NoEntry) => Ok(()),
        Err(error) if is_user_canceled(&error) => Ok(()),
        Err(error) => Err(format!("could not clear runner token: {error}")),
    }
}

#[tauri::command]
fn runner_pairing_status() -> Result<Value, String> {
    let profile_path = runner_profile_path()?;
    let profile = DesktopProfileStore
        .load_profile()
        .map_err(|error| error.message().to_string())?;
    let token_available = runner_token_available()?;
    pairing_status_payload(profile, token_available, profile_path.display().to_string())
        .map_err(|error| error.message().to_string())
}

#[tauri::command]
fn listener_start_plan(api_url: String, typed_token_present: bool) -> Result<Value, String> {
    let profile = load_runner_profile()?;
    let token_available = runner_token_available()?;
    build_listener_start_plan(
        &api_url,
        typed_token_present,
        profile.as_ref(),
        token_available,
    )
}

#[tauri::command]
fn worker_protocol_preview(api_url: String) -> Result<Value, String> {
    let profile = load_runner_profile()?;
    let execution_mode = profile_string(profile.as_ref(), "preferred_execution_mode")
        .unwrap_or_else(|| preferred_execution_mode().to_string());
    let runner_id = runner_id_from_profile(profile.as_ref());
    RunnerProtocolPreviewInput {
        api_url,
        runner_id,
        execution_mode,
        hostname: hostname(),
    }
    .build()
    .and_then(|preview| {
        serde_json::to_value(preview).map_err(|error| {
            RunnerError::new(
                "worker_protocol_preview_serialize_failed",
                format!("could not serialize worker protocol preview: {error}"),
            )
        })
    })
    .map_err(|error| error.message().to_string())
}

#[tauri::command]
async fn worker_protocol_ping(api_url: String) -> Result<Value, String> {
    let profile = load_runner_profile()?
        .ok_or_else(|| "Pair this machine before sending Runner register/heartbeat.".to_string())?;
    let token = load_runner_token_value()?
        .ok_or_else(|| "Pair this machine before sending Runner register/heartbeat.".to_string())?;
    let execution_mode = profile_string(Some(&profile), "preferred_execution_mode")
        .unwrap_or_else(|| preferred_execution_mode().to_string());
    let runner_id = runner_id_from_profile(Some(&profile));
    let plan = RunnerProtocolPingInput {
        api_url,
        runner_id,
        execution_mode,
        hostname: hostname(),
    }
    .build()
    .map_err(|error| error.message().to_string())?;
    let register_payload = serde_json::to_value(&plan.register)
        .map_err(|error| format!("Could not serialize runner register payload: {error}"))?;
    let heartbeat_payload = serde_json::to_value(&plan.heartbeat)
        .map_err(|error| format!("Could not serialize runner heartbeat payload: {error}"))?;
    let register = send_worker_json_request(
        &plan.api_url,
        &plan.register_endpoint,
        &register_payload,
        &token,
    )
    .await?;
    let heartbeat = send_worker_json_request(
        &plan.api_url,
        &plan.heartbeat_endpoint,
        &heartbeat_payload,
        &token,
    )
    .await?;
    Ok(json!({
        "status": "sent",
        "runner_id": plan.runner_id,
        "execution_mode": plan.execution_mode,
        "register": register,
        "heartbeat": heartbeat,
    }))
}

fn emit_listener_event(app: &AppHandle, payload: Value) {
    let _ = app.emit("runner-listener-event", payload);
}

fn emit_first_run_event(app: &AppHandle, event: RunnerEvent) {
    if let Ok(payload) = serde_json::to_value(event) {
        let _ = app.emit("runner-first-run-event", payload);
    }
}

#[tauri::command]
fn start_runner_listener(
    app: AppHandle,
    state: State<ListenerProcess>,
    api_url: String,
    typed_token: Option<String>,
) -> Result<Value, String> {
    if state
        .child
        .lock()
        .map_err(|_| "listener state is unavailable".to_string())?
        .is_some()
    {
        return Ok(json!({"status": "already_running"}));
    }

    let typed_token = typed_token.unwrap_or_default().trim().to_string();
    let typed_token_present = !typed_token.is_empty();
    let profile = load_runner_profile()?;
    let stored_token = load_runner_token_value()?;
    let plan = build_listener_start_plan(
        &api_url,
        typed_token_present,
        profile.as_ref(),
        stored_token.is_some(),
    )?;
    if plan["can_start"] != true {
        return Err("Pair this machine before starting the local Runner listener.".to_string());
    }
    let normalized_api_url = plan
        .get("api_url")
        .and_then(Value::as_str)
        .ok_or_else(|| "listener start plan did not include a Hub API URL".to_string())?
        .to_string();
    let token_for_child = if typed_token_present {
        Some(typed_token)
    } else {
        stored_token
    };
    let sensitive_values = token_for_child
        .as_ref()
        .map(|token| vec![token.clone()])
        .unwrap_or_default();

    let mut command = app
        .shell()
        .sidecar("binaries/infergrade-sidecar")
        .map_err(|error| format!("could not prepare Runner sidecar: {error}"))?
        .args(["start", "--api-url", &normalized_api_url]);
    if let Some(token) = token_for_child {
        command = command.env("INFERGRADE_HUB_TOKEN", token);
    }
    let (mut events, child) = command
        .spawn()
        .map_err(|error| format!("could not start Runner listener: {error}"))?;
    let pid = child.pid();
    *state
        .child
        .lock()
        .map_err(|_| "listener state is unavailable".to_string())? = Some(child);

    let event_app = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    emit_listener_event(
                        &event_app,
                        json!({"type": "stdout", "line": redact_listener_text(line.trim_end(), &sensitive_values)}),
                    );
                }
                CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes);
                    emit_listener_event(
                        &event_app,
                        json!({"type": "stderr", "line": redact_listener_text(line.trim_end(), &sensitive_values)}),
                    );
                }
                CommandEvent::Error(error) => emit_listener_event(
                    &event_app,
                    json!({"type": "error", "detail": redact_listener_text(&error, &sensitive_values)}),
                ),
                CommandEvent::Terminated(payload) => {
                    let listener_state = event_app.state::<ListenerProcess>();
                    if let Ok(mut child) = listener_state.child.lock() {
                        *child = None;
                    }
                    emit_listener_event(
                        &event_app,
                        json!({"type": "terminated", "code": payload.code}),
                    );
                    break;
                }
                _ => {}
            }
        }
    });

    Ok(json!({
        "status": "started",
        "pid": pid,
        "plan": plan,
    }))
}

#[tauri::command]
fn stop_runner_listener(state: State<ListenerProcess>) -> Result<Value, String> {
    let child = state
        .child
        .lock()
        .map_err(|_| "listener state is unavailable".to_string())?
        .take();
    match child {
        Some(child) => {
            let pid = child.pid();
            child
                .kill()
                .map_err(|error| format!("could not stop Runner listener: {error}"))?;
            Ok(json!({"status": "stop_requested", "pid": pid}))
        }
        None => Ok(json!({"status": "not_running"})),
    }
}

#[tauri::command]
fn reset_runner_pairing() -> Result<Value, String> {
    let profile_path = runner_profile_path()?;
    reset_pairing_state(
        &DesktopProfileStore,
        &DesktopTokenStore,
        profile_path.display().to_string(),
    )
    .map_err(|error| error.message().to_string())
}

#[tauri::command]
fn llama_cpp_runtime_plan() -> Value {
    engine_llama_cpp_runtime_plan(selected_llama_cpp_runtime())
}

fn native_first_run_input(model_path: &str) -> NativeFirstRunInput {
    NativeFirstRunInput {
        model_path: PathBuf::from(model_path.trim()),
        runtime_hint: Some("auto".to_string()),
        prompt: "Write one short sentence that says the local InferGrade runner is ready."
            .to_string(),
        max_tokens: 32,
        upload: false,
    }
}

fn desktop_native_first_run_response(
    input: NativeFirstRunInput,
    runtime: &dyn infergrade_runner_engine::NativeFirstRunRuntime,
    artifact_dir: &PathBuf,
    mut emit: impl FnMut(RunnerEvent),
) -> Result<Value, String> {
    let result = engine_run_native_first_run_with_events(input, runtime, &mut emit)
        .map_err(|error| error.message().to_string())?;
    let bundle_payload = infergrade_runner_engine::native_first_run_bundle_payload(
        &result,
        NativeFirstRunBundleOptions {
            submission_channel: "infergrade_desktop_runner".to_string(),
            ..NativeFirstRunBundleOptions::default()
        },
    );
    let mut payload = json!({
        "status": "completed",
        "uploaded": false,
        "result": result,
    });
    let artifact = write_native_first_run_artifact(artifact_dir, &payload)
        .map_err(|error| error.message().to_string())?;
    payload["artifact"] = serde_json::to_value(artifact).map_err(|error| {
        format!("Could not serialize native first-run artifact metadata: {error}")
    })?;
    let bundle_artifact = write_native_first_run_bundle_payload(artifact_dir, &bundle_payload)
        .map_err(|error| error.message().to_string())?;
    payload["bundle_artifact"] = serde_json::to_value(bundle_artifact).map_err(|error| {
        format!("Could not serialize native first-run bundle artifact metadata: {error}")
    })?;
    Ok(payload)
}

async fn upload_desktop_native_first_run(
    payload: &mut Value,
    artifact_dir: &PathBuf,
    run_id: &str,
    worker_id: Option<&str>,
) -> Result<(), String> {
    let token = DesktopTokenStore
        .load_runner_token()
        .map_err(|error| error.message().to_string())?
        .ok_or_else(|| "Pair with Hub before uploading a native first-run result.".to_string())?;
    let profile = load_runner_profile()?;
    let api_url = profile_string(profile.as_ref(), "api_url")
        .unwrap_or_else(|| "https://api.infergrade.com".to_string());
    let worker_id = worker_id
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .unwrap_or_else(|| runner_id_from_profile(profile.as_ref()));
    let result: NativeFirstRunResult = serde_json::from_value(payload["result"].clone())
        .map_err(|error| format!("Could not rebuild native first-run result: {error}"))?;
    let bundle_payload = native_first_run_bundle_payload(
        &result,
        NativeFirstRunBundleOptions {
            submission_channel: "infergrade_desktop_runner".to_string(),
            ..NativeFirstRunBundleOptions::default()
        },
    );
    let upload_request =
        build_run_bundle_upload_request(&api_url, run_id, bundle_payload, Some(&token))
            .map_err(|error| error.message().to_string())?;
    let upload_response = execute_hub_json_request(&upload_request)
        .await
        .map_err(|error| error.message().to_string())?;
    let redacted_upload_body =
        redact_worker_response(upload_response.body.clone(), &[token.to_string()]);
    let bundle_id = upload_response
        .body
        .get("bundle_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "Hub upload response did not include bundle_id".to_string())?
        .to_string();
    let completion_request = build_run_completion_request(
        &api_url,
        run_id,
        &worker_id,
        &bundle_id,
        Some(redacted_upload_body.clone()),
        Some(&token),
    )
    .map_err(|error| error.message().to_string())?;
    let completion_response = execute_hub_json_request(&completion_request)
        .await
        .map_err(|error| error.message().to_string())?;
    let redacted_completion_body =
        redact_worker_response(completion_response.body.clone(), &[token.to_string()]);
    payload["uploaded"] = Value::Bool(true);
    payload["result"]["uploaded"] = Value::Bool(true);
    payload["upload"] = json!({
        "uploaded": true,
        "run_id": run_id,
        "worker_id": worker_id,
        "bundle_id": bundle_id,
        "server": redacted_upload_body,
        "completion": redacted_completion_body,
    });
    let mut persisted_payload = payload.clone();
    if let Some(entries) = persisted_payload.as_object_mut() {
        entries.remove("artifact");
    }
    let artifact = write_native_first_run_artifact(artifact_dir, &persisted_payload)
        .map_err(|error| error.message().to_string())?;
    payload["artifact"] = serde_json::to_value(artifact).map_err(|error| {
        format!("Could not serialize native first-run artifact metadata: {error}")
    })?;
    payload["artifact"]["uploaded"] = Value::Bool(true);
    Ok(())
}

fn mark_desktop_native_first_run_upload_failed(payload: &mut Value, run_id: &str, error: String) {
    payload["uploaded"] = Value::Bool(false);
    payload["result"]["uploaded"] = Value::Bool(false);
    payload["upload"] = json!({
        "uploaded": false,
        "run_id": run_id,
        "error": error,
    });
}

#[tauri::command]
async fn run_desktop_native_first_run(
    app: AppHandle,
    model_path: String,
    runtime_path: Option<String>,
    upload_run_id: Option<String>,
    upload_worker_id: Option<String>,
) -> Result<Value, String> {
    let input = native_first_run_input(&model_path);
    let runtime_path = runtime_path
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
        .map(PathBuf::from);
    let artifact_dir = desktop_first_run_artifact_dir()?;
    let local_artifact_dir = artifact_dir.clone();
    let event_app = app.clone();
    let mut result = tauri::async_runtime::spawn_blocking(move || {
        emit_first_run_event(
            &event_app,
            RunnerEvent::BenchmarkProgress {
                benchmark_id: "native_first_run".to_string(),
                message: "Resolving selected llama.cpp runtime.".to_string(),
                progress_percent: Some(1.0),
            },
        );
        let runtime = match LlamaCppRuntime::resolve(runtime_path) {
            Ok(runtime) => runtime,
            Err(message) => {
                emit_first_run_event(
                    &event_app,
                    RunnerEvent::Error {
                        code: "llama_cpp_runtime_unavailable".to_string(),
                        message: message.clone(),
                    },
                );
                return Err(message);
            }
        };
        desktop_native_first_run_response(input, &runtime, &local_artifact_dir, |event| {
            emit_first_run_event(&event_app, event);
        })
    })
    .await
    .map_err(|error| format!("Native first-run task failed: {error}"))??;
    if let Some(run_id) = upload_run_id
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
    {
        if let Err(error) = upload_desktop_native_first_run(
            &mut result,
            &artifact_dir,
            &run_id,
            upload_worker_id.as_deref(),
        )
        .await
        {
            mark_desktop_native_first_run_upload_failed(&mut result, &run_id, error);
        }
    }
    Ok(result)
}

#[tauri::command]
async fn redeem_runner_pairing(
    api_url: String,
    pair_code: String,
    label: Option<String>,
) -> Result<Value, String> {
    let api_url = normalize_api_url(&api_url)?;
    let payload = build_pairing_redeem_request(
        PairingInput { pair_code, label },
        hostname(),
        preferred_execution_mode(),
        desktop_environment(),
    )
    .map_err(|error| error.message().to_string())?;
    let request = build_hub_json_request(
        HubMethod::Post,
        &api_url,
        "/v1/runner-pairings/redeem",
        Some(
            serde_json::to_value(&payload)
                .map_err(|error| format!("Could not serialize pairing request payload: {error}"))?,
        ),
        None,
    )
    .map_err(|error| error.message().to_string())?;
    let response = reqwest::Client::new()
        .post(request.url)
        .json(&payload)
        .send()
        .await
        .map_err(|error| format!("Could not reach Hub pairing endpoint: {error}"))?;
    let status = response.status();
    let text = response
        .text()
        .await
        .map_err(|error| format!("Could not read Hub pairing response: {error}"))?;
    let parsed = serde_json::from_str::<Value>(&text).ok();
    if !status.is_success() {
        let detail = parsed
            .as_ref()
            .and_then(pairing_error_detail)
            .unwrap_or_else(|| text.trim())
            .chars()
            .take(300)
            .collect::<String>();
        return Err(format!(
            "Runner pairing failed: HTTP {}: {detail}",
            status.as_u16()
        ));
    }
    let body = parsed.ok_or_else(|| "Hub pairing response was not valid JSON.".to_string())?;
    let profile_path = runner_profile_path()?;
    complete_pairing_response(
        body,
        &DesktopProfileStore,
        &DesktopTokenStore,
        profile_path.display().to_string(),
    )
    .map(|completion| completion.ui_response)
    .map_err(|error| error.message().to_string())
}

pub fn run() {
    tauri::Builder::default()
        .manage(ListenerProcess::default())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            save_runner_token,
            clear_runner_token,
            runner_pairing_status,
            listener_start_plan,
            worker_protocol_preview,
            worker_protocol_ping,
            start_runner_listener,
            stop_runner_listener,
            reset_runner_pairing,
            llama_cpp_runtime_plan,
            run_desktop_native_first_run,
            redeem_runner_pairing
        ])
        .run(tauri::generate_context!())
        .expect("error while running InferGrade desktop runner");
}

#[cfg(test)]
mod tests {
    use super::*;
    use infergrade_runner_engine::{
        claim_run_job_payload, runner_heartbeat_payload, runner_register_payload,
        sanitized_runner_profile, ui_pairing_response, verify_runtime_download_manifest,
        worker_request_preview, NativeFirstRunRuntime, NativeRuntimeOutput, LLAMA_CPP_RUNTIME_ID,
    };
    use std::sync::{Mutex as TestMutex, OnceLock};

    fn env_test_lock() -> &'static TestMutex<()> {
        static LOCK: OnceLock<TestMutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| TestMutex::new(()))
    }

    #[test]
    fn normalizes_hosted_and_local_api_urls() {
        assert_eq!(
            normalize_api_url("").expect("hosted default"),
            "https://api.infergrade.com/"
        );
        assert_eq!(
            normalize_api_url("api.infergrade.com").expect("hosted shorthand"),
            "https://api.infergrade.com/"
        );
        assert_eq!(
            normalize_api_url("localhost:8000").expect("local shorthand"),
            "http://localhost:8000/"
        );
        assert_eq!(
            normalize_api_url("127.0.0.1:8000").expect("loopback shorthand"),
            "http://127.0.0.1:8000/"
        );
    }

    #[test]
    fn desktop_first_run_input_is_local_native_and_upload_disabled() {
        let input = native_first_run_input(" /tmp/model.gguf ");

        assert_eq!(input.model_path, PathBuf::from("/tmp/model.gguf"));
        assert_eq!(input.runtime_hint.as_deref(), Some("auto"));
        assert_eq!(input.max_tokens, 32);
        assert_eq!(input.upload, false);
        assert!(input.prompt.contains("InferGrade runner"));
    }

    struct DesktopFirstRunFakeRuntime;

    impl NativeFirstRunRuntime for DesktopFirstRunFakeRuntime {
        fn run(&self, _input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String> {
            Ok(NativeRuntimeOutput {
                runtime_id: "llama.cpp-desktop-test".to_string(),
                stdout: "hello from desktop first-run".to_string(),
                stderr: String::new(),
                exit_code: 0,
                load_time_ms: 10,
                time_to_first_token_ms: 5,
                decode_tokens_per_second: 20.5,
                generated_tokens: 3,
                peak_memory_bytes: None,
            })
        }
    }

    #[test]
    fn desktop_first_run_response_forwards_events_and_keeps_upload_disabled() {
        let model_path = env::temp_dir().join(format!(
            "infergrade-desktop-first-run-{}.gguf",
            std::process::id()
        ));
        fs::write(&model_path, b"fake gguf").expect("model file");
        let input = NativeFirstRunInput {
            model_path: model_path.clone(),
            runtime_hint: Some("auto".to_string()),
            prompt: "hello".to_string(),
            max_tokens: 8,
            upload: false,
        };
        let artifact_dir = env::temp_dir().join(format!(
            "infergrade-desktop-first-run-artifact-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&artifact_dir);
        let mut events = Vec::new();

        let response = desktop_native_first_run_response(
            input,
            &DesktopFirstRunFakeRuntime,
            &artifact_dir,
            |event| {
                events.push(event);
            },
        )
        .expect("desktop response");

        assert_eq!(response["status"], "completed");
        assert_eq!(response["uploaded"], false);
        assert_eq!(response["result"]["uploaded"], false);
        assert_eq!(response["result"]["evidence_kind"], "native_first_run");
        assert_eq!(response["result"]["runtime_id"], "llama.cpp-desktop-test");
        assert_eq!(response["artifact"]["uploaded"], false);
        assert_eq!(
            response["artifact"]["format"],
            "infergrade.native_first_run.v1"
        );
        let artifact_path = response["artifact"]["path"]
            .as_str()
            .expect("artifact path");
        let artifact_text = fs::read_to_string(artifact_path).expect("artifact text");
        let artifact_json: Value = serde_json::from_str(&artifact_text).expect("artifact JSON");
        assert_eq!(artifact_json["result"]["evidence_kind"], "native_first_run");
        assert_eq!(artifact_json["result"]["uploaded"], false);
        assert_eq!(artifact_json.get("artifact"), None);
        assert_eq!(response["bundle_artifact"]["uploaded"], false);
        assert_eq!(
            response["bundle_artifact"]["format"],
            "infergrade.bundle_upload.v1"
        );
        let bundle_path = response["bundle_artifact"]["path"]
            .as_str()
            .expect("bundle artifact path");
        let bundle_text = fs::read_to_string(bundle_path).expect("bundle text");
        let bundle_json: Value = serde_json::from_str(&bundle_text).expect("bundle JSON");
        assert_eq!(
            bundle_json["results"][0]["provenance"]["source_bundle_origin"],
            "infergrade_native_first_run"
        );
        assert_eq!(
            bundle_json["results"][0]["verification"]["verification_level"],
            "experimental"
        );
        assert_eq!(
            bundle_json["results"][0]["derived"]["comparison_grade"],
            "informational_only"
        );
        assert!(events.iter().any(|event| matches!(
            event,
            RunnerEvent::BenchmarkStarted { benchmark_id } if benchmark_id == "native_first_run"
        )));
        assert!(events.iter().any(|event| matches!(
            event,
            RunnerEvent::BenchmarkCompleted { benchmark_id } if benchmark_id == "native_first_run"
        )));

        let _ = fs::remove_file(model_path);
        let _ = fs::remove_dir_all(artifact_dir);
    }

    #[test]
    fn desktop_first_run_upload_failure_keeps_local_result_successful() {
        let mut response = json!({
            "status": "completed",
            "uploaded": false,
            "result": {
                "uploaded": false,
                "evidence_kind": "native_first_run"
            },
            "artifact": {
                "path": "/tmp/native-first-run-result.json"
            }
        });

        mark_desktop_native_first_run_upload_failed(
            &mut response,
            "run_upload_failed_123",
            "Hub request failed with HTTP 403: run is not owned by this paired runner".to_string(),
        );

        assert_eq!(response["status"], "completed");
        assert_eq!(response["uploaded"], false);
        assert_eq!(response["result"]["uploaded"], false);
        assert_eq!(response["result"]["evidence_kind"], "native_first_run");
        assert_eq!(response["upload"]["uploaded"], false);
        assert_eq!(response["upload"]["run_id"], "run_upload_failed_123");
        assert!(response["upload"]["error"]
            .as_str()
            .expect("upload error")
            .contains("paired runner"));
    }

    #[test]
    fn rejects_cleartext_hosted_api_urls() {
        let error =
            normalize_api_url("http://api.infergrade.com").expect_err("cleartext hosted rejected");
        assert!(error.contains("HTTPS"));
    }

    #[test]
    fn desktop_pairing_payload_prefers_native_on_apple_silicon() {
        let environment = desktop_environment();
        assert_eq!(environment["source"], "desktop_rust_supervisor");
        if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
            assert_eq!(preferred_execution_mode(), "local_native");
            assert_eq!(environment["hardware_class"], "apple_silicon");
        }
    }

    #[test]
    fn extracts_pairing_error_details_from_hub_envelopes() {
        assert_eq!(
            pairing_error_detail(&json!({"error": {"message": "pair code expired"}})),
            Some("pair code expired")
        );
        assert_eq!(
            pairing_error_detail(&json!({"detail": "pair_code is required"})),
            Some("pair_code is required")
        );
    }

    #[test]
    fn runtime_plan_is_inspection_only_and_recommends_platform_lane() {
        let plan = llama_cpp_runtime_plan();
        assert_eq!(plan["runtime_family"], "llama.cpp");
        assert_eq!(
            plan["download_policy"]["requires_explicit_user_action"],
            true
        );
        assert!(
            plan["message"]
                .as_str()
                .unwrap_or("")
                .contains("install command")
                || plan["native_runtime_status"] == "available"
        );
        if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
            assert_eq!(
                plan["recommended_runtime"]["runtime_id"],
                LLAMA_CPP_RUNTIME_ID
            );
            assert_eq!(plan["recommended_runtime"]["accelerator"], "metal");
        }
    }

    #[test]
    fn runtime_download_manifest_requires_supply_chain_and_rollback_fields() {
        let valid = json!({
            "runtime_id": "llama-cpp-metal-2026-05",
            "archive_url": "https://downloads.infergrade.com/runtimes/llama-cpp-metal-2026-05.tar.zst",
            "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "signature_url": "https://downloads.infergrade.com/runtimes/llama-cpp-metal-2026-05.tar.zst.minisig",
            "expected_binaries": ["llama-cli", "llama-server", "llama-perplexity"],
            "rollback_runtime_id": "llama-cpp-homebrew-stable-2026-04",
        });
        assert!(verify_runtime_download_manifest(&valid).is_ok());

        let mut insecure = valid.clone();
        insecure["archive_url"] = Value::String("http://example.com/runtime.tar.zst".to_string());
        assert!(verify_runtime_download_manifest(&insecure)
            .expect_err("insecure runtime url rejected")
            .contains("HTTPS"));

        let mut missing_checksum = valid.clone();
        missing_checksum["sha256"] = Value::String("abc".to_string());
        assert!(verify_runtime_download_manifest(&missing_checksum)
            .expect_err("short checksum rejected")
            .contains("sha256"));

        let mut missing_rollback = valid;
        missing_rollback["rollback_runtime_id"] = Value::String(String::new());
        assert!(verify_runtime_download_manifest(&missing_rollback)
            .expect_err("rollback required")
            .contains("rollback"));
    }

    #[test]
    fn reset_pairing_clears_runner_profile_without_requiring_existing_file() {
        let _guard = env_test_lock().lock().expect("env test lock");
        let temp = env::temp_dir().join(format!("infergrade-reset-test-{}", std::process::id()));
        env::set_var("INFERGRADE_CONFIG_DIR", &temp);
        let first = clear_runner_profile().expect("missing profile is ok");
        assert_eq!(first["removed"], false);

        fs::create_dir_all(&temp).expect("config dir");
        fs::write(temp.join("runner_profile.json"), "{}\n").expect("profile");
        let second = clear_runner_profile().expect("profile removed");
        assert_eq!(second["removed"], true);
        assert!(!temp.join("runner_profile.json").exists());

        env::remove_var("INFERGRADE_CONFIG_DIR");
        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn pairing_status_reads_profile_without_exposing_token() {
        let profile = json!({
            "api_url": "https://api.infergrade.com/",
            "access_token": "qbhr_secret",
            "runner_id": "runner_123",
            "label": "Test runner",
            "preferred_execution_mode": "local_native",
        });
        let sanitized = sanitized_runner_profile(&profile);
        assert_eq!(sanitized["runner_id"], "runner_123");
        assert_eq!(sanitized["has_access_token"], true);
        assert_eq!(sanitized.get("access_token"), None);
    }

    #[test]
    fn pairing_response_does_not_return_runner_token_to_ui() {
        let profile = json!({
            "api_url": "https://api.infergrade.com/",
            "access_token": "qbhr_secret",
            "runner_id": "runner_123",
            "label": "Test runner",
        });
        let response = ui_pairing_response(
            json!({
                "runner_profile": profile.clone(),
                "other": "unchanged",
            }),
            &profile,
            PathBuf::from("/tmp/infergrade/runner_profile.json"),
        );

        assert_eq!(response["runner_profile"]["runner_id"], "runner_123");
        assert_eq!(response["runner_profile"]["has_access_token"], true);
        assert_eq!(response["other"], "unchanged");
        assert!(!response.to_string().contains("qbhr_secret"));
        assert_eq!(response["runner_profile"].get("access_token"), None);
    }

    #[test]
    fn desktop_profile_store_does_not_write_token_to_runner_profile_file() {
        let _guard = env_test_lock().lock().expect("env test lock");
        let temp = env::temp_dir().join(format!(
            "infergrade-profile-store-test-{}",
            std::process::id()
        ));
        env::set_var("INFERGRADE_CONFIG_DIR", &temp);
        let profile = RunnerProfile {
            api_url: "https://api.infergrade.com/".to_string(),
            access_token: Some("qbhr_secret".to_string()),
            runner_id: "runner_123".to_string(),
            label: Some("Test runner".to_string()),
            preferred_execution_mode: Some("local_native".to_string()),
            paired_at: None,
            expires_at: None,
            user: None,
        };

        DesktopProfileStore
            .save_profile(&profile)
            .expect("profile saved");
        let path = temp.join("runner_profile.json");
        let text = fs::read_to_string(&path).expect("profile text");
        assert!(!text.contains("qbhr_secret"));
        assert!(!text.contains("access_token"));

        env::remove_var("INFERGRADE_CONFIG_DIR");
        let _ = fs::remove_dir_all(temp);
    }

    #[test]
    fn pairing_status_requires_profile_and_os_token_to_be_ready() {
        let profile = RunnerProfile {
            api_url: "https://api.infergrade.com/".to_string(),
            access_token: None,
            runner_id: "runner_123".to_string(),
            label: Some("Test runner".to_string()),
            preferred_execution_mode: None,
            paired_at: None,
            expires_at: None,
            user: None,
        };
        let path = PathBuf::from("/tmp/infergrade/runner_profile.json");

        let stale_profile =
            pairing_status_payload(Some(profile.clone()), false, path.display().to_string())
                .expect("status");
        assert_eq!(stale_profile["paired"], false);
        assert_eq!(stale_profile["profile"]["status"], "present");
        assert_eq!(stale_profile["token"]["status"], "missing");

        let token_without_profile =
            pairing_status_payload(None, true, path.display().to_string()).expect("status");
        assert_eq!(token_without_profile["paired"], false);
        assert_eq!(token_without_profile["profile"]["status"], "missing");
        assert_eq!(token_without_profile["token"]["status"], "present");

        let ready = pairing_status_payload(Some(profile), true, path.display().to_string())
            .expect("status");
        assert_eq!(ready["paired"], true);
    }

    #[test]
    fn listener_start_plan_prefers_os_token_without_exposing_secret() {
        let profile = json!({
            "api_url": "https://api.infergrade.com/",
            "access_token": "qbhr_secret",
            "runner_id": "runner_123",
            "preferred_execution_mode": "local_native",
        });
        let plan = build_listener_start_plan("api.infergrade.com", false, Some(&profile), true)
            .expect("listener plan");

        assert_eq!(plan["api_url"], "https://api.infergrade.com/");
        assert_eq!(plan["runner_id"], "runner_123");
        assert_eq!(plan["execution_mode"], "local_native");
        assert_eq!(plan["credential_source"], "saved_pairing");
        assert_eq!(plan["can_start"], true);
        assert!(!plan.to_string().contains("qbhr_secret"));
    }

    #[test]
    fn listener_start_plan_rejects_stale_profile_without_os_token() {
        let profile = json!({
            "api_url": "https://api.infergrade.com/",
            "access_token": "qbhr_secret",
            "runner_id": "runner_123",
        });
        let stale = build_listener_start_plan("api.infergrade.com", false, Some(&profile), false)
            .expect("listener plan");
        assert_eq!(stale["credential_source"], "missing");
        assert_eq!(stale["can_start"], false);
        assert_eq!(stale["profile_token_status"], "present");
        assert_eq!(stale["token_status"], "missing");

        let typed = build_listener_start_plan("api.infergrade.com", true, None, false)
            .expect("typed token plan");
        assert_eq!(typed["credential_source"], "typed_input");
        assert_eq!(typed["can_start"], true);
    }

    #[test]
    fn listener_start_plan_allows_profile_without_embedded_token_when_os_token_exists() {
        let profile = json!({
            "api_url": "https://api.infergrade.com/",
            "runner_id": "runner_123",
        });
        let plan = build_listener_start_plan("api.infergrade.com", false, Some(&profile), true)
            .expect("listener plan");
        assert_eq!(plan["credential_source"], "saved_pairing");
        assert_eq!(plan["profile_token_status"], "missing");
        assert_eq!(plan["token_status"], "present");
        assert_eq!(plan["can_start"], true);
    }

    #[test]
    fn listener_output_redacts_child_env_token_before_browser_event() {
        let redacted = redact_listener_text(
            "starting with qbhr_secret_token in stderr",
            &[String::from("qbhr_secret_token")],
        );

        assert_eq!(redacted, "starting with [redacted] in stderr");
        assert!(!redacted.contains("qbhr_secret_token"));
    }

    #[test]
    fn rust_worker_protocol_payloads_match_python_bridge_contract_shape() {
        let register =
            runner_register_payload("runner_123", "local_native", Some("host-a".to_string()));
        assert_eq!(register["runner_id"], "runner_123");
        assert_eq!(register["execution_modes"][0], "local_native");
        assert_eq!(register["status"], "starting");
        assert_eq!(register["runner_kind"], "local_listener");
        assert_eq!(register["capabilities"]["run_token_supported"], true);
        assert_eq!(register["capabilities"]["auto_upload"], true);
        assert_eq!(register["environment"]["source"], "desktop_rust_supervisor");

        let heartbeat = runner_heartbeat_payload(
            "listening",
            None,
            Some("host-a".to_string()),
            Some("Runner is listening for jobs."),
        );
        assert_eq!(heartbeat["status"], "listening");
        assert_eq!(
            heartbeat["metadata"]["message"],
            "Runner is listening for jobs."
        );
        assert_eq!(heartbeat["current_run_id"], Value::Null);

        let claim = claim_run_job_payload(
            "runner_123",
            "local_native",
            Some("run_1"),
            None,
            Some("host-a".to_string()),
        );
        assert_eq!(claim["worker_id"], "runner_123");
        assert_eq!(claim["execution_mode"], "local_native");
        assert_eq!(claim["run_id"], "run_1");
        assert_eq!(claim["provider_id"], Value::Null);

        let combined = json!({
            "register": register,
            "heartbeat": heartbeat,
            "claim": claim,
        })
        .to_string();
        assert!(!combined.contains("qbhr_"));
        assert!(!combined.contains("Authorization"));
    }

    #[test]
    fn rust_worker_request_preview_keeps_token_out_of_payload() {
        let payload =
            runner_register_payload("runner_123", "local_native", Some("host-a".to_string()));
        let request = worker_request_preview(
            "api.infergrade.com",
            "/v1/runners/register",
            payload,
            "qbhr_secret_token",
        )
        .expect("request preview");

        assert_eq!(
            request["url"],
            "https://api.infergrade.com/v1/runners/register"
        );
        assert_eq!(request["method"], "POST");
        assert_eq!(request["has_authorization"], true);
        assert!(!request["payload"].to_string().contains("qbhr_secret_token"));
        assert!(!request.to_string().contains("Authorization"));
    }

    #[test]
    fn rust_worker_response_redacts_header_and_token_echoes() {
        let response = redact_worker_response(
            json!({
                "runner_id": "runner_123",
                "access_token": "qbhr_secret_token",
                "detail": "Authorization Bearer qbhr_secret_token failed",
                "capabilities": {
                    "run_token_supported": true
                }
            }),
            &[String::from("qbhr_secret_token")],
        );

        let combined = response.to_string();
        assert_eq!(response["access_token"], "[redacted]");
        assert_eq!(response["capabilities"]["run_token_supported"], true);
        assert!(!combined.contains("qbhr_secret_token"));
        assert!(!combined.contains("Authorization"));
    }
}
