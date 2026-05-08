mod benchmark;
mod errors;
mod events;
mod hub_client;
mod pairing;
mod profile;
mod token_store;
mod worker_protocol;

pub use benchmark::{
    native_first_run_bundle_payload, run_native_first_run, run_native_first_run_with_events,
    validate_native_first_run_input, write_native_first_run_artifact,
    write_native_first_run_bundle_payload, LlamaCppRuntime, NativeCommandRuntime,
    NativeFirstRunArtifact, NativeFirstRunBundleOptions, NativeFirstRunInput,
    NativeFirstRunMetrics, NativeFirstRunResult, NativeFirstRunRuntime, NativeRuntimeOutput,
};
pub use errors::RunnerError;
pub use events::{RunnerEvent, RuntimeInfo};
pub use hub_client::{
    build_hub_json_request, build_run_bundle_upload_request, build_run_claim_request,
    build_run_completion_request, execute_hub_json_request, hub_api_url, shared_hub_client,
    shared_hub_upload_client, validate_hub_path_id, HubJsonRequest, HubJsonResponse, HubMethod,
};
pub use pairing::{
    build_pairing_redeem_request, complete_pairing_response, pairing_status_payload,
    reset_pairing_state, PairingCompletion, PairingInput, PairingRedeemRequest,
};
pub use profile::{MemoryProfileStore, ProfileStore, RunnerProfile, SanitizedRunnerProfile};
pub use token_store::{MemoryTokenStore, TokenStore};
pub use worker_protocol::{
    claim_run_job_payload, runner_heartbeat_payload, runner_register_payload, ClaimRunJobRequest,
    RunnerCapabilities, RunnerHeartbeatRequest, RunnerProtocolEndpoints, RunnerProtocolPingInput,
    RunnerProtocolPingPlan, RunnerProtocolPreview, RunnerProtocolPreviewInput,
    RunnerRegisterRequest,
};

use flate2::read::GzDecoder;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::env;
use std::fs;
use std::io::Read;
use std::net::IpAddr;
use std::path::{Path, PathBuf};
use std::process::Command as StdCommand;
use tar::Archive;
use url::Url;

pub const LLAMA_CPP_RUNTIME_ID: &str = "llama-cpp-homebrew-stable-2026-04";
pub const RUNTIME_MANIFEST_VERSION: &str = "2026-04-22";
pub const MANAGED_LLAMA_CPP_MACOS_METAL_RUNTIME_ID: &str = "llama-cpp-b9050-macos-arm64-metal";
const MANAGED_LLAMA_CPP_MACOS_METAL_TAG: &str = "b9050";
const MANAGED_LLAMA_CPP_MACOS_METAL_ARCHIVE_URL: &str =
    "https://github.com/ggml-org/llama.cpp/releases/download/b9050/llama-b9050-bin-macos-arm64.tar.gz";
const MANAGED_LLAMA_CPP_MACOS_METAL_SHA256: &str =
    "d334fa44e42a143ec6e49924f9630136c0b5fedc5a615508636ba9c8d08eb5d3";

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

pub fn load_selected_llama_cpp_runtime() -> Value {
    match selected_llama_cpp_runtime_path()
        .ok()
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
    {
        Some(selection) => json!({"status": "selected", "selection": selection}),
        None => json!({"status": "not_selected", "selection": Value::Null}),
    }
}

pub fn managed_llama_cpp_runtime_manifest() -> Value {
    json!({
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "runtime_family": "llama.cpp",
        "channels": managed_llama_cpp_runtime_channels(),
        "runtimes": [
            {
                "runtime_id": MANAGED_LLAMA_CPP_MACOS_METAL_RUNTIME_ID,
                "channel": "infergrade_stable",
                "backend": "llama.cpp",
                "accelerator": "metal",
                "version_label": "llama.cpp b9050 macOS arm64",
                "upstream": {
                    "project": "ggml-org/llama.cpp",
                    "tag": MANAGED_LLAMA_CPP_MACOS_METAL_TAG,
                    "release_url": "https://github.com/ggml-org/llama.cpp/releases/tag/b9050",
                },
                "platform": {
                    "system": "macos",
                    "arch": "aarch64",
                    "human": "macOS Apple Silicon",
                },
                "archive": {
                    "url": MANAGED_LLAMA_CPP_MACOS_METAL_ARCHIVE_URL,
                    "sha256": MANAGED_LLAMA_CPP_MACOS_METAL_SHA256,
                    "size_bytes": 8641914_u64,
                    "format": "tar.gz",
                    "checksum_source": "github_release_asset_digest",
                    "signature_url": Value::Null,
                },
                "verification": {
                    "sha256": true,
                    "expected_binaries": true,
                    "version_smoke": true,
                    "independent_signature": false,
                    "notes": [
                        "The GitHub release asset exposes a SHA-256 digest, but no independent signature asset was found during v0.2.2 planning.",
                        "Do not describe this runtime as independently signed until a signature lane exists.",
                    ],
                },
                "download": {
                    "enabled": true,
                    "requires_explicit_user_action": true,
                    "message": "Download only runs after explicit user action. InferGrade verifies SHA-256, expected binaries, and version smoke before selecting this runtime.",
                },
                "expected_binaries": ["llama-cli", "llama-server", "llama-perplexity"],
                "binary_names": {
                    "cli": "llama-cli",
                    "server": "llama-server",
                    "perplexity": "llama-perplexity",
                },
                "rollback_runtime_id": LLAMA_CPP_RUNTIME_ID,
                "compatibility_notes": [
                    "Recommended only for macOS Apple Silicon native first-run.",
                    "Windows and Linux remain preview/partial until separate runtime lanes are validated.",
                    "Native first-run evidence remains experimental/informational.",
                ],
                "provenance": "Upstream ggml-org/llama.cpp GitHub release asset with pinned SHA-256 digest; no independent signature verified.",
            }
        ],
    })
}

pub fn managed_llama_cpp_runtime_channels() -> Value {
    json!({
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "runtime_family": "llama.cpp",
        "channels": [
            {
                "channel": "infergrade_stable",
                "label": "InferGrade Stable",
                "audience": "default",
                "default": true,
                "managed_by_infergrade": true,
                "install_policy": "explicit_only",
                "update_policy": "manual_only",
                "provenance_expectation": "Pinned manifest entry with SHA-256 verification. Independent signature verification is not yet available.",
                "evidence_note": "Recommended for native first-run evidence, which remains experimental/informational until stronger trust gates exist.",
            },
            {
                "channel": "previous_release",
                "label": "Previous Stable",
                "audience": "recovery",
                "default": false,
                "managed_by_infergrade": true,
                "install_policy": "explicit_only",
                "update_policy": "manual_rollback_only",
                "provenance_expectation": "Pinned historical manifest entry when available.",
                "evidence_note": "Useful for recovery when a stable runtime update regresses.",
            },
            {
                "channel": "upstream_release",
                "label": "Upstream Release",
                "audience": "advanced",
                "default": false,
                "managed_by_infergrade": false,
                "install_policy": "explicit_only",
                "update_policy": "manual_only",
                "provenance_expectation": "Upstream release metadata must be reviewed before selection.",
                "evidence_note": "Directional evidence only unless promoted into InferGrade Stable.",
            },
            {
                "channel": "local_binary",
                "label": "Local Binary",
                "audience": "advanced",
                "default": false,
                "managed_by_infergrade": false,
                "install_policy": "user_selected_path_only",
                "update_policy": "not_managed",
                "provenance_expectation": "User-selected local path. InferGrade validates executability but does not verify archive provenance.",
                "evidence_note": "Useful local evidence, not an InferGrade-managed runtime claim.",
            },
            {
                "channel": "experimental",
                "label": "Experimental",
                "audience": "advanced",
                "default": false,
                "managed_by_infergrade": false,
                "install_policy": "explicit_only",
                "update_policy": "manual_only",
                "provenance_expectation": "Requires clear user opt-in and visible warnings.",
                "evidence_note": "Experimental evidence only; never decision-grade by channel alone.",
            },
        ],
    })
}

