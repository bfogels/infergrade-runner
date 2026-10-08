//! Fixed local storage controls; no renderer paths or command arguments.
use serde_json::Value;
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::AppHandle;
use tauri_plugin_shell::{process::CommandEvent, ShellExt};
static BUSY: AtomicBool = AtomicBool::new(false);
struct Guard {
    _work: Option<crate::background::WorkGuard>,
    _maintenance: Option<crate::background::MaintenanceGuard>,
}
impl Guard {
    fn begin(trim: bool) -> Result<Self, String> {
        let work = if trim {
            None
        } else {
            Some(crate::background::WorkGuard::begin()?)
        };
        let maintenance = if trim {
            Some(crate::background::MaintenanceGuard::begin()?)
        } else {
            None
        };
        BUSY.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .map_err(|_| {
                "Storage confirmation is still being supervised. Wait before refreshing."
                    .to_string()
            })?;
        Ok(Self {
            _work: work,
            _maintenance: maintenance,
        })
    }
}
impl Drop for Guard {
    fn drop(&mut self) {
        BUSY.store(false, Ordering::SeqCst);
    }
}
fn arguments(limit: Option<Option<u64>>, trim: bool) -> Result<Vec<String>, String> {
    if trim && limit.is_none() {
        return Err("Choose a limit before trimming downloads.".into());
    }
    let mut args = vec![
        "cache".into(),
        "--budget-status".into(),
        "--json".into(),
        "--artifact-cache-dir".into(),
        crate::desktop_artifact_cache_dir()
            .map_err(|_| "Storage controls are unavailable.")?
            .to_string_lossy()
            .into_owned(),
    ];
    if let Some(limit) = limit {
        if limit.is_some_and(|v| ![25, 50, 100, 200].contains(&v)) {
            return Err("Invalid download limit.".into());
        }
        args.extend([
            "--limit-gb".into(),
            limit.map(|v| v.to_string()).unwrap_or("none".into()),
        ]);
    }
    if trim {
        args.push("--trim-oldest".into());
    }
    Ok(args)
}
fn projection(value: Value) -> Result<Value, String> {
    let keys = [
        "schema_version",
        "limit_gb",
        "limit_bytes",
        "managed_bytes",
        "kept_bytes",
        "reserved_bytes",
        "producer_active",
        "disk_free_bytes",
        "disk_total_bytes",
    ];
    let fail = || "Storage controls returned invalid state.".to_string();
    if !value
        .as_object()
        .is_some_and(|o| o.len() == keys.len() && keys.iter().all(|k| o.contains_key(*k)))
        || value["schema_version"] != "infergrade.cache_budget.v1"
        || !value["producer_active"].is_boolean()
    {
        return Err(fail());
    }
    for key in [
        "managed_bytes",
        "kept_bytes",
        "reserved_bytes",
        "disk_free_bytes",
        "disk_total_bytes",
    ] {
        if value[key]
            .as_u64()
            .is_none_or(|v| v > 9_007_199_254_740_991)
        {
            return Err(fail());
        }
    }
    if value["kept_bytes"].as_u64() > value["managed_bytes"].as_u64()
        || value["disk_free_bytes"].as_u64() > value["disk_total_bytes"].as_u64()
        || (value["producer_active"] == false && value["reserved_bytes"] != 0)
    {
        return Err(fail());
    }
    if value["limit_gb"].is_null() {
        if !value["limit_bytes"].is_null() {
            return Err(fail());
        }
    } else {
        let limit = value["limit_gb"]
            .as_u64()
            .filter(|v| [25, 50, 100, 200].contains(v))
            .ok_or_else(fail)?;
        if value["limit_bytes"].as_u64() != Some(limit * 1024 * 1024 * 1024) {
            return Err(fail());
        }
    }
    Ok(value)
}
async fn action(app: &AppHandle, args: Vec<String>, trim: bool) -> Result<Value, String> {
    let guard = Guard::begin(trim)?;
    let mut command = app
        .shell()
        .sidecar(crate::SIDECAR_BINARY_NAME)
        .map_err(|_| "Could not prepare Storage controls.")?
        .args(args)
        .env_clear();
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
    for name in names {
        if let Ok(value) = std::env::var(name) {
            command = command.env(name, value);
        }
    }
    let (mut events, child) = command
        .env(
            "INFERGRADE_CONFIG_DIR",
            crate::runner_config_dir().map_err(|_| "Storage controls are unavailable.")?,
        )
        .spawn()
        .map_err(|_| "Could not start Storage controls.")?;
    let mut terminated = false;
    let result = tokio::time::timeout(std::time::Duration::from_secs(45), async {
        let mut output = Vec::new();
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    if output.len() + bytes.len() > 65536 {
                        return Err("Storage controls returned too much output.".to_string());
                    }
                    output.extend(bytes);
                }
                CommandEvent::Terminated(payload) => {
                    terminated = true;
                    if payload.code != Some(0) {
                        return Err(
                            "Could not confirm the download limit. Refresh storage; stop listening and finish active work before trimming."
                                .into(),
                        );
                    }
                    return projection(
                        serde_json::from_slice(&output)
                            .map_err(|_| "Storage controls returned invalid state.")?,
                    );
                }
                CommandEvent::Error(_) => return Err("Storage controls could not finish.".into()),
                _ => {}
            }
        }
        Err("Storage controls ended without confirmation.".into())
    })
    .await;
    match result {
        Ok(Ok(value)) => Ok(value),
        other => {
            let error = match other {
                Ok(Err(error)) => error,
                _ => "Storage confirmation timed out. Refresh its saved state before trying again."
                    .into(),
            };
            if terminated {
                return Err(error);
            }
            let kill_failed = child.kill().is_err();
            tauri::async_runtime::spawn(crate::hold_admission_until_terminated(events, guard));
            if kill_failed {
                Err("Could not stop storage confirmation. Runner remains open while cleanup is supervised.".into())
            } else {
                Err(error)
            }
        }
    }
}
#[tauri::command]
pub(crate) async fn desktop_storage_status(app: AppHandle) -> Result<Value, String> {
    action(&app, arguments(None, false)?, false).await
}
#[tauri::command]
pub(crate) async fn set_desktop_download_limit(
    app: AppHandle,
    limit_gb: Option<u64>,
    trim_oldest: bool,
) -> Result<Value, String> {
    action(&app, arguments(Some(limit_gb), trim_oldest)?, trim_oldest).await
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    fn state() -> Value {
        json!({"schema_version":"infergrade.cache_budget.v1","limit_gb":25,"limit_bytes":26843545600_u64,"managed_bytes":10,"kept_bytes":5,"reserved_bytes":0,"producer_active":false,"disk_free_bytes":100,"disk_total_bytes":200})
    }
    #[test]
    fn closed_storage_projection_refuses_unknown_or_inconsistent_values() {
        assert!(projection(state()).is_ok());
        for (key, value) in [
            ("limit_gb", json!(true)),
            ("limit_bytes", json!(25)),
            ("kept_bytes", json!(11)),
            ("reserved_bytes", json!(1)),
            ("disk_free_bytes", json!(201)),
            ("managed_bytes", json!(-1)),
            ("extra", json!("private/path")),
        ] {
            let mut bad = state();
            bad[key] = value;
            assert!(projection(bad).is_err(), "{key}");
        }
        let mut unlimited = state();
        unlimited["limit_gb"] = Value::Null;
        unlimited["limit_bytes"] = Value::Null;
        assert!(projection(unlimited).is_ok());
        let mut live = state();
        live["producer_active"] = json!(true);
        live["reserved_bytes"] = json!(30);
        assert!(projection(live).is_ok());
    }
}
