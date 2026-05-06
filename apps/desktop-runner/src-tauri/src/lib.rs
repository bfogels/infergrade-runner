use keyring::{Entry, Error as KeyringError};
use reqwest::Url;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::net::IpAddr;
use std::path::PathBuf;

const KEYRING_SERVICE: &str = "com.infergrade.runner";
const KEYRING_USER: &str = "hub-runner-token";

fn runner_token_entry() -> Result<Entry, String> {
    Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .map_err(|error| format!("could not open OS credential store: {error}"))
}

fn is_user_canceled(error: &KeyringError) -> bool {
    let message = error.to_string().to_lowercase();
    message.contains("cancel") || message.contains("user interaction")
}

fn is_local_http_host(host: &str) -> bool {
    if host == "localhost" {
        return true;
    }
    host.parse::<IpAddr>()
        .map(|address| address.is_loopback())
        .unwrap_or(false)
}

fn normalize_desktop_api_url(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim();
    let with_scheme = if trimmed.is_empty() {
        "https://api.infergrade.com".to_string()
    } else if trimmed.starts_with("http://") || trimmed.starts_with("https://") {
        trimmed.to_string()
    } else if trimmed.starts_with("localhost")
        || trimmed.starts_with("127.")
        || trimmed.starts_with("[::1]")
    {
        format!("http://{trimmed}")
    } else {
        format!("https://{trimmed}")
    };

    let parsed = Url::parse(&with_scheme).map_err(|_| {
        "Hub URL is invalid. Use https://api.infergrade.com or a local http://localhost URL."
            .to_string()
    })?;
    let host = parsed
        .host_str()
        .ok_or_else(|| "Hub URL must include a host.".to_string())?
        .to_lowercase();
    match parsed.scheme() {
        "https" => Ok(parsed.to_string()),
        "http" if is_local_http_host(&host) => Ok(parsed.to_string()),
        _ => Err("Hosted Hub URLs must use HTTPS. HTTP is allowed only for localhost or loopback addresses.".to_string()),
    }
}

fn preferred_execution_mode() -> &'static str {
    if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
        "local_native"
    } else {
        "local_container"
    }
}

fn hostname() -> Option<String> {
    env::var("HOSTNAME")
        .or_else(|_| env::var("COMPUTERNAME"))
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn desktop_environment() -> Value {
    json!({
        "source": "desktop_rust_supervisor",
        "os": env::consts::OS,
        "arch": env::consts::ARCH,
        "hardware_class": if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
            "apple_silicon"
        } else {
            "unknown"
        },
        "execution_mode": preferred_execution_mode(),
    })
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

#[tauri::command]
fn load_runner_token() -> Result<Option<String>, String> {
    match runner_token_entry()?.get_password() {
        Ok(token) => Ok(Some(token)),
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
async fn redeem_runner_pairing(
    api_url: String,
    pair_code: String,
    label: Option<String>,
) -> Result<Value, String> {
    let api_url = normalize_desktop_api_url(&api_url)?;
    let pair_code = pair_code.trim();
    if pair_code.is_empty() {
        return Err("Paste the one-time pairing code from the Hub first.".to_string());
    }
    let label = label.unwrap_or_default().trim().to_string();
    let payload = json!({
        "pair_code": pair_code,
        "label": if label.is_empty() { Value::Null } else { Value::String(label) },
        "hostname": hostname(),
        "preferred_execution_mode": preferred_execution_mode(),
        "environment": desktop_environment(),
    });
    let url = format!(
        "{}/v1/runner-pairings/redeem",
        api_url.trim_end_matches('/')
    );
    let response = reqwest::Client::new()
        .post(url)
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
    let mut body = parsed.ok_or_else(|| "Hub pairing response was not valid JSON.".to_string())?;
    let profile = body
        .get("runner_profile")
        .cloned()
        .ok_or_else(|| "Hub pairing response did not include a runner profile.".to_string())?;
    let access_token = profile
        .get("access_token")
        .and_then(Value::as_str)
        .ok_or_else(|| "Hub pairing response did not include a runner token.".to_string())?;
    let profile_path = save_runner_profile(&profile)?;
    save_runner_token_value(access_token)?;
    body["profile_path"] = Value::String(profile_path.display().to_string());
    body["next_action"] = Value::String("start_runner".to_string());
    body["commands"] = json!({ "start": "infergrade start" });
    Ok(body)
}

fn pairing_error_detail(payload: &Value) -> Option<&str> {
    payload
        .get("detail")
        .and_then(Value::as_str)
        .or_else(|| payload.pointer("/error/message").and_then(Value::as_str))
        .or_else(|| payload.get("error").and_then(Value::as_str))
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            save_runner_token,
            load_runner_token,
            clear_runner_token,
            redeem_runner_pairing
        ])
        .run(tauri::generate_context!())
        .expect("error while running InferGrade desktop runner");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalizes_hosted_and_local_api_urls() {
        assert_eq!(
            normalize_desktop_api_url("").expect("hosted default"),
            "https://api.infergrade.com/"
        );
        assert_eq!(
            normalize_desktop_api_url("api.infergrade.com").expect("hosted shorthand"),
            "https://api.infergrade.com/"
        );
        assert_eq!(
            normalize_desktop_api_url("localhost:8000").expect("local shorthand"),
            "http://localhost:8000/"
        );
        assert_eq!(
            normalize_desktop_api_url("127.0.0.1:8000").expect("loopback shorthand"),
            "http://127.0.0.1:8000/"
        );
    }

    #[test]
    fn rejects_cleartext_hosted_api_urls() {
        let error = normalize_desktop_api_url("http://api.infergrade.com")
            .expect_err("cleartext hosted rejected");
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
}