fn runtime_channel_details(channel: &str) -> Value {
    managed_llama_cpp_runtime_channels()["channels"]
        .as_array()
        .and_then(|channels| {
            channels
                .iter()
                .find(|entry| entry["channel"].as_str() == Some(channel))
                .cloned()
        })
        .unwrap_or_else(|| {
            json!({
                "channel": channel,
                "label": "Unknown Runtime Channel",
                "audience": "unknown",
                "default": false,
                "managed_by_infergrade": false,
                "install_policy": "unknown",
                "update_policy": "manual_review_required",
                "provenance_expectation": "Unknown channel; review runtime provenance before running benchmarks.",
                "evidence_note": "Treat evidence as informational until the runtime channel is understood.",
            })
        })
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

pub fn worker_request_url(api_url: &str, path: &str) -> Result<String, String> {
    hub_api_url(api_url, path).map_err(|error| error.message().to_string())
}

pub fn worker_request_preview(
    api_url: &str,
    path: &str,
    payload: Value,
    token: &str,
) -> Result<Value, String> {
    build_hub_json_request(HubMethod::Post, api_url, path, Some(payload), Some(token))
        .map(|request| request.sanitized_preview())
        .map_err(|error| error.message().to_string())
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

fn command_probe(program: &str, args: &[&str]) -> Value {
    match StdCommand::new(program).args(args).output() {
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
            json!({"status": "found", "program": program, "output": text})
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

pub fn command_version(program: &str) -> Value {
    let probed = command_probe(program, &["--version"]);
    if probed.get("status").and_then(Value::as_str) == Some("found") {
        json!({
            "status": "found",
            "program": program,
            "version": probed.get("output").and_then(Value::as_str).unwrap_or(""),
        })
    } else {
        probed
    }
}

pub fn container_runtime_check(program: &str) -> Value {
    let cli = command_version(program);
    let cli_status = cli.get("status").and_then(Value::as_str).unwrap_or("error");
    let daemon = if cli_status == "found" {
        command_probe(program, &["info"])
    } else {
        json!({"status": cli_status, "program": program})
    };
    let daemon_status = daemon
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("error");
    let available = cli_status == "found" && daemon_status == "found";
    json!({
        "provider": program,
        "status": if available {
            "available"
        } else if cli_status == "found" {
            "daemon_unreachable"
        } else {
            cli_status
        },
        "available": available,
        "cli": cli,
        "daemon": daemon,
        "first_run_required": false,
        "capability": "advanced_sandboxed_benchmarks",
        "message": if available {
            format!("{program} detected. Advanced sandboxed benchmarks can be enabled.")
        } else if cli_status == "found" {
            format!("{program} CLI detected, but the container daemon is not reachable. Native runtime setup can continue; advanced sandboxed benchmarks are disabled.")
        } else {
            format!("{program} not found. Native runtime setup can continue; advanced sandboxed benchmarks are disabled.")
        },
    })
}

pub fn container_runtime_readiness() -> Value {
    let docker = container_runtime_check("docker");
    let podman = container_runtime_check("podman");
    let any_available = docker
        .get("available")
        .and_then(Value::as_bool)
        .unwrap_or(false)
        || podman
            .get("available")
            .and_then(Value::as_bool)
            .unwrap_or(false);
    json!({
        "status": if any_available { "available" } else { "not_found" },
        "docker_required_for_first_run": false,
        "first_run_message": "Docker and Podman are optional advanced sandbox providers; they do not gate native first-run setup.",
        "advanced_sandboxed_benchmarks": if any_available { "available" } else { "disabled" },
        "runtimes": {
            "docker": docker,
            "podman": podman,
        },
    })
}

pub fn verified_runtime_download_policy() -> Value {
    let manifest = managed_llama_cpp_runtime_manifest();
    let verifier_status = if manifest["runtimes"]
        .as_array()
        .and_then(|entries| entries.first())
        .map(verify_runtime_download_manifest)
        .transpose()
        .is_ok()
    {
        "ready"
    } else {
        "unavailable"
    };
    json!({
        "status": "configured",
        "manifest_verifier": verifier_status,
        "requires_explicit_user_action": true,
        "required_fields": [
            "runtime_id",
            "channel",
            "upstream",
            "platform",
            "archive.url",
            "archive.sha256",
            "expected_binaries",
            "rollback_runtime_id"
        ],
        "message": "Runtime downloads require explicit user action and must pass HTTPS, SHA-256, expected-binary, version-smoke, and rollback checks before selection.",
    })
}

pub fn recommended_llama_cpp_runtime() -> Value {
    if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
        managed_llama_cpp_runtime_manifest()["runtimes"][0].clone()
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

fn safe_runtime_id(value: Option<&str>) -> Result<String, String> {
    let runtime_id = value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(LLAMA_CPP_RUNTIME_ID);
    if runtime_id.len() > 120
        || runtime_id == "."
        || runtime_id == ".."
        || !runtime_id
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '.' | '_' | '-'))
    {
        return Err(
            "runtime_id must contain only letters, numbers, dots, underscores, or dashes."
                .to_string(),
        );
    }
    Ok(runtime_id.to_string())
}

fn find_program_path(program: &str) -> Option<PathBuf> {
    let path = env::var_os("PATH")?;
    for dir in env::split_paths(&path) {
        let candidate = dir.join(program);
        if candidate.is_file() && is_executable_file(&candidate) {
            return Some(candidate);
        }
        if cfg!(windows) {
            let candidate = dir.join(format!("{program}.exe"));
            if candidate.is_file() && is_executable_file(&candidate) {
                return Some(candidate);
            }
        }
    }
    None
}

fn is_executable_file(path: &Path) -> bool {
    if !path.is_file() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::metadata(path)
            .map(|metadata| metadata.permissions().mode() & 0o111 != 0)
            .unwrap_or(false)
    }
    #[cfg(not(unix))]
    {
        true
    }
}

fn validate_existing_runtime_path(
    path: &Path,
    kind: &str,
    required_name: &str,
) -> Result<String, String> {
    if !path.is_file() {
        return Err(format!(
            "{kind} path `{}` does not exist or is not a file.",
            path.display()
        ));
    }
    if !is_executable_file(path) {
        return Err(format!(
            "{kind} path `{}` is not executable. Select a runnable llama.cpp binary.",
            path.display()
        ));
    }
    let canonical = fs::canonicalize(path).map_err(|error| {
        format!(
            "could not resolve {kind} path `{}`: {error}",
            path.display()
        )
    })?;
    validate_llama_cpp_binary(&canonical, kind, required_name)?;
    Ok(canonical.display().to_string())
}

fn validate_llama_cpp_binary(path: &Path, kind: &str, required_name: &str) -> Result<(), String> {
    let output = StdCommand::new(path)
        .arg("--version")
        .output()
        .map_err(|error| {
            format!(
                "could not execute {kind} path `{}` with --version: {error}",
                path.display()
            )
        })?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);
    let preview = stdout
        .lines()
        .chain(stderr.lines())
        .map(str::trim)
        .find(|line| !line.is_empty())
        .unwrap_or("")
        .chars()
        .take(300)
        .collect::<String>();
    if !output.status.success() {
        return Err(format!(
            "{kind} path `{}` did not run successfully with --version. First output: {}",
            path.display(),
            if preview.is_empty() {
                "(none)"
            } else {
                &preview
            }
        ));
    }
    let binary_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("");
    let lower_name = binary_name.to_ascii_lowercase();
    let lower_output = preview.to_ascii_lowercase();
    let expected_name = required_name.to_ascii_lowercase();
    if !lower_name.contains(&expected_name) && !lower_output.contains("llama") {
        return Err(format!(
            "{kind} path `{}` does not look like a llama.cpp `{required_name}` binary.",
            path.display()
        ));
    }
    Ok(())
}

fn resolve_existing_runtime_binary(
    explicit_path: Option<PathBuf>,
    program: &str,
    kind: &str,
    required: bool,
) -> Result<Option<String>, String> {
    if let Some(path) = explicit_path {
        return validate_existing_runtime_path(&path, kind, program).map(Some);
    }
    if let Some(path) = find_program_path(program) {
        return validate_existing_runtime_path(&path, kind, program).map(Some);
    }
    if required {
        Err(format!(
            "Cannot select existing llama.cpp runtime; missing required {kind} binary. Provide an explicit path instead of relying on PATH."
        ))
    } else {
        Ok(None)
    }
}

fn resolve_optional_sibling_runtime_binary(
    cli: &Path,
    explicit_path: Option<PathBuf>,
    program: &str,
    kind: &str,
) -> Result<Option<String>, String> {
    if let Some(path) = explicit_path {
        return validate_existing_runtime_path(&path, kind, program).map(Some);
    }
    let Some(parent) = cli.parent() else {
        return Ok(None);
    };
    let candidate = parent.join(program);
    if candidate.is_file() {
        return validate_existing_runtime_path(&candidate, kind, program).map(Some);
    }
    if cfg!(windows) {
        let candidate = parent.join(format!("{program}.exe"));
        if candidate.is_file() {
            return validate_existing_runtime_path(&candidate, kind, program).map(Some);
        }
    }
    Ok(None)
}

pub fn select_existing_llama_cpp_runtime(
    runtime_id: Option<&str>,
    cli_path: Option<PathBuf>,
    server_path: Option<PathBuf>,
    perplexity_path: Option<PathBuf>,
) -> Result<Value, String> {
    let runtime_id = safe_runtime_id(runtime_id)?;
    let cli_was_explicit = cli_path.is_some();
    let cli = resolve_existing_runtime_binary(cli_path, "llama-cli", "llama-cli", true)?
        .ok_or_else(|| "llama-cli selection failed.".to_string())?;
    let cli_path = PathBuf::from(&cli);
    let server = if cli_was_explicit {
        resolve_optional_sibling_runtime_binary(
            &cli_path,
            server_path,
            "llama-server",
            "llama-server",
        )?
    } else {
        resolve_existing_runtime_binary(server_path, "llama-server", "llama-server", false)?
    };
    let perplexity = if cli_was_explicit {
        resolve_optional_sibling_runtime_binary(
            &cli_path,
            perplexity_path,
            "llama-perplexity",
            "llama-perplexity",
        )?
    } else {
        resolve_existing_runtime_binary(
            perplexity_path,
            "llama-perplexity",
            "llama-perplexity",
            false,
        )?
    };
    let selection = json!({
        "runtime_id": runtime_id,
        "backend": "llama.cpp",
        "version_label": "existing local binary",
        "source": "selected_existing",
        "channel": "local_binary",
        "provenance": "User-selected existing llama.cpp binary. No runtime download or install command was run by InferGrade.",
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "binaries": {
            "cli": cli,
            "server": server,
            "perplexity": perplexity,
        },
        "selected_at_platform": {
            "system": env::consts::OS,
            "machine": env::consts::ARCH,
        },
    });
    let path = selected_llama_cpp_runtime_path()?;
    let parent = path.parent().ok_or_else(|| {
        format!(
            "could not resolve selected runtime directory for `{}`",
            path.display()
        )
    })?;
    fs::create_dir_all(parent).map_err(|error| {
        format!(
            "could not create selected runtime directory `{}`: {error}",
            parent.display()
        )
    })?;
    let body = serde_json::to_string_pretty(&selection)
        .map_err(|error| format!("could not serialize selected runtime: {error}"))?;
    fs::write(&path, format!("{body}\n")).map_err(|error| {
        format!(
            "could not write selected runtime `{}`: {error}",
            path.display()
        )
    })?;
    Ok(json!({
        "status": "selected",
        "selection": selection,
        "path": path.display().to_string(),
        "message": "Existing llama.cpp runtime selected. No download or install command was run.",
    }))
}

pub fn llama_cpp_runtime_plan(selected_runtime: Value) -> Value {
    let cli = command_version("llama-cli");
    let server = command_version("llama-server");
    let selected_cli_available = selected_runtime
        .pointer("/selection/binaries/cli")
        .and_then(Value::as_str)
        .map(Path::new)
        .map(Path::is_file)
        .unwrap_or(false);
    let runtime_available =
        cli.get("status").and_then(Value::as_str) == Some("found") || selected_cli_available;
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

pub fn llama_cpp_runtime_status() -> Value {
    let selected_runtime = load_selected_llama_cpp_runtime();
    let mut selected_status = selected_runtime.clone();
    let selected_cli_path = selected_runtime
        .pointer("/selection/binaries/cli")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty());
    if selected_runtime.get("status").and_then(Value::as_str) == Some("selected") {
        match selected_cli_path {
            Some(path) if Path::new(path).is_file() => {}
            Some(path) => {
                selected_status["status"] = Value::String("stale".to_string());
                selected_status["recovery"] = json!({
                    "message": "Select a valid runtime or reinstall the managed runtime before running native first-run.",
                    "stale_path": path,
                });
            }
            None => {
                selected_status["status"] = Value::String("invalid".to_string());
                selected_status["recovery"] = json!({
                    "message": "The selected runtime record is missing binaries.cli. Select a valid runtime before running native first-run.",
                });
            }
        }
    }
    let mut plan = llama_cpp_runtime_plan(selected_status.clone());
    plan["managed_runtime_manifest"] = managed_llama_cpp_runtime_manifest();
    plan["selected_runtime"] = selected_status.clone();
    if selected_status
        .get("selection")
        .map(|selection| !selection.is_null())
        .unwrap_or(false)
    {
        let selected_channel = selected_status
            .pointer("/selection/channel")
            .and_then(Value::as_str)
            .unwrap_or("local_binary");
        plan["selected_channel"] = runtime_channel_details(selected_channel);
    } else {
        plan["selected_channel"] = json!({
            "channel": "not_selected",
            "label": "No Runtime Selected",
            "audience": "default",
            "default": false,
            "managed_by_infergrade": false,
            "install_policy": "select_or_install_required",
            "update_policy": "not_applicable",
            "provenance_expectation": "No runtime has been selected yet.",
            "evidence_note": "No native-first-run evidence can be produced until a runtime is selected or installed.",
        });
    }
    plan["runtime_channels"] = managed_llama_cpp_runtime_channels();
    plan["update_policy"] = json!({
        "automatic_updates": false,
        "message": "Runtime updates are manual. InferGrade will not silently download, upgrade, or switch llama.cpp runtimes.",
    });
    if selected_status.get("status").and_then(Value::as_str) == Some("stale") {
        plan["native_runtime_status"] = Value::String("missing".to_string());
        plan["recovery"] = selected_status["recovery"].clone();
        plan["message"] = Value::String(
            "Selected llama.cpp runtime is missing. Select a valid runtime before the first local benchmark."
                .to_string(),
        );
    }
    plan
}

pub fn build_support_summary(
    app_version: Option<&str>,
    pairing_status: Value,
    first_run_artifact: Option<Value>,
    recent_errors: &[String],
) -> Value {
    let runtime_status = llama_cpp_runtime_status();
    let selected_runtime = runtime_status
        .get("selected_runtime")
        .cloned()
        .unwrap_or(Value::Null);
    let selected_channel = runtime_status
        .get("selected_channel")
        .cloned()
        .unwrap_or(Value::Null);
    let selected_selection = selected_runtime.get("selection").unwrap_or(&Value::Null);
    let first_run_status = support_first_run_status(first_run_artifact.as_ref());
    let pairing = redact_support_value(pairing_status);
    let errors = recent_errors
        .iter()
        .filter_map(|error| {
            let sanitized = redact_support_text(error).trim().to_string();
            if sanitized.is_empty() {
                None
            } else {
                Some(Value::String(sanitized))
            }
        })
        .take(8)
        .collect::<Vec<_>>();
    json!({
        "export_kind": "infergrade_runner_support_summary_v1",
        "secrets_excluded": true,
        "app_version": app_version.unwrap_or(env!("CARGO_PKG_VERSION")),
        "runner_engine_version": env!("CARGO_PKG_VERSION"),
        "runtime": {
            "family": "llama.cpp",
            "native_runtime_status": runtime_status.get("native_runtime_status").cloned().unwrap_or(Value::Null),
            "message": runtime_status.get("message").cloned().unwrap_or(Value::Null),
            "selected_runtime_status": selected_runtime.get("status").cloned().unwrap_or(Value::Null),
            "selected_runtime_id": selected_selection.get("runtime_id").cloned().unwrap_or(Value::Null),
            "selected_channel": selected_channel,
            "runtime_path": selected_selection.pointer("/binaries/cli").cloned().unwrap_or(Value::Null),
            "provenance": selected_selection.get("provenance").cloned().unwrap_or_else(|| selected_selection.get("source").cloned().unwrap_or(Value::Null)),
            "recovery": runtime_status.get("recovery").cloned().unwrap_or(Value::Null),
            "update_policy": runtime_status.get("update_policy").cloned().unwrap_or(Value::Null),
        },
        "pairing": pairing,
        "first_run": first_run_status,
        "recent_errors": errors,
        "next_actions": support_next_actions(&runtime_status, first_run_artifact.as_ref()),
        "privacy": {
            "browser_visible_tokens": false,
            "excluded": [
                "runner tokens",
                "upload tokens",
                "bearer tokens",
                "authorization headers",
                "pairing codes"
            ],
        },
    })
}

fn support_first_run_status(first_run_artifact: Option<&Value>) -> Value {
    let Some(payload) = first_run_artifact else {
        return json!({
            "status": "not_provided",
            "upload_status": "unknown",
            "message": "No first-run artifact was provided for this support summary.",
        });
    };
    let artifact_path = payload
        .pointer("/artifact/path")
        .or_else(|| payload.pointer("/bundle_artifact/path"))
        .cloned()
        .unwrap_or(Value::Null);
    let bundle_artifact_path = payload
        .pointer("/bundle_artifact/path")
        .cloned()
        .unwrap_or(Value::Null);
    let uploaded = payload
        .pointer("/upload/uploaded")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let upload_status = if uploaded {
        "succeeded"
    } else if payload.get("upload").is_some() {
        "not_uploaded_or_failed"
    } else {
        "not_attempted"
    };
    json!({
        "status": redact_support_value(payload.pointer("/result/status").cloned().unwrap_or_else(|| Value::String("completed_or_unknown".to_string()))),
        "evidence_kind": redact_support_value(payload.pointer("/result/evidence_kind").cloned().unwrap_or(Value::Null)),
        "artifact_path": redact_support_value(artifact_path),
        "bundle_artifact_path": redact_support_value(bundle_artifact_path),
        "upload_status": upload_status,
        "upload_reason": redact_support_value(payload.pointer("/upload/reason").cloned().unwrap_or(Value::Null)),
        "run_id": redact_support_value(payload.pointer("/upload/run_id").cloned().unwrap_or(Value::Null)),
        "bundle_id": redact_support_value(payload.pointer("/upload/bundle_id").cloned().unwrap_or(Value::Null)),
        "message": if uploaded {
            "Local first-run completed and upload succeeded."
        } else {
            "Local first-run artifact is available; upload can be retried after pairing and Hub handoff are healthy."
        },
    })
}

fn support_next_actions(runtime_status: &Value, first_run_artifact: Option<&Value>) -> Value {
    let mut actions = Vec::new();
    match runtime_status
        .get("native_runtime_status")
        .and_then(Value::as_str)
    {
        Some("available") => {}
        _ => actions.push(json!({
            "area": "runtime",
            "action": "install_or_select_runtime",
            "message": "Install the recommended managed runtime or select a runnable llama.cpp binary before running native first-run.",
        })),
    }
    if runtime_status
        .pointer("/selected_runtime/status")
        .and_then(Value::as_str)
        == Some("stale")
    {
        actions.push(json!({
            "area": "runtime",
            "action": "repair_stale_selection",
            "message": "The selected runtime path is stale. Reinstall the managed runtime or select an existing llama.cpp binary.",
        }));
    }
    match first_run_artifact {
        None => actions.push(json!({
            "area": "first_run",
            "action": "run_native_first_benchmark",
            "message": "Run the native first benchmark after pairing, runtime selection, and model selection are ready.",
        })),
        Some(payload)
            if payload
                .pointer("/upload/uploaded")
                .and_then(Value::as_bool)
                .unwrap_or(false) => {}
        Some(_) => actions.push(json!({
            "area": "upload",
            "action": "retry_upload",
            "message": "A local first-run artifact exists. Retry upload after confirming the machine is paired with Hub.",
        })),
    }
    Value::Array(actions)
}

pub fn redact_support_value(value: Value) -> Value {
    match value {
        Value::String(text) => Value::String(redact_support_text(&text)),
        Value::Array(items) => Value::Array(items.into_iter().map(redact_support_value).collect()),
        Value::Object(entries) => Value::Object(
            entries
                .into_iter()
                .map(|(key, item)| {
                    let normalized_key = key.to_lowercase();
                    let redacted_value = if normalized_key.contains("authorization")
                        || normalized_key == "access_token"
                        || normalized_key == "runner_token"
                        || normalized_key == "upload_token"
                        || normalized_key == "bearer_token"
                        || normalized_key == "pairing_code"
                    {
                        Value::String("[redacted]".to_string())
                    } else {
                        redact_support_value(item)
                    };
                    (key, redacted_value)
                })
                .collect(),
        ),
        other => other,
    }
}

pub fn redact_support_text(text: &str) -> String {
    let mut redact_next = false;
    text.split_whitespace()
        .map(|part| {
            if redact_next {
                redact_next = false;
                return "[redacted]".to_string();
            }
            let lower = part.to_lowercase();
            let upper = part.to_uppercase();
            let embedded_redacted = redact_embedded_support_patterns(part);
            if embedded_redacted != part {
                return embedded_redacted;
            }
            if lower.starts_with("bearer")
                || lower.starts_with("qbhr_")
                || lower.starts_with("igrt_")
                || lower.starts_with("igrp_")
                || lower.starts_with("igrp-")
                || upper.starts_with("IGRP-")
                || lower.contains("authorization:")
            {
                if lower == "bearer"
                    || lower.ends_with("bearer")
                    || lower.contains("authorization:")
                {
                    redact_next = true;
                }
                "[redacted]".to_string()
            } else {
                part.to_string()
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn redact_embedded_support_patterns(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut redacted = String::with_capacity(text.len());
    let mut index = 0;
    while index < bytes.len() {
        let suffix = text[index..].to_lowercase();
        if ["qbhr_", "igrt_", "igrp_", "igrp-"]
            .iter()
            .any(|prefix| suffix.starts_with(prefix))
        {
            redacted.push_str("[redacted]");
            index += sensitive_pattern_len(&bytes[index..]);
            continue;
        }
        let ch = text[index..]
            .chars()
            .next()
            .expect("index is always within string");
        redacted.push(ch);
        index += ch.len_utf8();
    }
    redacted
}

fn sensitive_pattern_len(bytes: &[u8]) -> usize {
    bytes
        .iter()
        .take_while(|byte| byte.is_ascii_alphanumeric() || **byte == b'_' || **byte == b'-')
        .count()
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
    for key in ["channel", "backend", "rollback_runtime_id"] {
        if entry
            .get(key)
            .and_then(Value::as_str)
            .unwrap_or("")
            .trim()
            .is_empty()
        {
            return Err(format!("{key} is required"));
        }
    }
    if !entry.get("upstream").is_some_and(Value::is_object) {
        return Err("upstream metadata is required".to_string());
    }
    if !entry.get("platform").is_some_and(Value::is_object) {
        return Err("platform metadata is required".to_string());
    }
    let archive_url = entry
        .pointer("/archive/url")
        .and_then(Value::as_str)
        .or_else(|| entry.get("archive_url").and_then(Value::as_str))
        .unwrap_or("")
        .trim();
    let url = Url::parse(archive_url).map_err(|_| "archive.url must be a valid HTTPS URL")?;
    if url.scheme() != "https" {
        return Err("archive.url must use HTTPS".to_string());
    }
    let signature_url = entry
        .pointer("/archive/signature_url")
        .and_then(Value::as_str)
        .or_else(|| entry.get("signature_url").and_then(Value::as_str))
        .unwrap_or("")
        .trim();
    if !signature_url.is_empty() {
        let url = Url::parse(signature_url)
            .map_err(|_| "archive.signature_url must be a valid HTTPS URL")?;
        if url.scheme() != "https" {
            return Err("archive.signature_url must use HTTPS".to_string());
        }
    }
    let sha256 = entry
        .pointer("/archive/sha256")
        .and_then(Value::as_str)
        .or_else(|| entry.get("sha256").and_then(Value::as_str))
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
    Ok(())
}

#[derive(Debug, Clone)]
pub struct ManagedRuntimeInstallOptions {
    pub runtime_id: Option<String>,
    pub archive_bytes: Option<Vec<u8>>,
}

fn managed_llama_cpp_runtime_entry(runtime_id: Option<&str>) -> Result<Value, String> {
    let manifest = managed_llama_cpp_runtime_manifest();
    let runtimes = manifest["runtimes"]
        .as_array()
        .ok_or_else(|| "managed runtime manifest is missing runtimes".to_string())?;
    let runtime_id = runtime_id.unwrap_or(MANAGED_LLAMA_CPP_MACOS_METAL_RUNTIME_ID);
    runtimes
        .iter()
        .find(|entry| entry["runtime_id"].as_str() == Some(runtime_id))
        .cloned()
        .ok_or_else(|| format!("unknown managed llama.cpp runtime: {runtime_id}"))
}

fn sha256_hex(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn managed_runtime_install_root(runtime_id: &str) -> Result<PathBuf, String> {
    Ok(runtime_cache_root()?
        .join("llama.cpp")
        .join("managed")
        .join(runtime_id))
}

fn runtime_archive_url(entry: &Value) -> Result<&str, String> {
    entry
        .pointer("/archive/url")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "managed runtime manifest is missing archive.url".to_string())
}

fn runtime_archive_sha256(entry: &Value) -> Result<&str, String> {
    entry
        .pointer("/archive/sha256")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| "managed runtime manifest is missing archive.sha256".to_string())
}

/// Maximum size we accept when downloading a managed runtime archive.
/// Sized for current macOS Metal builds (~9 MB) plus generous slack for
/// future Linux/Windows lanes; refuses pathologically large URLs that would
/// OOM the host.
pub const MAX_MANAGED_RUNTIME_ARCHIVE_BYTES: u64 = 256 * 1024 * 1024;

fn fetch_runtime_archive(url: &str) -> Result<Vec<u8>, String> {
    let mut response = reqwest::blocking::Client::builder()
        .connect_timeout(std::time::Duration::from_secs(15))
        .timeout(std::time::Duration::from_secs(300))
        .build()
        .map_err(|error| format!("could not initialize runtime downloader: {error}"))?
        .get(url)
        .send()
        .map_err(|error| format!("could not download managed runtime archive: {error}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "managed runtime archive download failed with HTTP {}",
            response.status()
        ));
    }
    if let Some(declared) = response.content_length() {
        if declared > MAX_MANAGED_RUNTIME_ARCHIVE_BYTES {
            return Err(format!(
                "managed runtime archive declares {} bytes, exceeding the {}-byte cap",
                declared, MAX_MANAGED_RUNTIME_ARCHIVE_BYTES
            ));
        }
    }
    let mut bytes: Vec<u8> = Vec::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = response
            .read(&mut buffer)
            .map_err(|error| format!("could not read managed runtime archive: {error}"))?;
        if read == 0 {
            break;
        }
        if (bytes.len() as u64).saturating_add(read as u64) > MAX_MANAGED_RUNTIME_ARCHIVE_BYTES {
            return Err(format!(
                "managed runtime archive exceeded the {}-byte cap during download",
                MAX_MANAGED_RUNTIME_ARCHIVE_BYTES
            ));
        }
        bytes.extend_from_slice(&buffer[..read]);
    }
    Ok(bytes)
}

fn set_executable_if_needed(path: &Path) -> Result<(), String> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut permissions = fs::metadata(path)
            .map_err(|error| format!("could not read `{}` permissions: {error}", path.display()))?
            .permissions();
        permissions.set_mode(permissions.mode() | 0o755);
        fs::set_permissions(path, permissions)
            .map_err(|error| format!("could not mark `{}` executable: {error}", path.display()))?;
    }
    Ok(())
}

