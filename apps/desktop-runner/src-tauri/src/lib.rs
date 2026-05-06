use keyring::{Entry, Error as KeyringError};
use reqwest::Url;
use serde_json::{json, Value};
use std::env;
use std::fs;
use std::net::IpAddr;
use std::path::PathBuf;
use std::process::Command;

const KEYRING_SERVICE: &str = "com.infergrade.runner";
const KEYRING_USER: &str = "hub-runner-token";
const LLAMA_CPP_RUNTIME_ID: &str = "llama-cpp-homebrew-stable-2026-04";
const RUNTIME_MANIFEST_VERSION: &str = "2026-04-22";

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

fn runtime_cache_root() -> Result<PathBuf, String> {
    if let Ok(value) = env::var("INFERGRADE_RUNTIME_CACHE_DIR") {
        let trimmed = value.trim();
        if !trimmed.is_empty() {
            return Ok(PathBuf::from(trimmed));
        }
    }
    let home = env::var("HOME")
        .or_else(|_| env::var("USERPROFILE"))
        .map_err(|_| "Could not resolve a home directory for the runtime cache.".to_string())?;
    Ok(PathBuf::from(home)
        .join(".cache")
        .join("infergrade")
        .join("runtimes"))
}

fn selected_llama_cpp_runtime_path() -> Result<PathBuf, String> {
    Ok(runtime_cache_root()?
        .join("llama.cpp")
        .join("selected_runtime.json"))
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

fn sanitized_runner_profile(profile: &Value) -> Value {
    json!({
        "api_url": profile.get("api_url").and_then(Value::as_str).unwrap_or(""),
        "runner_id": profile.get("runner_id").and_then(Value::as_str).unwrap_or(""),
        "label": profile.get("label").and_then(Value::as_str).unwrap_or(""),
        "preferred_execution_mode": profile.get("preferred_execution_mode").and_then(Value::as_str).unwrap_or(""),
        "paired_at": profile.get("paired_at").and_then(Value::as_str).unwrap_or(""),
        "expires_at": profile.get("expires_at").and_then(Value::as_str).unwrap_or(""),
        "user": profile.get("user").cloned().unwrap_or(Value::Null),
        "has_access_token": profile.get("access_token").and_then(Value::as_str).map(|token| !token.trim().is_empty()).unwrap_or(false),
    })
}

fn ui_pairing_response(mut body: Value, profile: &Value, profile_path: PathBuf) -> Value {
    body["runner_profile"] = sanitized_runner_profile(profile);
    body["profile_path"] = Value::String(profile_path.display().to_string());
    body["next_action"] = Value::String("start_runner".to_string());
    body["commands"] = json!({ "start": "infergrade start" });
    body
}

fn profile_string(profile: Option<&Value>, key: &str) -> Option<String> {
    profile
        .and_then(|value| value.get(key))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn profile_token_available(profile: Option<&Value>) -> bool {
    profile_string(profile, "access_token").is_some()
}

fn build_listener_start_plan(
    api_url: &str,
    typed_token_present: bool,
    profile: Option<&Value>,
    os_token_available: bool,
) -> Result<Value, String> {
    let normalized_api_url = normalize_desktop_api_url(api_url)?;
    let profile_available = profile.is_some();
    let profile_has_token = profile_token_available(profile);
    let credential_source = if typed_token_present {
        "typed_input"
    } else if profile_available && profile_has_token && os_token_available {
        "saved_pairing"
    } else {
        "missing"
    };
    Ok(json!({
        "api_url": normalized_api_url,
        "runner_id": profile_string(profile, "runner_id").unwrap_or_default(),
        "execution_mode": profile_string(profile, "preferred_execution_mode").unwrap_or_else(|| preferred_execution_mode().to_string()),
        "credential_source": credential_source,
        "can_start": credential_source != "missing",
        "profile_status": if profile_available { "present" } else { "missing" },
        "profile_token_status": if profile_has_token { "present" } else { "missing" },
        "token_status": if os_token_available { "present" } else { "missing" },
    }))
}

fn command_version(program: &str) -> Value {
    match Command::new(program).arg("--version").output() {
        Ok(output) if output.status.success() => {
            let text = String::from_utf8_lossy(if output.stdout.is_empty() {
                &output.stderr
            } else {
                &output.stdout
            })
            .trim()
            .lines()
            .next()
            .unwrap_or("")
            .to_string();
            json!({"status": "found", "program": program, "version": text})
        }
        Ok(output) => json!({
            "status": "error",
            "program": program,
            "detail": String::from_utf8_lossy(&output.stderr).trim().chars().take(300).collect::<String>(),
        }),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            json!({"status": "not_found", "program": program})
        }
        Err(error) => json!({"status": "error", "program": program, "detail": error.to_string()}),
    }
}

fn recommended_llama_cpp_runtime() -> Value {
    if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
        json!({
            "runtime_id": LLAMA_CPP_RUNTIME_ID,
            "backend": "llama.cpp",
            "accelerator": "metal",
            "platform": "macOS Apple Silicon",
            "source": "homebrew",
            "provenance": "Homebrew formula `llama.cpp`; inspect with `brew info llama.cpp` before executing.",
            "install_command": ["brew", "install", "llama.cpp"],
            "download_required": false,
            "supported_on_this_platform": true,
            "notes": [
                "Recommended managed path for Apple Silicon native benchmarking.",
                "No install command was run. Installation remains explicit."
            ],
        })
    } else {
        json!({
            "runtime_id": "llama-cpp-native-manual",
            "backend": "llama.cpp",
            "accelerator": preferred_execution_mode(),
            "platform": format!("{} {}", env::consts::OS, env::consts::ARCH),
            "source": "manual",
            "provenance": "Use an explicit llama.cpp build for this platform until InferGrade ships a verified runtime lane.",
            "install_command": Value::Null,
            "download_required": false,
            "download_policy": verified_runtime_download_policy(),
            "supported_on_this_platform": false,
            "notes": [
                "Verified GPU-specific runtime downloads are not implemented yet.",
                "No install command was run. Installation remains explicit."
            ],
        })
    }
}

