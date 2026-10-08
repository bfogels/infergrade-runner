//! Local-only GPU preference controls. Hardware UUIDs never enter a Hub request.
use serde_json::{json, Value};
use std::sync::atomic::{AtomicBool, Ordering};
use tauri::AppHandle;
use tauri_plugin_shell::{process::CommandEvent, ShellExt};

static BUSY: AtomicBool = AtomicBool::new(false);
struct Guard {
    _work: crate::background::WorkGuard,
}
impl Guard {
    fn begin() -> Result<Self, String> {
        let work = crate::background::WorkGuard::begin()?;
        BUSY.compare_exchange(false, true, Ordering::SeqCst, Ordering::SeqCst)
            .map_err(|_| {
                "GPU confirmation is still being supervised. Wait before refreshing.".to_string()
            })?;
        Ok(Self { _work: work })
    }
}
impl Drop for Guard {
    fn drop(&mut self) {
        BUSY.store(false, Ordering::SeqCst);
    }
}
fn valid_uuid(value: &str) -> bool {
    let Some(value) = value.strip_prefix("GPU-") else {
        return false;
    };
    value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| {
            if [8, 13, 18, 23].contains(&index) {
                byte == b'-'
            } else {
                byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)
            }
        })
}
fn digest(value: &Value) -> bool {
    value.as_str().is_some_and(|v| {
        v.len() == 64
            && v.bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    })
}
fn label(value: &Value) -> bool {
    value.as_str().is_some_and(|v| {
        !v.is_empty()
            && v.chars().count() <= 256
            && v.trim() == v
            && !v.chars().any(|c| c.is_control())
    })
}
fn memory(value: &Value) -> bool {
    value
        .as_f64()
        .is_some_and(|v| v.is_finite() && v > 0.0 && v <= 4096.0)
}
fn fields(value: &Value, expected: &[&str]) -> bool {
    value.as_object().is_some_and(|o| {
        o.len() == expected.len() && expected.iter().all(|key| o.contains_key(*key))
    })
}
fn projection(value: Value) -> Result<Value, String> {
    let fail = || "GPU controls returned invalid state.".to_string();
    let mut keys = vec![
        "schema_version",
        "policy",
        "available",
        "selection_ready",
        "devices",
    ];
    if value.get("message").is_some() {
        keys.push("message");
    }
    if !fields(&value, &keys)
        || value["schema_version"] != "infergrade.cuda_device_policy.v1"
        || !value["available"].is_boolean()
        || !value["selection_ready"].is_boolean()
    {
        return Err(fail());
    }
    if !value["policy"].is_null() {
        let policy = &value["policy"];
        let devices = policy["devices"].as_array().ok_or_else(fail)?;
        if !fields(
            policy,
            &[
                "schema_version",
                "revision",
                "selection_fingerprint",
                "device_count",
                "devices",
            ],
        ) || policy["schema_version"] != "infergrade.cuda_device_policy.v1"
            || !digest(&policy["revision"])
            || !digest(&policy["selection_fingerprint"])
            || devices.is_empty()
            || devices.len() > 16
            || policy["device_count"].as_u64() != Some(devices.len() as u64)
            || devices.iter().any(|d| {
                !fields(d, &["model", "vram_gb"]) || !label(&d["model"]) || !memory(&d["vram_gb"])
            })
        {
            return Err(fail());
        }
    }
    let devices = value["devices"].as_array().ok_or_else(fail)?;
    if devices.len() > 16 || (value["available"] == false && !devices.is_empty()) {
        return Err(fail());
    }
    let mut uuids = std::collections::HashSet::new();
    let mut indices = std::collections::HashSet::new();
    for device in devices {
        if !fields(device, &["uuid", "index", "model", "vram_gb", "selected"])
            || !device["uuid"].as_str().is_some_and(valid_uuid)
            || device["index"].as_u64().is_none_or(|n| n > 999)
            || !label(&device["model"])
            || !memory(&device["vram_gb"])
            || !device["selected"].is_boolean()
            || !uuids.insert(device["uuid"].as_str().unwrap())
            || !indices.insert(device["index"].as_u64().unwrap())
        {
            return Err(fail());
        }
    }
    // Never forward arbitrary helper diagnostic text into the webview.
    let message = if value["available"] == false {
        Some("Physical NVIDIA device inventory is unavailable.")
    } else if value["selection_ready"] == false {
        Some("Selected GPU hardware changed or is unavailable. Select the devices again; no fallback is allowed.")
    } else {
        None
    };
    Ok(
        json!({"schema_version":"infergrade.cuda_device_policy.v1", "policy":value["policy"],
        "available":value["available"], "selection_ready":value["selection_ready"], "devices":devices, "message":message}),
    )
}
fn arguments(uuids: Option<Vec<String>>) -> Result<Vec<String>, String> {
    let mut args = vec!["gpu-choice".into()];
    match uuids {
        None => args.push("status".into()),
        Some(values) if values.is_empty() => args.push("reset".into()),
        Some(values) => {
            let unique: std::collections::HashSet<_> = values.iter().collect();
            if values.len() > 16
                || unique.len() != values.len()
                || values.iter().any(|v| !valid_uuid(v))
            {
                return Err("Select distinct devices from this machine's inventory.".into());
            }
            args.push("select".into());
            for value in values {
                args.extend(["--cuda-device".into(), value]);
            }
        }
    }
    args.push("--json".into());
    Ok(args)
}
async fn action(app: &AppHandle, args: Vec<String>) -> Result<Value, String> {
    let guard = Guard::begin()?;
    let mut command = app
        .shell()
        .sidecar(crate::SIDECAR_BINARY_NAME)
        .map_err(|_| "Could not prepare GPU controls.")?
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
        .env("INFERGRADE_CONFIG_DIR", crate::runner_config_dir()?)
        .spawn()
        .map_err(|_| "Could not start GPU controls.")?;
    let mut terminated = false;
    let result = tokio::time::timeout(std::time::Duration::from_secs(45), async {
        let mut output = Vec::new();
        while let Some(event) = events.recv().await {
            match event {
                CommandEvent::Stdout(bytes) => {
                    if output.len() + bytes.len() > 65536 {
                        return Err("GPU controls returned too much output.".to_string());
                    }
                    output.extend(bytes);
                }
                CommandEvent::Terminated(payload) => {
                    terminated = true;
                    if payload.code != Some(0) {
                        return Err(
                            "Could not confirm GPU choice. Refresh or reset the saved preference."
                                .into(),
                        );
                    }
                    return projection(
                        serde_json::from_slice(&output)
                            .map_err(|_| "GPU controls returned invalid state.")?,
                    );
                }
                CommandEvent::Error(_) => return Err("GPU controls could not finish.".into()),
                _ => {}
            }
        }
        Err("GPU controls ended without confirmation.".into())
    })
    .await;
    match result {
        Ok(Ok(value)) => Ok(value),
        other => {
            let error = match other {
                Ok(Err(error)) => error,
                _ => "GPU confirmation timed out. Refresh its saved state before trying again."
                    .into(),
            };
            if terminated {
                return Err(error);
            }
            let kill_failed = child.kill().is_err();
            tauri::async_runtime::spawn(crate::hold_admission_until_terminated(events, guard));
            if kill_failed {
                Err("Could not stop GPU confirmation. Runner remains open while cleanup is supervised.".into())
            } else {
                Err(error)
            }
        }
    }
}
#[tauri::command]
pub(crate) async fn desktop_gpu_status(app: AppHandle) -> Result<Value, String> {
    action(&app, arguments(None)?).await
}
#[tauri::command]
pub(crate) async fn set_desktop_gpu_choice(
    app: AppHandle,
    uuids: Vec<String>,
) -> Result<Value, String> {
    action(&app, arguments(Some(uuids))?).await
}