fn safe_extract_targz(bytes: &[u8], destination: &Path) -> Result<(), String> {
    fs::create_dir_all(destination).map_err(|error| {
        format!(
            "could not create managed runtime directory `{}`: {error}",
            destination.display()
        )
    })?;
    let decoder = GzDecoder::new(bytes);
    let mut archive = Archive::new(decoder);
    for entry in archive
        .entries()
        .map_err(|error| format!("could not read managed runtime archive: {error}"))?
    {
        let mut entry = entry
            .map_err(|error| format!("could not read managed runtime archive entry: {error}"))?;
        let entry_path = entry
            .path()
            .map_err(|error| format!("could not read managed runtime archive path: {error}"))?;
        let entry_type = entry.header().entry_type();
        // Reject every link form (hard link, symlink, fifo, char/block device,
        // etc.) outright. The managed runtime archives we accept only need
        // regular files and directories. This closes the soundness gap where a
        // symlink-then-write sequence could be redirected through an
        // attacker-controlled link target inside the destination tree.
        if entry_type.is_symlink() || entry_type.is_hard_link() {
            return Err("managed runtime archive contains a link entry".to_string());
        }
        if !entry_type.is_file() && !entry_type.is_dir() {
            return Err(
                "managed runtime archive contains a link or special file entry".to_string(),
            );
        }
        if entry_path.components().any(|component| {
            matches!(
                component,
                std::path::Component::ParentDir
                    | std::path::Component::RootDir
                    | std::path::Component::Prefix(_)
            )
        }) {
            return Err("managed runtime archive contains an unsafe path".to_string());
        }
        let output = destination.join(&entry_path);
        if !output.starts_with(destination) {
            return Err(
                "managed runtime archive attempted to write outside the runtime cache".to_string(),
            );
        }
        if let Some(parent) = output.parent() {
            fs::create_dir_all(parent).map_err(|error| {
                format!(
                    "could not create managed runtime extraction directory `{}`: {error}",
                    parent.display()
                )
            })?;
        }
        entry
            .unpack(&output)
            .map_err(|error| format!("could not extract managed runtime archive: {error}"))?;
    }
    Ok(())
}