fn verified_runtime_download_policy() -> Value {
    let verifier_status = if verify_runtime_download_manifest(&json!({
        "runtime_id": "schema-check",
        "archive_url": "https://downloads.infergrade.com/runtimes/schema-check.tar.zst",
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "signature_url": "https://downloads.infergrade.com/runtimes/schema-check.tar.zst.minisig",
        "expected_binaries": ["llama-cli", "llama-server"],
        "rollback_runtime_id": "previous-runtime",
    }))
    .is_ok()
    {
        "ready"
    } else {
        "unavailable"
    };
    json!({
        "status": "not_configured",
        "manifest_verifier": verifier_status,
        "requires_explicit_user_action": true,
        "required_fields": [
            "runtime_id",
            "archive_url",
            "sha256",
            "signature_url",
            "expected_binaries",
            "rollback_runtime_id"
        ],
        "message": "Runtime downloads are disabled until a manifest entry passes HTTPS, checksum, signature, expected-binary, and rollback validation.",
    })
}

fn verify_runtime_download_manifest(entry: &Value) -> Result<(), String> {
    let runtime_id = entry
        .get("runtime_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim();
    if runtime_id.is_empty() {
        return Err("runtime_id is required".to_string());
    }
    for key in ["archive_url", "signature_url"] {
        let raw = entry.get(key).and_then(Value::as_str).unwrap_or("").trim();
        let url = Url::parse(raw).map_err(|_| format!("{key} must be a valid HTTPS URL"))?;
        if url.scheme() != "https" {
            return Err(format!("{key} must use HTTPS"));
        }
    }
    let sha256 = entry
        .get("sha256")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim();
    if sha256.len() != 64 || !sha256.chars().all(|ch| ch.is_ascii_hexdigit()) {
        return Err("sha256 must be a 64-character hex digest".to_string());
    }
    let binaries = entry
        .get("expected_binaries")
        .and_then(Value::as_array)
        .ok_or_else(|| "expected_binaries must list required runtime binaries".to_string())?;
    let has_binary = |name: &str| {
        binaries
            .iter()
            .any(|item| item.as_str().map(|value| value == name).unwrap_or(false))
    };
    if !has_binary("llama-cli") || !has_binary("llama-server") {
        return Err("expected_binaries must include llama-cli and llama-server".to_string());
    }
    let rollback = entry
        .get("rollback_runtime_id")
        .and_then(Value::as_str)
        .unwrap_or("")
        .trim();
    if rollback.is_empty() {
        return Err("rollback_runtime_id is required".to_string());
    }
    Ok(())
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
    match runner_token_entry()?.get_password() {
        Ok(token) => Ok(!token.trim().is_empty()),
        Err(KeyringError::NoEntry) => Ok(false),
        Err(error) if is_user_canceled(&error) => Ok(false),
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
    let profile = load_runner_profile()?;
    let token_available = runner_token_available()?;
    Ok(runner_pairing_status_payload(
        profile,
        token_available,
        profile_path,
    ))
}

fn runner_pairing_status_payload(
    profile: Option<Value>,
    token_available: bool,
    profile_path: PathBuf,
) -> Value {
    let profile_status = match profile {
        Some(profile) => json!({
            "status": "present",
            "profile": sanitized_runner_profile(&profile),
        }),
        None => json!({
            "status": "missing",
            "profile": Value::Null,
        }),
    };
    let profile_available = profile_status["status"] == "present";
    json!({
        "paired": profile_available && token_available,
        "profile_path": profile_path.display().to_string(),
        "profile": profile_status,
        "token": {
            "status": if token_available { "present" } else { "missing" },
            "stored_in": "os_credential_store",
        },
    })
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
fn reset_runner_pairing() -> Result<Value, String> {
    let token_cleared = match clear_runner_token() {
        Ok(()) => true,
        Err(error) => return Err(error),
    };
    let profile = clear_runner_profile()?;
    Ok(json!({
        "reset": true,
        "token_cleared": token_cleared,
        "profile": profile,
    }))
}

#[tauri::command]
fn llama_cpp_runtime_plan() -> Value {
    let cli = command_version("llama-cli");
    let server = command_version("llama-server");
    let runtime_available = cli.get("status").and_then(Value::as_str) == Some("found")
        && server.get("status").and_then(Value::as_str) == Some("found");
    json!({
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "runtime_family": "llama.cpp",
        "recommended_runtime": recommended_llama_cpp_runtime(),
        "download_policy": verified_runtime_download_policy(),
        "selected_runtime": selected_llama_cpp_runtime(),
        "detected_binaries": {
            "cli": cli,
            "server": server,
            "perplexity": command_version("llama-perplexity"),
        },
        "native_runtime_status": if runtime_available { "available" } else { "missing" },
        "message": if runtime_available {
            "llama.cpp binaries are available. Review provenance before running benchmark jobs."
        } else {
            "No install command was run. Select or install a native llama.cpp runtime before the first local benchmark."
        },
    })
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
    let body = parsed.ok_or_else(|| "Hub pairing response was not valid JSON.".to_string())?;
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
    Ok(ui_pairing_response(body, &profile, profile_path))
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
            clear_runner_token,
            runner_pairing_status,
            listener_start_plan,
            reset_runner_pairing,
            llama_cpp_runtime_plan,
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
    fn pairing_status_requires_profile_and_os_token_to_be_ready() {
        let profile = json!({
            "api_url": "https://api.infergrade.com/",
            "runner_id": "runner_123",
            "label": "Test runner",
        });
        let path = PathBuf::from("/tmp/infergrade/runner_profile.json");

        let stale_profile =
            runner_pairing_status_payload(Some(profile.clone()), false, path.clone());
        assert_eq!(stale_profile["paired"], false);
        assert_eq!(stale_profile["profile"]["status"], "present");
        assert_eq!(stale_profile["token"]["status"], "missing");

        let token_without_profile = runner_pairing_status_payload(None, true, path.clone());
        assert_eq!(token_without_profile["paired"], false);
        assert_eq!(token_without_profile["profile"]["status"], "missing");
        assert_eq!(token_without_profile["token"]["status"], "present");

        let ready = runner_pairing_status_payload(Some(profile), true, path);
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
}
