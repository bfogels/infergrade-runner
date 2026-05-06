mod errors;
mod events;
mod profile;
mod token_store;

pub use errors::RunnerError;
pub use events::{RunnerEvent, RuntimeInfo};
pub use profile::{MemoryProfileStore, ProfileStore, RunnerProfile, SanitizedRunnerProfile};
pub use token_store::{MemoryTokenStore, TokenStore};

use serde_json::{json, Value};
use std::env;
use std::net::IpAddr;
use std::path::PathBuf;
use std::process::Command as StdCommand;
use url::Url;

pub const LLAMA_CPP_RUNTIME_ID: &str = "llama-cpp-homebrew-stable-2026-04";
pub const RUNTIME_MANIFEST_VERSION: &str = "2026-04-22";

fn is_local_http_host(host: &str) -> bool {
    if host == "localhost" {
        return true;
    }
    host.parse::<IpAddr>()
        .map(|address| address.is_loopback())
        .unwrap_or(false)
}

pub fn normalize_api_url(raw: &str) -> Result<String, String> {
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

pub fn preferred_execution_mode() -> &'static str {
    if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
        "local_native"
    } else {
        "local_container"
    }
}

pub fn hostname() -> Option<String> {
    env::var("HOSTNAME")
        .or_else(|_| env::var("COMPUTERNAME"))
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

pub fn desktop_environment() -> Value {
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

pub fn runtime_cache_root() -> Result<PathBuf, String> {
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

pub fn selected_llama_cpp_runtime_path() -> Result<PathBuf, String> {
    Ok(runtime_cache_root()?
        .join("llama.cpp")
        .join("selected_runtime.json"))
}

pub fn sanitized_runner_profile(profile: &Value) -> Value {
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

pub fn ui_pairing_response(mut body: Value, profile: &Value, profile_path: PathBuf) -> Value {
    body["runner_profile"] = sanitized_runner_profile(profile);
    body["profile_path"] = Value::String(profile_path.display().to_string());
    body["next_action"] = Value::String("start_runner".to_string());
    body["commands"] = json!({ "start": "infergrade start" });
    body
}

pub fn profile_string(profile: Option<&Value>, key: &str) -> Option<String> {
    profile
        .and_then(|value| value.get(key))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

pub fn profile_token_available(profile: Option<&Value>) -> bool {
    profile_string(profile, "access_token").is_some()
}

pub fn build_listener_start_plan(
    api_url: &str,
    typed_token_present: bool,
    profile: Option<&Value>,
    os_token_available: bool,
) -> Result<Value, String> {
    let normalized_api_url = normalize_api_url(api_url)?;
    let profile_available = profile.is_some();
    let profile_has_token = profile_token_available(profile);
    let credential_source = if typed_token_present {
        "typed_input"
    } else if profile_available && os_token_available {
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

pub fn runner_id_from_profile(profile: Option<&Value>) -> String {
    profile_string(profile, "runner_id").unwrap_or_else(|| {
        hostname()
            .map(|host| format!("runner-{host}"))
            .unwrap_or_else(|| "runner-local".to_string())
    })
}

pub fn runner_register_payload(
    runner_id: &str,
    execution_mode: &str,
    hostname: Option<String>,
) -> Value {
    json!({
        "runner_id": runner_id,
        "execution_modes": [execution_mode],
        "status": "starting",
        "label": runner_id,
        "runner_kind": if execution_mode == "cloud_container" { "cloud_worker" } else { "local_listener" },
        "hostname": hostname,
        "provider_id": Value::Null,
        "instance_type_id": Value::Null,
        "capabilities": {
            "run_token_supported": true,
            "auto_upload": true,
        },
        "version": env!("CARGO_PKG_VERSION"),
        "environment": desktop_environment(),
        "contract": {},
        "diagnostics": {},
    })
}

pub fn runner_heartbeat_payload(
    status: &str,
    current_run_id: Option<&str>,
    hostname: Option<String>,
    message: Option<&str>,
) -> Value {
    json!({
        "status": status,
        "current_run_id": current_run_id,
        "hostname": hostname,
        "provider_id": Value::Null,
        "instance_type_id": Value::Null,
        "metadata": match message {
            Some(message) => json!({"message": message}),
            None => json!({}),
        },
        "environment": desktop_environment(),
        "contract": {},
        "diagnostics": {},
    })
}

pub fn claim_run_job_payload(
    worker_id: &str,
    execution_mode: &str,
    run_id: Option<&str>,
    run_config_id: Option<&str>,
    hostname: Option<String>,
) -> Value {
    json!({
        "worker_id": worker_id,
        "execution_mode": execution_mode,
        "run_id": run_id,
        "run_config_id": run_config_id,
        "provider_id": Value::Null,
        "instance_type_id": Value::Null,
        "hostname": hostname,
    })
}

pub fn worker_request_url(api_url: &str, path: &str) -> Result<String, String> {
    let normalized = normalize_api_url(api_url)?;
    Ok(format!(
        "{}/{}",
        normalized.trim_end_matches('/'),
        path.trim_start_matches('/')
    ))
}

pub fn worker_request_preview(
    api_url: &str,
    path: &str,
    payload: Value,
    token: &str,
) -> Result<Value, String> {
    Ok(json!({
        "url": worker_request_url(api_url, path)?,
        "method": "POST",
        "has_authorization": !token.trim().is_empty(),
        "payload": payload,
    }))
}

pub fn redact_listener_text(text: &str, sensitive_values: &[String]) -> String {
    sensitive_values
        .iter()
        .filter(|value| !value.trim().is_empty())
        .fold(text.to_string(), |redacted, value| {
            redacted.replace(value, "[redacted]")
        })
}

pub fn redact_worker_text(text: &str, sensitive_values: &[String]) -> String {
    let redacted = redact_listener_text(text, sensitive_values);
    redacted
        .replace("Authorization", "[redacted-header]")
        .replace("authorization", "[redacted-header]")
}

pub fn redact_worker_response(value: Value, sensitive_values: &[String]) -> Value {
    match value {
        Value::String(text) => Value::String(redact_worker_text(&text, sensitive_values)),
        Value::Array(items) => Value::Array(
            items
                .into_iter()
                .map(|item| redact_worker_response(item, sensitive_values))
                .collect(),
        ),
        Value::Object(entries) => Value::Object(
            entries
                .into_iter()
                .map(|(key, value)| {
                    let normalized_key = key.to_lowercase();
                    let redacted_value = if normalized_key.contains("authorization")
                        || (normalized_key.contains("token") && value.is_string())
                    {
                        Value::String("[redacted]".to_string())
                    } else {
                        redact_worker_response(value, sensitive_values)
                    };
                    (key, redacted_value)
                })
                .collect(),
        ),
        other => other,
    }
}

pub fn pairing_error_detail(payload: &Value) -> Option<&str> {
    payload
        .get("detail")
        .and_then(Value::as_str)
        .or_else(|| payload.pointer("/error/message").and_then(Value::as_str))
        .or_else(|| payload.get("error").and_then(Value::as_str))
}

pub fn command_version(program: &str) -> Value {
    match StdCommand::new(program).arg("--version").output() {
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

pub fn verified_runtime_download_policy() -> Value {
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

pub fn recommended_llama_cpp_runtime() -> Value {
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

pub fn llama_cpp_runtime_plan(selected_runtime: Value) -> Value {
    let cli = command_version("llama-cli");
    let server = command_version("llama-server");
    let runtime_available = cli.get("status").and_then(Value::as_str) == Some("found")
        && server.get("status").and_then(Value::as_str) == Some("found");
    json!({
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "runtime_family": "llama.cpp",
        "recommended_runtime": recommended_llama_cpp_runtime(),
        "download_policy": verified_runtime_download_policy(),
        "selected_runtime": selected_runtime,
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

pub fn verify_runtime_download_manifest(entry: &Value) -> Result<(), String> {
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

#[cfg(test)]
mod tests {
    use super::*;

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
    fn runtime_plan_is_inspection_only_and_recommends_platform_lane() {
        let plan =
            llama_cpp_runtime_plan(json!({"status": "not_selected", "selection": Value::Null}));
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