fn cleanup_stale_runtime_dir(path: &Path, label: &str) -> Result<(), String> {
    match fs::remove_dir_all(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(error) => Err(format!(
            "could not clean stale managed runtime {label} directory `{}`: {error}",
            path.display()
        )),
    }
}

fn assert_no_symlinks_under(root: &Path) -> Result<(), String> {
    let mut stack = vec![root.to_path_buf()];
    while let Some(path) = stack.pop() {
        let metadata = fs::symlink_metadata(&path).map_err(|error| {
            format!(
                "could not inspect extracted managed runtime path `{}`: {error}",
                path.display()
            )
        })?;
        let file_type = metadata.file_type();
        if file_type.is_symlink() {
            return Err(format!(
                "managed runtime extraction produced a symlink at `{}`",
                path.display()
            ));
        }
        if file_type.is_dir() {
            for entry in fs::read_dir(&path).map_err(|error| {
                format!(
                    "could not scan extracted managed runtime directory `{}`: {error}",
                    path.display()
                )
            })? {
                let entry = entry.map_err(|error| {
                    format!(
                        "could not scan extracted managed runtime directory `{}`: {error}",
                        path.display()
                    )
                })?;
                stack.push(entry.path());
            }
        }
    }
    Ok(())
}

fn find_runtime_binary(root: &Path, binary_name: &str) -> Result<Option<PathBuf>, String> {
    let mut stack = vec![root.to_path_buf()];
    while let Some(path) = stack.pop() {
        let metadata = fs::metadata(&path).map_err(|error| {
            format!(
                "could not inspect extracted runtime path `{}`: {error}",
                path.display()
            )
        })?;
        if metadata.is_dir() {
            for entry in fs::read_dir(&path)
                .map_err(|error| format!("could not scan `{}`: {error}", path.display()))?
            {
                stack.push(
                    entry
                        .map_err(|error| format!("could not scan `{}`: {error}", path.display()))?
                        .path(),
                );
            }
        } else if path
            .file_name()
            .and_then(|name| name.to_str())
            .map(|name| {
                name == binary_name || (cfg!(windows) && name == format!("{binary_name}.exe"))
            })
            .unwrap_or(false)
            && fs::symlink_metadata(&path)
                .map(|metadata| metadata.file_type().is_file())
                .unwrap_or(false)
        {
            return Ok(Some(path));
        }
    }
    Ok(None)
}

