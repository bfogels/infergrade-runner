//! Private local work has its own supervisor and never a Hub upload handoff.
use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

#[derive(Default)]
pub(crate) struct PrivateProcess {
    state: Mutex<Process>,
}
#[derive(Default)]
struct Process {
    child: Option<CommandChild>,
    work: Option<crate::background::WorkGuard>,
    snapshot: Value,
}
fn child_environment() -> Vec<(String, String)> {
    let mut names = vec![
        "PATH",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "TEMP",
        "TMP",
        "TMPDIR",
        "SystemRoot",
        "WINDIR",
        "LANG",
        "LC_ALL",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
    ];
    if cfg!(debug_assertions) {
        names.extend([
            "INFERGRADE_RUNNER_REPO",
            "INFERGRADE_BUNDLED_RUNNER_CORE",
            "INFERGRADE_BUNDLED_PYTHON_ROOT",
            "INFERGRADE_NATIVE_IFEVAL_BUNDLE",
        ]);
    }
    names
        .into_iter()
        .filter_map(|name| {
            std::env::var(name)
                .ok()
                .map(|value| (name.to_string(), value))
        })
        .collect()
}
fn valid_id(id: &str) -> bool {
    id.strip_prefix("private_").is_some_and(|value| {
        value.len() == 32
            && value
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}
fn fixed_report(root: &Path, id: &str) -> Result<PathBuf, String> {
    if !valid_id(id) {
        return Err("Invalid private benchmark identity.".into());
    }
    if std::fs::symlink_metadata(root)
        .map(|m| !m.is_dir() || m.file_type().is_symlink())
        .unwrap_or(true)
    {
        return Err("Private report storage is unavailable or linked.".into());
    }
    let mut path = root.to_path_buf();
    for name in ["private-runs", id, "bundle", "report.md"] {
        path.push(name);
        let meta = std::fs::symlink_metadata(&path).map_err(|_| "Local report is unavailable.")?;
        if meta.file_type().is_symlink() {
            return Err("Linked private reports are refused.".into());
        }
    }
    if !path.is_file() {
        return Err("Local report is unavailable.".into());
    }
    Ok(path)
}
fn start_arguments(
    model_path: &str,
    use_case: &str,
    tier: &str,
    selection: &Value,
) -> Result<Vec<String>, String> {
    if model_path.is_empty()
        || model_path.len() > 4096
        || model_path.chars().any(char::is_control)
        || !["general_assistant", "agentic_coding", "reasoning"].contains(&use_case)
        || !["canary", "standard"].contains(&tier)
    {
        return Err("Choose a local GGUF, an available use case and benchmark depth.".into());
    }
    let binaries = &selection["selection"]["binaries"];
    let mut args = vec![
        "benchmark-local".into(),
        "--model-file".into(),
        model_path.into(),
        "--use-case".into(),
        use_case.into(),
        "--tier".into(),
        tier.into(),
        "--json".into(),
    ];
    for (flag, role) in [
        ("--llama-cpp-cli-path", "cli"),
        ("--llama-cpp-server-path", "server"),
    ] {
        let path=binaries[role].as_str().filter(|v| !v.is_empty() && v.len()<=4096 && !v.chars().any(char::is_control)).ok_or("Install or select a llama.cpp runtime with both CLI and server before benchmarking privately.")?;
        if !Path::new(path).is_absolute() || !Path::new(path).is_file() {
            return Err(
                "The selected runtime needs repair. Install or select its CLI and server.".into(),
            );
        }
        args.extend([flag.into(), path.into()]);
    }
    Ok(args)
}
fn completed_receipt(value: &Value) -> bool {
    value["schema_version"] == "infergrade.private_benchmark.v1"
        && value["status"] == "completed"
        && value["uploaded"] == false
        && value["id"].as_str().is_some_and(valid_id)
}
#[tauri::command]
pub(crate) fn desktop_private_benchmark_status(
    state: State<'_, PrivateProcess>,
) -> Result<Value, String> {
    let state = state
        .state
        .lock()
        .map_err(|_| "Private benchmark state is unavailable.")?;
    Ok(if state.snapshot.is_null() {
        json!({"status":"idle","pid":null})
    } else {
        state.snapshot.clone()
    })
}
#[tauri::command]
pub(crate) fn start_desktop_private_benchmark(
    app: AppHandle,
    state: State<'_, PrivateProcess>,
    model_path: String,
    use_case: String,
    tier: String,
) -> Result<Value, String> {
    let work = crate::background::WorkGuard::begin_exclusive()?;
    let args = start_arguments(
        &model_path,
        &use_case,
        &tier,
        &infergrade_runner_engine::load_selected_llama_cpp_runtime(),
    )?;
    let mut process = state
        .state
        .lock()
        .map_err(|_| "Private benchmark state is unavailable.")?;
    if process.child.is_some() {
        return Err("Private benchmark cleanup is still supervised. Keep Runner open.".into());
    }
    let command = app
        .shell()
        .sidecar(crate::SIDECAR_BINARY_NAME)
        .map_err(|_| "Could not prepare private benchmark.")?
        .args(args)
        .env_clear()
        .envs(child_environment())
        .env("INFERGRADE_CONFIG_DIR", crate::runner_config_dir()?);
    let (mut events, child) = command
        .spawn()
        .map_err(|_| "Could not start private benchmark.")?;
    let pid = child.pid();
    process.child = Some(child);
    process.work = Some(work);
    process.snapshot =
        json!({"status":"running","pid":pid,"phase":"Verifying model and runtime","receipt":null});
    let snapshot = process.snapshot.clone();
    drop(process);
    tauri::async_runtime::spawn(async move {
        let mut stdout = Vec::new();
        let mut invalid_output = false;
        while let Some(event) = events.recv().await {
            let state = app.state::<PrivateProcess>();
            let Ok(mut process) = state.state.lock() else {
                return;
            };
            if process.child.as_ref().map(CommandChild::pid) != Some(pid) {
                return;
            }
            match event {
                CommandEvent::Stdout(bytes) => {
                    if stdout.len() + bytes.len() <= 32768 {
                        stdout.extend(bytes);
                    } else {
                        invalid_output = true;
                    }
                }
                CommandEvent::Stderr(bytes) => {
                    // Only Runner's fixed phase/count lines are displayed. No
                    // evaluator text, local paths or arbitrary errors cross here.
                    let text = String::from_utf8_lossy(&bytes);
                    for line in text.lines() {
                        if let Some(phase) = progress_phase(line) {
                            process.snapshot["phase"] = json!(phase);
                        }
                    }
                }
                CommandEvent::Terminated(payload) => {
                    let receipt = serde_json::from_slice::<Value>(&stdout)
                        .ok()
                        .filter(completed_receipt);
                    let complete = payload.code == Some(0) && !invalid_output && receipt.is_some();
                    process.snapshot = json!({"status":if complete{"completed"}else{"failed"},"pid":pid,"phase":if complete{"Finished · private"}else{"Did not finish. Refresh private history for the local report."},"receipt":receipt.filter(|_|complete)});
                    process.child = None;
                    process.work = None;
                    return;
                }
                CommandEvent::Error(_) => {
                    process.snapshot["phase"] =
                        json!("Process state is unconfirmed. Keep Runner open and try Stop.");
                }
                _ => {}
            }
        }
        // An event-channel close is not a process cleanup receipt. Retain the
        // child and lifecycle/cache guards, including after a failed Stop.
        if let Ok(mut process) = app.state::<PrivateProcess>().state.lock() {
            process.snapshot["phase"] =
                json!("Process cleanup is unconfirmed. Keep Runner open and try Stop.");
        }
    });
    Ok(snapshot)
}
fn progress_phase(line: &str) -> Option<String> {
    let line = line.trim();
    if [
        "Capturing environment...",
        "Resolving model artifact...",
        "Resolving backend runtime...",
        "Checking model/runtime compatibility...",
        "Running capability suite...",
        "Writing bundle artifacts...",
    ]
    .contains(&line)
    {
        return Some(line.to_string());
    }
    if line.len() <= 180
        && line.starts_with("Capability benchmark ")
        && line.ends_with(" cases.")
        && line
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b" /()._-".contains(&b))
    {
        return Some(line.to_string());
    }
    if line.len() <= 180
        && line.starts_with("Deployment profile interactive_chat_v1 ")
        && line
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b" /()._-".contains(&b))
    {
        return Some(line.to_string());
    }
    None
}
#[tauri::command]
pub(crate) fn stop_desktop_private_benchmark(
    state: State<'_, PrivateProcess>,
    expected_pid: u32,
) -> Result<Value, String> {
    let process = state
        .state
        .lock()
        .map_err(|_| "Private benchmark state is unavailable.")?;
    let Some(child) = process.child.as_ref() else {
        return Ok(json!({"status":"not_running"}));
    };
    if child.pid() != expected_pid {
        return Err("The private benchmark changed. No other process was stopped.".into());
    }
    #[cfg(unix)]
    if unsafe { libc::kill(expected_pid as libc::pid_t, libc::SIGINT) } != 0 {
        return Err("Could not request interruption. Keep Runner open.".into());
    }
    #[cfg(windows)]
    {
        let status = std::process::Command::new("taskkill")
            .args(["/PID", &expected_pid.to_string(), "/T", "/F"])
            .status()
            .map_err(|_| "Could not request interruption. Keep Runner open.")?;
        if !status.success() {
            return Err("Could not request interruption. Keep Runner open.".into());
        }
    }
    Ok(json!({"status":"stop_requested","pid":expected_pid}))
}
async fn history(app: &AppHandle) -> Result<Value, String> {
    let guard = crate::background::WorkGuard::begin()?;
    let (mut events, child) = app
        .shell()
        .sidecar(crate::SIDECAR_BINARY_NAME)
        .map_err(|_| "Could not prepare private history.")?
        .args(["private-history", "--json"])
        .env_clear()
        .envs(child_environment())
        .env("INFERGRADE_CONFIG_DIR", crate::runner_config_dir()?)
        .spawn()
        .map_err(|_| "Could not start private history.")?;
    let mut terminated = false;
    let result = tokio::time::timeout(std::time::Duration::from_secs(30), async {
        let mut stdout = Vec::new();
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    if stdout.len() + bytes.len() > 512 * 1024 {
                        return Err("Private history exceeded its output bound.".to_string());
                    }
                    stdout.extend(bytes);
                }
                CommandEvent::Terminated(payload) => {
                    terminated = true;
                    if payload.code != Some(0) {
                        return Err(
                            "Private history unavailable. Check local storage permissions.".into(),
                        );
                    }
                    return serde_json::from_slice::<Value>(&stdout)
                        .map_err(|_| "Private history returned invalid metadata.".into());
                }
                CommandEvent::Error(_) => {
                    return Err(
                        "Private history failed before process cleanup was confirmed.".into(),
                    )
                }
                _ => {}
            }
        }
        Err("Private history process cleanup is unconfirmed.".into())
    })
    .await;
    let value = match result {
        Ok(Ok(value)) => value,
        other => {
            let error = match other {
                Ok(Err(error)) => error,
                _ => "Private history timed out.".to_string(),
            };
            if !terminated {
                let failed = child.kill().is_err();
                tauri::async_runtime::spawn(crate::hold_admission_until_terminated(events, guard));
                if failed {
                    return Err("Could not stop private history. Keep Runner open while cleanup is supervised.".into());
                }
            }
            return Err(error);
        }
    };
    if value["schema_version"] != "infergrade.private_history.v1" || !value["results"].is_array() {
        return Err("Private history returned invalid metadata.".into());
    }
    Ok(value)
}
#[tauri::command]
pub(crate) async fn desktop_private_benchmark_history(app: AppHandle) -> Result<Value, String> {
    history(&app).await
}
#[tauri::command]
pub(crate) async fn open_desktop_private_report(
    app: AppHandle,
    id: String,
) -> Result<Value, String> {
    let value = history(&app).await?;
    if !value["results"].as_array().is_some_and(|rows| {
        rows.iter()
            .any(|row| row["id"] == id && row["report_available"] == true)
    }) {
        return Err("Local report is unavailable. Refresh private history.".into());
    }
    let path = fixed_report(&crate::runner_config_dir()?, &id)?;
    tauri::async_runtime::spawn_blocking(move || {
        open::that(path).map_err(|_| "Could not open the local report.".to_string())
    })
    .await
    .map_err(|_| "Local report opening task failed.")??;
    Ok(json!({"opened":true}))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn report_paths_are_fixed_and_linked_reports_are_refused() {
        let root = std::env::temp_dir().join(format!(
            "infergrade-private-report-test-{}",
            std::process::id()
        ));
        let id = "private_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
        let directory = root.join("private-runs").join(id).join("bundle");
        std::fs::create_dir_all(&directory).expect("test report directory");
        let report = directory.join("report.md");
        std::fs::write(&report, "local test report").expect("test report");
        assert_eq!(fixed_report(&root, id).expect("contained report"), report);
        assert!(fixed_report(&root, "../outside").is_err());
        #[cfg(unix)]
        {
            std::fs::remove_file(&report).expect("replace own test report");
            std::os::unix::fs::symlink("/etc/passwd", &report).expect("test linked report");
            assert!(fixed_report(&root, id).is_err());
        }
        std::fs::remove_dir_all(root).expect("remove own test directory");
    }
    #[test]
    fn generic_progress_never_forwards_arbitrary_private_text() {
        assert_eq!(
            progress_phase("Capability benchmark IFEval 2/25 cases."),
            Some("Capability benchmark IFEval 2/25 cases.".into())
        );
        assert!(progress_phase("Private /Users/name/model prompt secret").is_none());
        assert!(progress_phase("Capability benchmark <script> cases.").is_none());
    }
    #[test]
    fn completion_requires_local_closed_state() {
        assert!(completed_receipt(
            &json!({"schema_version":"infergrade.private_benchmark.v1","status":"completed","uploaded":false,"id":"private_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
        ));
        assert!(!completed_receipt(
            &json!({"schema_version":"infergrade.private_benchmark.v1","status":"completed","uploaded":true,"id":"private_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"})
        ));
        assert!(!valid_id("../outside"));
    }
    #[test]
    fn private_environment_excludes_credentials_and_proxy_injection() {
        for (name, _) in child_environment() {
            assert!(!name.contains("TOKEN"));
            assert!(!name.contains("PROXY"));
            assert!(!name.contains("API"));
            assert_ne!(name, "PYTHONPATH");
        }
    }
}
