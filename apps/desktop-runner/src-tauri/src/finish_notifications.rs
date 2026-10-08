//! Generic completion notices, only after Hub verifies this exact paired assignment.
use infergrade_runner_engine::{
    normalize_api_url, profile_string, runner_id_from_profile, validate_hub_path_id,
};
use serde_json::{json, Value};
use std::{
    collections::VecDeque,
    fs,
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::Mutex,
};
static OPERATION: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
static SENT: Mutex<VecDeque<String>> = Mutex::new(VecDeque::new());
const SCHEMA: &str = "infergrade.desktop_notifications.v1";
const TITLE: &str = "InferGrade benchmark finished";
const BODY: &str =
    "Your benchmark finished and uploaded. Open Runner to view the accepted results.";
fn preference_path() -> Result<PathBuf, String> {
    Ok(super::runner_config_dir()?.join("desktop-notifications.json"))
}
fn read_preference(path: &Path) -> Result<bool, String> {
    let mut options = fs::OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.custom_flags(0x00200000);
    }
    let file = match options.open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Err(_) => return Err("Cannot read the notification preference".into()),
    };
    let metadata = file
        .metadata()
        .map_err(|_| "Cannot inspect the notification preference")?;
    if !metadata.is_file()
        || metadata.len() > 4096
        || fs::symlink_metadata(path)
            .map_err(|_| "Cannot inspect the notification preference")?
            .file_type()
            .is_symlink()
    {
        return Err("The notification preference is not a supported regular file".into());
    }
    let mut bytes = Vec::new();
    file.take(4097)
        .read_to_end(&mut bytes)
        .map_err(|_| "Cannot read the notification preference")?;
    if bytes.len() > 4096 {
        return Err("The notification preference is too large".into());
    }
    let value: Value =
        serde_json::from_slice(&bytes).map_err(|_| "The notification preference is invalid")?;
    if value["schema_version"] != SCHEMA || value.as_object().is_none_or(|v| v.len() != 2) {
        return Err("The notification preference is invalid".into());
    }
    value["enabled"]
        .as_bool()
        .ok_or("The notification preference is invalid".into())
}
fn write_preference(path: &Path, enabled: bool) -> Result<(), String> {
    // A corrupt regular preference can be explicitly repaired, but links/non-files cannot.
    if let Ok(metadata) = fs::symlink_metadata(path) {
        if !metadata.is_file() || metadata.file_type().is_symlink() {
            return Err("Cannot safely replace the notification preference".into());
        }
    }
    let parent = path.parent().ok_or("Missing preference directory")?;
    fs::create_dir_all(parent).map_err(|_| "Cannot create the preference directory")?;
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| "Clock is unavailable")?
        .as_nanos();
    let temporary = parent.join(format!(".notifications-{}-{nonce}", std::process::id()));
    let result = (|| -> Result<(), String> {
        let mut options = fs::OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options
            .open(&temporary)
            .map_err(|_| "Cannot save the notification preference")?;
        file.write_all(
            json!({"schema_version":SCHEMA,"enabled":enabled})
                .to_string()
                .as_bytes(),
        )
        .and_then(|_| file.sync_all())
        .map_err(|_| "Cannot save the notification preference")?;
        drop(file);
        fs::rename(&temporary, path).map_err(|_| "Cannot replace the notification preference")?;
        #[cfg(unix)]
        fs::File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|_| "Cannot sync the notification preference")?;
        Ok(())
    })();
    let _ = fs::remove_file(temporary);
    result
}
fn installed_release() -> bool {
    !cfg!(debug_assertions)
}
fn state(enabled: bool) -> Value {
    json!({"schema_version":SCHEMA,"enabled":enabled,"available":installed_release(),"warning":if installed_release(){Value::Null}else{json!("Finish notifications are available in the installed release app.")}})
}
#[tauri::command]
pub(crate) async fn desktop_notification_status() -> Result<Value, String> {
    let _operation = OPERATION.lock().await;
    Ok(state(read_preference(&preference_path()?)?))
}
#[tauri::command]
pub(crate) async fn set_desktop_notifications(enabled: bool) -> Result<Value, String> {
    let _work = super::background::WorkGuard::begin()?;
    let _operation = OPERATION.lock().await;
    if enabled && !installed_release() {
        return Err("Finish notifications are available in the installed release app.".into());
    }
    let path = preference_path()?;
    write_preference(&path, enabled)?;
    Ok(state(read_preference(&path)?))
}
async fn connection() -> Result<(String, String, String), String> {
    let _guard = super::PAIRING_STATE_LOCK.read().await;
    connection_unlocked()
}
fn connection_unlocked() -> Result<(String, String, String), String> {
    let profile =
        super::load_runner_profile()?.ok_or("Connect Runner before using finish notifications")?;
    let api = normalize_api_url(
        &profile_string(Some(&profile), "api_url").ok_or("Pairing is missing the Hub URL")?,
    )?;
    let runner = runner_id_from_profile(Some(&profile));
    let token = super::load_runner_token_value()?
        .ok_or("Connect Runner before using finish notifications")?;
    Ok((api, runner, token))
}
fn accepted_result(value: &Value, run: &str, api: &str) -> bool {
    value["run_id"].as_str() == Some(run)
        && value["api_url"].as_str() == Some(api)
        && value["results"]
            .as_array()
            .is_some_and(|rows| !rows.is_empty())
}
fn submit_once(
    history: &mut VecDeque<String>,
    key: String,
    send: impl FnOnce() -> Result<(), String>,
) -> Result<bool, String> {
    if history.contains(&key) {
        return Ok(false);
    }
    send()?;
    if history.len() >= 1024 {
        history.pop_front();
    }
    history.push_back(key);
    Ok(true)
}
fn send_os_notice() -> Result<(), String> {
    #[cfg(target_os = "macos")]
    {
        static APPLICATION: std::sync::OnceLock<Result<(), String>> = std::sync::OnceLock::new();
        APPLICATION
            .get_or_init(|| {
                mac_notification_sys::set_application("com.infergrade.runner").map_err(|_| {
                    "Cannot identify the installed Runner for notifications".to_string()
                })
            })
            .clone()?;
        // Submit explicitly: notify-rust's NSUser handle Drop discards backend errors.
        mac_notification_sys::send_notification(TITLE, None, BODY, None)
            .map(|_| ())
            .map_err(|_| {
                "Could not submit the OS notification. Check your system notification settings."
                    .into()
            })
    }
    #[cfg(any(target_os = "linux", windows))]
    {
        let mut notice = notify_rust::Notification::new();
        notice.summary(TITLE).body(BODY);
        #[cfg(windows)]
        notice.app_id("com.infergrade.runner");
        #[cfg(target_os = "linux")]
        notice.appname("InferGrade Runner");
        notice.show().map(|_| ()).map_err(|_| {
            "Could not submit the OS notification. Check your system notification settings.".into()
        })
    }
}
#[tauri::command]
pub(crate) async fn notify_desktop_run_completed(run_id: String) -> Result<Value, String> {
    validate_hub_path_id(&run_id, "run_id").map_err(|_| "Invalid Hub job identity")?;
    let work = super::background::WorkGuard::begin()?;
    let _operation = OPERATION.lock().await;
    if !installed_release() || !read_preference(&preference_path()?)? {
        return Ok(json!({"submitted":false}));
    }
    let snapshot = connection().await?;
    let key = format!("{}\n{}\n{run_id}", snapshot.0, snapshot.1);
    if SENT
        .lock()
        .map_err(|_| "Notification history is unavailable")?
        .contains(&key)
    {
        return Ok(json!({"submitted":false}));
    }
    let accepted =
        super::run_results::desktop_run_results_expected(run_id.clone(), Some(snapshot.clone()))
            .await?;
    if !accepted_result(&accepted, &run_id, &snapshot.0) {
        return Err("No accepted uploaded result is available for this benchmark".into());
    }
    let _pairing = super::PAIRING_STATE_LOCK.read().await;
    if connection_unlocked()? != snapshot {
        return Err("Runner connection changed before notification".into());
    }
    // Keep both lifecycle and pairing fences until the OS submission completes.
    let submitted = tauri::async_runtime::spawn_blocking(move || {
        let _work = work;
        let mut sent = SENT
            .lock()
            .map_err(|_| "Notification history is unavailable")?;
        submit_once(&mut sent, key, send_os_notice)
    })
    .await
    .map_err(|_| "Notification submission did not finish")??;
    Ok(json!({"submitted":submitted}))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn distinct_runs_submit_once_and_backend_failure_is_not_acknowledged() {
        let mut sent = VecDeque::new();
        let mut calls = 0;
        assert!(submit_once(&mut sent, "run_one".into(), || {
            calls += 1;
            Ok(())
        })
        .unwrap());
        assert!(!submit_once(&mut sent, "run_one".into(), || {
            calls += 1;
            Ok(())
        })
        .unwrap());
        assert!(submit_once(&mut sent, "run_two".into(), || {
            calls += 1;
            Ok(())
        })
        .unwrap());
        assert!(submit_once(&mut sent, "run_three".into(), || Err("OS refused".into())).is_err());
        assert!(!sent.contains(&"run_three".to_string()));
        assert_eq!(calls, 2);
    }
    #[test]
    fn preference_defaults_off_and_rejects_malformed_state() {
        let root = std::env::temp_dir().join(format!(
            "infergrade-notifications-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        let path = root.join("prefs.json");
        assert!(!read_preference(&path).unwrap());
        assert!(!path.exists());
        write_preference(&path, true).unwrap();
        assert!(read_preference(&path).unwrap());
        fs::write(&path, b"{}").unwrap();
        assert!(read_preference(&path).is_err());
        write_preference(&path, false).unwrap();
        assert!(!read_preference(&path).unwrap());
        #[cfg(unix)]
        {
            fs::remove_file(&path).unwrap();
            std::os::unix::fs::symlink(root.join("missing"), &path).unwrap();
            assert!(read_preference(&path).is_err());
            assert!(write_preference(&path, true).is_err());
        }
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn accepted_notice_requires_exact_run_api_and_nonempty_native_verified_results() {
        let value = json!({"run_id":"run_one","api_url":"https://api.infergrade.com","results":[{"result_id":"qb_one"}]});
        assert!(accepted_result(
            &value,
            "run_one",
            "https://api.infergrade.com"
        ));
        assert!(!accepted_result(
            &value,
            "run_two",
            "https://api.infergrade.com"
        ));
        assert!(!accepted_result(&value, "run_one", "https://other.test"));
        assert!(!accepted_result(
            &json!({"run_id":"run_one","api_url":"https://api.infergrade.com","results":[]}),
            "run_one",
            "https://api.infergrade.com"
        ));
        assert!(!TITLE.contains("qb_one"));
        assert!(!BODY.contains("https://"));
    }
}