fn smoke_runtime_binary(path: &Path) -> Result<String, String> {
    let output = StdCommand::new(path)
        .arg("--version")
        .output()
        .map_err(|error| format!("could not run managed llama.cpp version smoke: {error}"))?;
    if !output.status.success() {
        return Err(format!(
            "managed llama.cpp version smoke failed with exit code {:?}",
            output.status.code()
        ));
    }
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if !stdout.is_empty() {
        return Ok(stdout);
    }
    Ok(String::from_utf8_lossy(&output.stderr).trim().to_string())
}

pub fn install_managed_llama_cpp_runtime(
    options: ManagedRuntimeInstallOptions,
) -> Result<Value, String> {
    let entry = managed_llama_cpp_runtime_entry(options.runtime_id.as_deref())?;
    install_managed_llama_cpp_runtime_from_manifest_entry(entry, options)
}

fn managed_runtime_root_for_selection(selection: &Value) -> Result<Option<PathBuf>, String> {
    if selection.get("source").and_then(Value::as_str) != Some("managed_download") {
        return Ok(None);
    }
    let runtime_id = selection
        .get("runtime_id")
        .and_then(Value::as_str)
        .ok_or_else(|| "managed runtime selection is missing runtime_id".to_string())?;
    let runtime_id = safe_runtime_id(Some(runtime_id))?;
    managed_runtime_install_root(&runtime_id).map(Some)
}

pub fn remove_selected_llama_cpp_runtime(remove_managed_files: bool) -> Result<Value, String> {
    let selected_path = selected_llama_cpp_runtime_path()?;
    let selected_text = match fs::read_to_string(&selected_path) {
        Ok(text) => Some(text),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => {
            return Err(format!(
                "could not read selected runtime `{}`: {error}",
                selected_path.display()
            ))
        }
    };
    let selection = selected_text
        .as_deref()
        .map(|text| {
            serde_json::from_str::<Value>(text)
                .map_err(|error| format!("could not parse selected runtime: {error}"))
        })
        .transpose()?;
    let managed_root = selection
        .as_ref()
        .and_then(|value| managed_runtime_root_for_selection(value).transpose())
        .transpose()?;
    let removed_selection = match fs::remove_file(&selected_path) {
        Ok(()) => true,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
        Err(error) => {
            return Err(format!(
                "could not remove selected runtime `{}`: {error}",
                selected_path.display()
            ))
        }
    };
    let removed_managed_files = if remove_managed_files {
        match managed_root.as_ref() {
            Some(root) => match fs::remove_dir_all(root) {
                Ok(()) => true,
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => false,
                Err(error) => {
                    return Err(format!(
                        "could not remove managed runtime files `{}`: {error}",
                        root.display()
                    ))
                }
            },
            None => false,
        }
    } else {
        false
    };
    let selected_source = selection
        .as_ref()
        .and_then(|value| value.get("source"))
        .and_then(Value::as_str)
        .unwrap_or("not_selected");
    Ok(json!({
        "status": if removed_selection || removed_managed_files { "removed" } else { "not_selected" },
        "removed_selection": removed_selection,
        "removed_managed_files": removed_managed_files,
        "selected_runtime_path": selected_path.display().to_string(),
        "managed_runtime_root": managed_root.map(|path| path.display().to_string()),
        "selected_source": selected_source,
        "message": if removed_selection || removed_managed_files {
            "Selected llama.cpp runtime cleared. Install the managed runtime again or select a runnable local binary before native first-run."
        } else {
            "No selected llama.cpp runtime was recorded. Install or select a runtime before native first-run."
        },
        "next_actions": [
            "install_managed_runtime",
            "select_existing_runtime"
        ],
    }))
}

pub fn install_managed_llama_cpp_runtime_from_manifest_entry(
    entry: Value,
    options: ManagedRuntimeInstallOptions,
) -> Result<Value, String> {
    verify_runtime_download_manifest(&entry)?;
    let runtime_id = entry["runtime_id"]
        .as_str()
        .ok_or_else(|| "managed runtime id missing".to_string())?;
    if entry["download"]["requires_explicit_user_action"] != true {
        return Err("managed runtime install requires explicit user action".to_string());
    }
    let archive_url = runtime_archive_url(&entry)?;
    let expected_sha256 = runtime_archive_sha256(&entry)?;
    let bytes = match options.archive_bytes {
        Some(bytes) => bytes,
        None => fetch_runtime_archive(archive_url)?,
    };
    let actual_sha256 = sha256_hex(&bytes);
    if actual_sha256 != expected_sha256 {
        return Err(format!(
            "managed runtime checksum mismatch: expected {expected_sha256}, got {actual_sha256}"
        ));
    }

    let install_root = managed_runtime_install_root(runtime_id)?;
    let staging_root = install_root.with_extension(format!("staging-{}", std::process::id()));
    let previous_root = install_root.with_extension(format!("previous-{}", std::process::id()));
    cleanup_stale_runtime_dir(&staging_root, "staging")?;
    cleanup_stale_runtime_dir(&previous_root, "rollback")?;
    safe_extract_targz(&bytes, &staging_root)?;
    assert_no_symlinks_under(&staging_root)?;

    let cli_name = entry
        .pointer("/binary_names/cli")
        .and_then(Value::as_str)
        .unwrap_or("llama-cli");
    let server_name = entry
        .pointer("/binary_names/server")
        .and_then(Value::as_str)
        .unwrap_or("llama-server");
    let perplexity_name = entry
        .pointer("/binary_names/perplexity")
        .and_then(Value::as_str)
        .unwrap_or("llama-perplexity");
    let expected_binaries = entry["expected_binaries"]
        .as_array()
        .ok_or_else(|| "managed runtime manifest is missing expected_binaries".to_string())?;
    let cli = find_runtime_binary(&staging_root, cli_name)?
        .ok_or_else(|| "managed runtime archive did not contain llama-cli".to_string())?;
    let server = find_runtime_binary(&staging_root, server_name)?;
    let perplexity = find_runtime_binary(&staging_root, perplexity_name)?;
    for expected in expected_binaries {
        let Some(name) = expected.as_str() else {
            return Err("expected_binaries must contain only binary names".to_string());
        };
        let found = if name == cli_name {
            Some(cli.clone())
        } else if name == server_name {
            server.clone()
        } else if name == perplexity_name {
            perplexity.clone()
        } else {
            find_runtime_binary(&staging_root, name)?
        };
        if found.is_none() {
            return Err(format!(
                "managed runtime archive did not contain expected binary `{name}`"
            ));
        }
    }
    set_executable_if_needed(&cli)?;
    let version_output = smoke_runtime_binary(&cli)?;

    if install_root.exists() {
        fs::rename(&install_root, &previous_root).map_err(|error| {
            format!(
                "could not prepare rollback for managed runtime `{}`: {error}",
                install_root.display()
            )
        })?;
    }
    if let Err(error) = fs::rename(&staging_root, &install_root) {
        if previous_root.exists() {
            let _ = fs::rename(&previous_root, &install_root);
        }
        return Err(format!("could not activate managed runtime: {error}"));
    }
    let installed_cli = install_root.join(
        cli.strip_prefix(&staging_root)
            .map_err(|error| format!("could not resolve installed llama-cli path: {error}"))?,
    );
    let installed_server = server.and_then(|path| {
        path.strip_prefix(&staging_root)
            .ok()
            .map(|relative| install_root.join(relative).display().to_string())
    });
    let installed_perplexity = perplexity.and_then(|path| {
        path.strip_prefix(&staging_root)
            .ok()
            .map(|relative| install_root.join(relative).display().to_string())
    });
    let selection = json!({
        "runtime_id": runtime_id,
        "backend": "llama.cpp",
        "version_label": entry["version_label"].clone(),
        "source": "managed_download",
        "channel": entry["channel"].clone(),
        "provenance": entry["provenance"].clone(),
        "manifest_version": RUNTIME_MANIFEST_VERSION,
        "upstream": entry["upstream"].clone(),
        "archive": {
            "url": archive_url,
            "sha256": expected_sha256,
            "checksum_verified": true,
            "independent_signature_verified": false,
        },
        "binaries": {
            "cli": installed_cli.display().to_string(),
            "server": installed_server,
            "perplexity": installed_perplexity,
        },
        "version_smoke": {
            "command": "--version",
            "output": version_output,
        },
        "selected_at_platform": {
            "system": env::consts::OS,
            "machine": env::consts::ARCH,
        },
    });
    let selected_path = match write_selected_llama_cpp_runtime(&selection) {
        Ok(path) => path,
        Err(error) => {
            restore_previous_runtime_root(&install_root, &previous_root);
            return Err(error);
        }
    };
    let _ = fs::remove_dir_all(&previous_root);

    Ok(json!({
        "status": "selected",
        "selection": selection,
        "path": selected_path.display().to_string(),
        "install_root": install_root.display().to_string(),
        "message": "Managed llama.cpp runtime installed and selected. The archive checksum was verified; no independent signature was verified.",
    }))
}