#[cfg(test)]
mod tests {
    use super::*;
    const UUID: &str = "GPU-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
    fn status() -> Value {
        json!({"schema_version":"infergrade.cuda_device_policy.v1", "policy":null, "available":true, "selection_ready":true,
        "devices":[{"uuid":UUID,"index":2,"model":"Card","vram_gb":24,"selected":false}]})
    }
    #[test]
    fn arguments_are_fixed_and_uuid_only() {
        assert_eq!(
            arguments(None).unwrap(),
            vec!["gpu-choice", "status", "--json"]
        );
        assert_eq!(
            arguments(Some(vec![])).unwrap(),
            vec!["gpu-choice", "reset", "--json"]
        );
        assert_eq!(
            arguments(Some(vec![UUID.into()])).unwrap(),
            vec!["gpu-choice", "select", "--cuda-device", UUID, "--json"]
        );
        for values in [
            vec![UUID.into(), UUID.into()],
            vec!["--help".into()],
            vec!["GPU-short".into()],
        ] {
            assert!(arguments(Some(values)).is_err());
        }
    }
    #[test]
    fn saved_policy_projection_preserves_only_closed_summary() {
        let mut value = status();
        value["policy"] = json!({"schema_version":"infergrade.cuda_device_policy.v1", "revision":"a".repeat(64),
            "selection_fingerprint":"b".repeat(64), "device_count":1, "devices":[{"model":"Card","vram_gb":24}]});
        value["devices"][0]["selected"] = json!(true);
        assert_eq!(
            projection(value.clone()).unwrap()["policy"],
            value["policy"]
        );
        value["policy"]["devices"][0]["uuid"] = json!(UUID);
        assert!(projection(value).is_err());
    }
    #[test]
    fn projection_is_closed_and_diagnostics_are_fixed() {
        let mut value = status();
        value["message"] = json!("secret path");
        assert_eq!(projection(value).unwrap()["message"], Value::Null);
        for (key, bad) in [
            ("available", json!("true")),
            ("policy", json!({})),
            ("devices", json!([])),
            ("selection_ready", json!(null)),
        ] {
            let mut value = status();
            value[key] = bad;
            if key != "devices" {
                assert!(projection(value).is_err());
            }
        }
        let mut value = status();
        value["devices"][0]["uuid"] = json!("private-path");
        assert!(projection(value).is_err());
        let mut value = status();
        value["devices"][0]["model"] = json!("Card\u{85}");
        assert!(projection(value).is_err());
        let mut value = status();
        value["secret"] = json!("token");
        assert!(projection(value).is_err());
        let mut value = status();
        value["selection_ready"] = json!(false);
        assert!(projection(value).unwrap()["message"]
            .as_str()
            .unwrap()
            .contains("no fallback"));
    }
}