fn restore_previous_runtime_root(install_root: &Path, previous_root: &Path) {
    let _ = fs::remove_dir_all(install_root);
    if previous_root.exists() {
        let _ = fs::rename(previous_root, install_root);
    }
}

fn write_selected_llama_cpp_runtime(selection: &Value) -> Result<PathBuf, String> {
    let selected_path = selected_llama_cpp_runtime_path()?;
    fs::create_dir_all(selected_path.parent().ok_or_else(|| {
        format!(
            "could not resolve selected runtime directory for `{}`",
            selected_path.display()
        )
    })?)
    .map_err(|error| format!("could not create selected runtime directory: {error}"))?;
    let body = serde_json::to_string_pretty(selection)
        .map_err(|error| format!("could not serialize selected runtime: {error}"))?;
    let temp_path = selected_path.with_extension(format!("json.tmp-{}", std::process::id()));
    fs::write(&temp_path, format!("{body}\n"))
        .map_err(|error| format!("could not write selected runtime: {error}"))?;
    fs::rename(&temp_path, &selected_path)
        .map_err(|error| format!("could not activate selected runtime: {error}"))?;
    Ok(selected_path)
}

#[cfg(test)]
mod tests {
    use super::*;
    use flate2::write::GzEncoder;
    use flate2::Compression;
    use std::io::Write;
    use std::sync::{Mutex, OnceLock};
    use tar::{Builder, Header};

    fn env_test_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    fn write_test_llama_binary(path: &Path, binary_label: &str) {
        #[cfg(windows)]
        fs::write(
            path,
            format!("@echo off\r\necho {binary_label} version 0.0-test\r\n"),
        )
        .expect("test llama binary");
        #[cfg(not(windows))]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::write(
                path,
                format!("#!/bin/sh\necho '{binary_label} version 0.0-test'\n"),
            )
            .expect("test llama binary");
            let mut permissions = fs::metadata(path)
                .expect("test binary metadata")
                .permissions();
            permissions.set_mode(0o755);
            fs::set_permissions(path, permissions).expect("test binary executable");
        }
    }

    fn test_runtime_manifest_entry(archive_bytes: &[u8]) -> Value {
        json!({
            "runtime_id": "llama-cpp-managed-test",
            "channel": "infergrade_stable",
            "backend": "llama.cpp",
            "version_label": "llama.cpp managed test",
            "upstream": {
                "project": "ggml-org/llama.cpp",
                "tag": "test"
            },
            "platform": {
                "system": env::consts::OS,
                "arch": env::consts::ARCH
            },
            "archive": {
                "url": "https://downloads.infergrade.test/llama-cpp-managed-test.tar.gz",
                "sha256": sha256_hex(archive_bytes),
                "signature_url": Value::Null
            },
            "download": {
                "requires_explicit_user_action": true
            },
            "expected_binaries": ["llama-cli", "llama-server", "llama-perplexity"],
            "binary_names": {
                "cli": "llama-cli",
                "server": "llama-server",
                "perplexity": "llama-perplexity"
            },
            "rollback_runtime_id": LLAMA_CPP_RUNTIME_ID,
            "provenance": "Test archive with checksum verification only.",
        })
    }

    fn append_tar_file(
        builder: &mut Builder<GzEncoder<Vec<u8>>>,
        path: &str,
        body: &[u8],
        mode: u32,
    ) {
        let mut header = Header::new_gnu();
        header.set_size(body.len() as u64);
        header.set_mode(mode);
        header.set_cksum();
        builder
            .append_data(&mut header, path, body)
            .expect("append test archive file");
    }

    fn test_runtime_archive() -> Vec<u8> {
        let encoder = GzEncoder::new(Vec::new(), Compression::default());
        let mut builder = Builder::new(encoder);
        append_tar_file(
            &mut builder,
            "llama-test/bin/llama-cli",
            b"#!/bin/sh\necho 'llama-cli version managed-test'\n",
            0o755,
        );
        append_tar_file(
            &mut builder,
            "llama-test/bin/llama-server",
            b"#!/bin/sh\necho 'llama-server version managed-test'\n",
            0o755,
        );
        append_tar_file(
            &mut builder,
            "llama-test/bin/llama-perplexity",
            b"#!/bin/sh\necho 'llama-perplexity version managed-test'\n",
            0o755,
        );
        let encoder = builder.into_inner().expect("finish tar");
        encoder.finish().expect("finish gzip")
    }

    fn test_runtime_archive_without_perplexity() -> Vec<u8> {
        let encoder = GzEncoder::new(Vec::new(), Compression::default());
        let mut builder = Builder::new(encoder);
        append_tar_file(
            &mut builder,
            "llama-test/bin/llama-cli",
            b"#!/bin/sh\necho 'llama-cli version managed-test'\n",
            0o755,
        );
        append_tar_file(
            &mut builder,
            "llama-test/bin/llama-server",
            b"#!/bin/sh\necho 'llama-server version managed-test'\n",
            0o755,
        );
        let encoder = builder.into_inner().expect("finish tar");
        encoder.finish().expect("finish gzip")
    }

    fn symlink_runtime_archive() -> Vec<u8> {
        let encoder = GzEncoder::new(Vec::new(), Compression::default());
        let mut builder = Builder::new(encoder);
        let mut header = Header::new_gnu();
        header.set_entry_type(tar::EntryType::Symlink);
        header.set_size(0);
        header.set_mode(0o777);
        header.set_cksum();
        builder
            .append_link(
                &mut header,
                "llama-test/bin/llama-cli",
                "/tmp/outside-llama-cli",
            )
            .expect("append symlink");
        let encoder = builder.into_inner().expect("finish tar");
        encoder.finish().expect("finish gzip")
    }

    fn unsafe_runtime_archive() -> Vec<u8> {
        fn write_octal(field: &mut [u8], value: u64) {
            for byte in field.iter_mut() {
                *byte = b'0';
            }
            let text = format!("{value:o}");
            let start = field.len().saturating_sub(text.len() + 1);
            field[start..start + text.len()].copy_from_slice(text.as_bytes());
            field[field.len() - 1] = 0;
        }

        let body = b"escape";
        let mut tar_bytes = Vec::new();
        let mut header = [0u8; 512];
        header[..16].copy_from_slice(b"../outside-cache");
        write_octal(&mut header[100..108], 0o644);
        write_octal(&mut header[108..116], 0);
        write_octal(&mut header[116..124], 0);
        write_octal(&mut header[124..136], body.len() as u64);
        write_octal(&mut header[136..148], 0);
        for byte in &mut header[148..156] {
            *byte = b' ';
        }
        header[156] = b'0';
        header[257..263].copy_from_slice(b"ustar\0");
        header[263..265].copy_from_slice(b"00");
        let checksum: u32 = header.iter().map(|byte| u32::from(*byte)).sum();
        let checksum_text = format!("{checksum:06o}\0 ");
        header[148..156].copy_from_slice(checksum_text.as_bytes());
        tar_bytes.extend_from_slice(&header);
        tar_bytes.extend_from_slice(body);
        let padding = (512 - (body.len() % 512)) % 512;
        tar_bytes.extend(std::iter::repeat_n(0, padding));
        tar_bytes.extend([0u8; 1024]);

        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(&tar_bytes).expect("write unsafe tar");
        encoder.finish().expect("finish gzip")
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
            "channel": "infergrade_stable",
            "backend": "llama.cpp",
            "upstream": {"tag": "b0000"},
            "platform": {"system": "macos", "arch": "aarch64"},
            "archive": {
                "url": "https://downloads.infergrade.com/runtimes/llama-cpp-metal-2026-05.tar.zst",
                "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "signature_url": "https://downloads.infergrade.com/runtimes/llama-cpp-metal-2026-05.tar.zst.minisig",
            },
            "expected_binaries": ["llama-cli", "llama-server", "llama-perplexity"],
            "rollback_runtime_id": "llama-cpp-homebrew-stable-2026-04",
        });
        assert!(verify_runtime_download_manifest(&valid).is_ok());

        let mut insecure = valid.clone();
        insecure["archive"]["url"] =
            Value::String("http://example.com/runtime.tar.zst".to_string());
        assert!(verify_runtime_download_manifest(&insecure)
            .expect_err("insecure runtime url rejected")
            .contains("HTTPS"));

        let mut missing_checksum = valid.clone();
        missing_checksum["archive"]["sha256"] = Value::String("abc".to_string());
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
    fn managed_runtime_manifest_lists_checksum_verified_macos_metal_lane_with_explicit_download() {
        let manifest = managed_llama_cpp_runtime_manifest();
        assert_eq!(manifest["runtime_family"], "llama.cpp");
        assert_eq!(manifest["manifest_version"], RUNTIME_MANIFEST_VERSION);
        assert_eq!(manifest["channels"]["runtime_family"], "llama.cpp");
        let runtimes = manifest["runtimes"].as_array().expect("runtime entries");
        let macos = runtimes
            .iter()
            .find(|entry| entry["runtime_id"] == "llama-cpp-b9050-macos-arm64-metal")
            .expect("macOS Metal entry");
        assert_eq!(macos["channel"], "infergrade_stable");
        assert_eq!(macos["backend"], "llama.cpp");
        assert_eq!(macos["accelerator"], "metal");
        assert_eq!(macos["platform"]["system"], "macos");
        assert_eq!(macos["platform"]["arch"], "aarch64");
        assert_eq!(macos["upstream"]["tag"], "b9050");
        assert_eq!(
            macos["archive"]["url"],
            "https://github.com/ggml-org/llama.cpp/releases/download/b9050/llama-b9050-bin-macos-arm64.tar.gz"
        );
        assert_eq!(
            macos["archive"]["sha256"],
            "d334fa44e42a143ec6e49924f9630136c0b5fedc5a615508636ba9c8d08eb5d3"
        );
        assert_eq!(macos["download"]["enabled"], true);
        assert_eq!(macos["download"]["requires_explicit_user_action"], true);
        assert!(macos["download"]["message"]
            .as_str()
            .unwrap_or("")
            .contains("explicit user action"));
        assert_eq!(macos["verification"]["independent_signature"], false);
        assert_eq!(macos["expected_binaries"][0], "llama-cli");
        assert_eq!(
            macos["rollback_runtime_id"],
            "llama-cpp-homebrew-stable-2026-04"
        );
        assert!(verify_runtime_download_manifest(macos).is_ok());
    }

    #[test]
    fn managed_runtime_channels_describe_manual_update_policy() {
        let channels = managed_llama_cpp_runtime_channels();
        assert_eq!(channels["runtime_family"], "llama.cpp");
        let entries = channels["channels"].as_array().expect("channel entries");
        let stable = entries
            .iter()
            .find(|entry| entry["channel"] == "infergrade_stable")
            .expect("stable channel");
        assert_eq!(stable["default"], true);
        assert_eq!(stable["managed_by_infergrade"], true);
        assert_eq!(stable["install_policy"], "explicit_only");
        assert_eq!(stable["update_policy"], "manual_only");

        let local = entries
            .iter()
            .find(|entry| entry["channel"] == "local_binary")
            .expect("local binary channel");
        assert_eq!(local["managed_by_infergrade"], false);
        assert_eq!(local["update_policy"], "not_managed");
        assert!(local["provenance_expectation"]
            .as_str()
            .unwrap_or("")
            .contains("User-selected"));
    }

    #[test]
    fn managed_runtime_install_verifies_checksum_extracts_and_selects_runtime() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-managed-install-{}",
            std::process::id()
        ));
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        let archive = test_runtime_archive();
        let entry = test_runtime_manifest_entry(&archive);

        let result = install_managed_llama_cpp_runtime_from_manifest_entry(
            entry,
            ManagedRuntimeInstallOptions {
                runtime_id: None,
                archive_bytes: Some(archive),
            },
        )
        .expect("managed runtime install");

        assert_eq!(result["status"], "selected");
        assert_eq!(result["selection"]["source"], "managed_download");
        assert_eq!(result["selection"]["archive"]["checksum_verified"], true);
        assert_eq!(
            result["selection"]["archive"]["independent_signature_verified"],
            false
        );
        let cli = result["selection"]["binaries"]["cli"]
            .as_str()
            .expect("selected cli path");
        assert!(Path::new(cli).is_file());
        assert!(result["selection"]["version_smoke"]["output"]
            .as_str()
            .unwrap_or("")
            .contains("managed-test"));

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn managed_runtime_install_rejects_checksum_mismatch_before_extracting() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-managed-checksum-{}",
            std::process::id()
        ));
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        let archive = test_runtime_archive();
        let mut entry = test_runtime_manifest_entry(&archive);
        entry["archive"]["sha256"] = Value::String(
            "0000000000000000000000000000000000000000000000000000000000000000".to_string(),
        );

        let error = install_managed_llama_cpp_runtime_from_manifest_entry(
            entry,
            ManagedRuntimeInstallOptions {
                runtime_id: None,
                archive_bytes: Some(archive),
            },
        )
        .expect_err("checksum mismatch rejected");

        assert!(error.contains("checksum mismatch"));
        assert!(!runtime_cache_dir.join("llama.cpp").join("managed").exists());

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn managed_runtime_install_rejects_path_traversal_archive() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-managed-traversal-{}",
            std::process::id()
        ));
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        let archive = unsafe_runtime_archive();
        let entry = test_runtime_manifest_entry(&archive);

        let error = install_managed_llama_cpp_runtime_from_manifest_entry(
            entry,
            ManagedRuntimeInstallOptions {
                runtime_id: None,
                archive_bytes: Some(archive),
            },
        )
        .expect_err("path traversal rejected");

        assert!(error.contains("unsafe path") || error.contains("outside the runtime cache"));

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn managed_runtime_install_rejects_link_entries() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-managed-link-{}",
            std::process::id()
        ));
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        let archive = symlink_runtime_archive();
        let entry = test_runtime_manifest_entry(&archive);

        let error = install_managed_llama_cpp_runtime_from_manifest_entry(
            entry,
            ManagedRuntimeInstallOptions {
                runtime_id: None,
                archive_bytes: Some(archive),
            },
        )
        .expect_err("link entry rejected");

        assert!(
            error.contains("link entry")
                || error.contains("unsafe symlink target")
                || error.contains("link or special file")
        );

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn managed_runtime_install_requires_declared_expected_binaries() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-managed-missing-binary-{}",
            std::process::id()
        ));
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        let archive = test_runtime_archive_without_perplexity();
        let entry = test_runtime_manifest_entry(&archive);

        let error = install_managed_llama_cpp_runtime_from_manifest_entry(
            entry,
            ManagedRuntimeInstallOptions {
                runtime_id: None,
                archive_bytes: Some(archive),
            },
        )
        .expect_err("missing expected binary rejected");

        assert!(error.contains("llama-perplexity"));

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn managed_runtime_install_restores_previous_root_when_selection_write_fails() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-managed-rollback-{}",
            std::process::id()
        ));
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        let archive = test_runtime_archive();
        let entry = test_runtime_manifest_entry(&archive);
        let install_root =
            managed_runtime_install_root("llama-cpp-managed-test").expect("install root");
        fs::create_dir_all(&install_root).expect("existing install root");
        fs::write(install_root.join("old-runtime-marker"), "old").expect("old marker");
        let selected_path = selected_llama_cpp_runtime_path().expect("selected path");
        fs::create_dir_all(&selected_path).expect("directory blocks selection file");

        let error = install_managed_llama_cpp_runtime_from_manifest_entry(
            entry,
            ManagedRuntimeInstallOptions {
                runtime_id: None,
                archive_bytes: Some(archive),
            },
        )
        .expect_err("selection write failure rejected");

        assert!(error.contains("selected runtime"));
        assert!(install_root.join("old-runtime-marker").is_file());

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn runtime_status_reports_stale_selected_runtime_without_treating_it_as_available() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-stale-runtime-cache-{}",
            std::process::id()
        ));
        let missing_runtime = runtime_cache_dir.join("missing-llama-cli");
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        let selected_path = selected_llama_cpp_runtime_path().expect("selected path");
        fs::create_dir_all(selected_path.parent().expect("selected parent"))
            .expect("runtime cache dir");
        fs::write(
            &selected_path,
            serde_json::to_string_pretty(&json!({
                "runtime_id": "llama-cpp-stale-test",
                "source": "selected_existing",
                "binaries": {"cli": missing_runtime.display().to_string()}
            }))
            .expect("selection json"),
        )
        .expect("selected runtime");

        let status = llama_cpp_runtime_status();

        assert_eq!(status["selected_runtime"]["status"], "stale");
        assert_eq!(status["native_runtime_status"], "missing");
        assert_eq!(status["selected_channel"]["channel"], "local_binary");
        assert!(status["recovery"]["message"]
            .as_str()
            .unwrap_or("")
            .contains("Select a valid runtime"));

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn runtime_status_does_not_call_unselected_runtime_local_binary() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-unselected-runtime-cache-{}",
            std::process::id()
        ));
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);

        let status = llama_cpp_runtime_status();

        assert_eq!(status["selected_runtime"]["status"], "not_selected");
        assert_eq!(status["selected_channel"]["channel"], "not_selected");
        assert_eq!(
            status["selected_channel"]["update_policy"],
            "not_applicable"
        );
        assert_ne!(status["selected_channel"]["channel"], "local_binary");

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn support_summary_preserves_recovery_hints_without_secrets() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-support-cache-{}",
            std::process::id()
        ));
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        let first_run = json!({
            "result": {
                "status": "completed",
                "evidence_kind": "native_first_run"
            },
            "artifact": {
                "path": "/tmp/qbhr_path_secret/native-first-run-result.json"
            },
            "bundle_artifact": {
                "path": "/tmp/infergrade/IGRP-8421-bundle.json"
            },
            "upload": {
                "uploaded": false,
                "reason": "Bearer qbhr_reason_secret",
                "run_id": "qbhr_run_secret",
                "bundle_id": "igrp_bundle_secret",
                "server": {
                    "authorization": "Bearer qbhr_secret_token",
                    "echo": "qbhr_secret_token"
                }
            }
        });

        let summary = build_support_summary(
            Some("0.2.4-test"),
            json!({
                "profile": {"status": "present"},
                "token": {"status": "present"},
                "access_token": "qbhr_secret_token"
            }),
            Some(first_run),
            &[
                "Authorization: Bearer qbhr_secret_token".to_string(),
                "pairing failed for code IGRP-8421".to_string(),
            ],
        );

        assert_eq!(
            summary["export_kind"],
            "infergrade_runner_support_summary_v1"
        );
        assert_eq!(summary["secrets_excluded"], true);
        assert_eq!(summary["app_version"], "0.2.4-test");
        assert_eq!(
            summary["runtime"]["selected_channel"]["channel"],
            "not_selected"
        );
        assert_eq!(summary["pairing"]["access_token"], "[redacted]");
        assert_eq!(
            summary["first_run"]["upload_status"],
            "not_uploaded_or_failed"
        );
        assert_eq!(
            summary["first_run"]["upload_reason"],
            "[redacted] [redacted]"
        );
        assert_eq!(summary["first_run"]["run_id"], "[redacted]");
        assert_eq!(summary["first_run"]["bundle_id"], "[redacted]");
        assert!(!summary["first_run"]["artifact_path"]
            .as_str()
            .expect("artifact path")
            .contains("qbhr_path_secret"));
        assert!(!summary["first_run"]["bundle_artifact_path"]
            .as_str()
            .expect("bundle artifact path")
            .contains("IGRP-8421"));
        assert!(summary["next_actions"]
            .as_array()
            .expect("next actions")
            .iter()
            .any(|action| action["action"] == "retry_upload"));
        let rendered = serde_json::to_string(&summary).expect("summary JSON");
        assert!(!rendered.contains("qbhr_secret_token"));
        assert!(!rendered.contains("qbhr_reason_secret"));
        assert!(!rendered.contains("qbhr_run_secret"));
        assert!(!rendered.contains("igrp_bundle_secret"));
        assert!(!rendered.contains("qbhr_path_secret"));
        assert!(!rendered.contains("IGRP-8421"));
        assert!(!rendered.contains("Bearer qbhr"));

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
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
                MANAGED_LLAMA_CPP_MACOS_METAL_RUNTIME_ID
            );
            assert_eq!(plan["recommended_runtime"]["accelerator"], "metal");
        }
    }

    #[test]
    fn selects_existing_llama_cpp_runtime_from_explicit_path_without_installing() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-runtime-cache-{}",
            std::process::id()
        ));
        let runtime_path = env::temp_dir().join(format!(
            "infergrade-runner-engine-llama-cli-{}{}",
            std::process::id(),
            if cfg!(windows) { ".cmd" } else { "" }
        ));
        write_test_llama_binary(&runtime_path, "llama-cli");
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);

        let selection = select_existing_llama_cpp_runtime(
            Some("llama-cpp-selected-test"),
            Some(runtime_path.clone()),
            None,
            None,
        )
        .expect("runtime selection");

        assert_eq!(selection["status"], "selected");
        assert_eq!(
            selection["selection"]["runtime_id"],
            "llama-cpp-selected-test"
        );
        assert_eq!(selection["selection"]["source"], "selected_existing");
        assert_eq!(selection["selection"]["channel"], "local_binary");
        assert!(selection["message"]
            .as_str()
            .unwrap_or("")
            .contains("No download or install command was run"));
        let selected = load_selected_llama_cpp_runtime();
        assert_eq!(selected["status"], "selected");
        assert_eq!(
            selected["selection"]["binaries"]["cli"],
            fs::canonicalize(&runtime_path)
                .expect("canonical runtime path")
                .display()
                .to_string()
        );
        let plan = llama_cpp_runtime_plan(selected);
        assert_eq!(plan["native_runtime_status"], "available");
        let status = llama_cpp_runtime_status();
        assert_eq!(status["selected_channel"]["channel"], "local_binary");
        assert_eq!(status["selected_channel"]["update_policy"], "not_managed");
        assert_eq!(status["update_policy"]["automatic_updates"], false);

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_file(runtime_path);
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn selected_runtime_rejects_non_executable_or_non_llama_files() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-invalid-runtime-cache-{}",
            std::process::id()
        ));
        let invalid_path = runtime_cache_dir.join("llama-cli");
        fs::create_dir_all(&runtime_cache_dir).expect("runtime cache dir");
        fs::write(&invalid_path, b"not a runnable llama.cpp binary").expect("invalid file");
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);

        let error = select_existing_llama_cpp_runtime(
            Some("llama-cpp-invalid-test"),
            Some(invalid_path),
            None,
            None,
        )
        .expect_err("invalid runtime rejected");

        assert!(
            error.contains("executable")
                || error.contains("execute")
                || error.contains("llama.cpp")
        );
        assert_eq!(load_selected_llama_cpp_runtime()["status"], "not_selected");

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn selected_runtime_rejects_unsafe_runtime_ids() {
        let error = select_existing_llama_cpp_runtime(
            Some("../bad"),
            Some(PathBuf::from("/definitely/missing/llama-cli")),
            None,
            None,
        )
        .expect_err("unsafe runtime id rejected");
        assert!(error.contains("runtime_id"));
    }

    #[test]
    fn removes_selected_managed_runtime_without_touching_local_binary_selections() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-engine-remove-runtime-cache-{}",
            std::process::id()
        ));
        let local_binary = env::temp_dir().join(format!(
            "infergrade-runner-engine-local-binary-{}",
            std::process::id()
        ));
        fs::create_dir_all(&runtime_cache_dir).expect("runtime cache dir");
        fs::write(&local_binary, b"local llama-cli").expect("local runtime binary");
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);

        let local_selection = json!({
            "runtime_id": "llama-cpp-local-test",
            "source": "selected_existing",
            "channel": "local_binary",
            "binaries": {
                "cli": local_binary.display().to_string(),
            },
        });
        write_selected_llama_cpp_runtime(&local_selection).expect("selected local runtime");
        let removed = remove_selected_llama_cpp_runtime(true).expect("local selection removed");
        assert_eq!(removed["removed_selection"], true);
        assert_eq!(removed["removed_managed_files"], false);
        assert!(local_binary.exists());
        assert_eq!(load_selected_llama_cpp_runtime()["status"], "not_selected");

        let managed_root = managed_runtime_install_root(MANAGED_LLAMA_CPP_MACOS_METAL_RUNTIME_ID)
            .expect("managed root");
        fs::create_dir_all(&managed_root).expect("managed runtime root");
        fs::write(managed_root.join("llama-cli"), b"managed llama-cli")
            .expect("managed runtime binary");
        let managed_selection = json!({
            "runtime_id": MANAGED_LLAMA_CPP_MACOS_METAL_RUNTIME_ID,
            "source": "managed_download",
            "channel": "infergrade_stable",
            "binaries": {
                "cli": managed_root.join("llama-cli").display().to_string(),
            },
        });
        write_selected_llama_cpp_runtime(&managed_selection).expect("selected managed runtime");
        let removed = remove_selected_llama_cpp_runtime(true).expect("managed runtime removed");
        assert_eq!(removed["removed_selection"], true);
        assert_eq!(removed["removed_managed_files"], true);
        assert!(!managed_root.exists());
        assert!(removed["message"]
            .as_str()
            .expect("message")
            .contains("Install the managed runtime again"));

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = fs::remove_file(local_binary);
        let _ = fs::remove_dir_all(runtime_cache_dir);
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

    #[test]
    fn container_runtime_readiness_keeps_sandboxes_optional() {
        let readiness = container_runtime_readiness();

        assert_eq!(readiness["docker_required_for_first_run"], false);
        assert!(readiness["runtimes"]["docker"].get("cli").is_some());
        assert!(readiness["runtimes"]["docker"].get("daemon").is_some());
        assert_eq!(
            readiness["runtimes"]["docker"]["capability"],
            "advanced_sandboxed_benchmarks"
        );
        assert_eq!(readiness["runtimes"]["podman"]["first_run_required"], false);
    }
}
