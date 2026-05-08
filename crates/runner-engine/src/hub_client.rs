use crate::{normalize_api_url, worker_protocol::claim_run_job_payload, RunnerError};
use serde_json::{json, Value};
use std::fmt;
use std::sync::OnceLock;
use std::time::Duration;

pub const HUB_CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
pub const HUB_REQUEST_TIMEOUT: Duration = Duration::from_secs(60);
pub const HUB_BUNDLE_UPLOAD_TIMEOUT: Duration = Duration::from_secs(300);

fn build_hub_client(timeout: Duration) -> reqwest::Client {
    reqwest::Client::builder()
        .connect_timeout(HUB_CONNECT_TIMEOUT)
        .timeout(timeout)
        .build()
        .unwrap_or_else(|_| reqwest::Client::new())
}

/// Shared async client for typical Hub JSON requests. Reuses connections and
/// applies sane connect/request timeouts to avoid indefinite hangs on flaky
/// networks.
pub fn shared_hub_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| build_hub_client(HUB_REQUEST_TIMEOUT))
}

/// Shared async client for large bundle uploads. Same connect timeout, longer
/// request timeout to accommodate slow uploads.
pub fn shared_hub_upload_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| build_hub_client(HUB_BUNDLE_UPLOAD_TIMEOUT))
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HubMethod {
    Get,
    Post,
}

impl HubMethod {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Get => "GET",
            Self::Post => "POST",
        }
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct HubJsonRequest {
    pub method: HubMethod,
    pub url: String,
    pub body: Option<Value>,
    bearer_token: Option<String>,
    /// True for large bundle uploads. Set explicitly by the bundle-upload
    /// request builder; controls which shared timeout client is used.
    is_upload: bool,
}

#[derive(Clone, PartialEq)]
pub struct HubJsonResponse {
    pub status: u16,
    pub body: Value,
}

impl fmt::Debug for HubJsonResponse {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HubJsonResponse")
            .field("status", &self.status)
            .field("body", &"[redacted]")
            .finish()
    }
}

impl HubJsonRequest {
    pub fn authorization_header(&self) -> Option<String> {
        self.bearer_token
            .as_deref()
            .map(str::trim)
            .filter(|token| !token.is_empty())
            .map(|token| format!("Bearer {token}"))
    }

    pub fn sanitized_preview(&self) -> Value {
        json!({
            "url": self.url,
            "method": self.method.as_str(),
            "has_authorization": self.authorization_header().is_some(),
            "payload": self.body,
        })
    }
}

impl fmt::Debug for HubJsonRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("HubJsonRequest")
            .field("method", &self.method)
            .field("url", &self.url)
            .field("body", &self.body)
            .field(
                "bearer_token",
                &self.bearer_token.as_ref().map(|_| "[redacted]"),
            )
            .finish()
    }
}

pub fn hub_api_url(api_url: &str, path: &str) -> Result<String, RunnerError> {
    let normalized =
        normalize_api_url(api_url).map_err(|error| RunnerError::new("hub_url_invalid", error))?;
    Ok(format!(
        "{}/{}",
        normalized.trim_end_matches('/'),
        path.trim_start_matches('/')
    ))
}

pub fn build_hub_json_request(
    method: HubMethod,
    api_url: &str,
    path: &str,
    body: Option<Value>,
    bearer_token: Option<&str>,
) -> Result<HubJsonRequest, RunnerError> {
    Ok(HubJsonRequest {
        method,
        url: hub_api_url(api_url, path)?,
        body,
        bearer_token: bearer_token
            .map(str::trim)
            .filter(|token| !token.is_empty())
            .map(str::to_string),
        is_upload: false,
    })
}

fn build_hub_upload_request(
    method: HubMethod,
    api_url: &str,
    path: &str,
    body: Option<Value>,
    bearer_token: Option<&str>,
) -> Result<HubJsonRequest, RunnerError> {
    let mut request = build_hub_json_request(method, api_url, path, body, bearer_token)?;
    request.is_upload = true;
    Ok(request)
}

pub async fn execute_hub_json_request(
    request: &HubJsonRequest,
) -> Result<HubJsonResponse, RunnerError> {
    let client = if request.is_upload {
        shared_hub_upload_client()
    } else {
        shared_hub_client()
    };
    let mut builder = match request.method {
        HubMethod::Get => client.get(&request.url),
        HubMethod::Post => client.post(&request.url),
    };
    if let Some(authorization) = request.authorization_header() {
        builder = builder.header("Authorization", authorization);
    }
    if let Some(body) = &request.body {
        builder = builder.json(body);
    }
    let response = builder.send().await.map_err(|error| {
        RunnerError::new(
            "hub_request_failed",
            format!("Could not reach Hub endpoint: {error}"),
        )
    })?;
    let status = response.status().as_u16();
    let text = response.text().await.map_err(|error| {
        RunnerError::new(
            "hub_request_failed",
            format!("Could not read Hub response: {error}"),
        )
    })?;
    let body = serde_json::from_str::<Value>(&text).unwrap_or_else(|_| json!({"error": text}));
    if !(200..300).contains(&status) {
        let detail = response_detail(&body, request.bearer_token.as_deref());
        return Err(RunnerError::new(
            "hub_request_failed",
            format!("Hub request failed with HTTP {status}: {detail}"),
        ));
    }
    Ok(HubJsonResponse { status, body })
}

pub fn build_run_bundle_upload_request(
    api_url: &str,
    run_id: &str,
    bundle_payload: Value,
    bearer_token: Option<&str>,
) -> Result<HubJsonRequest, RunnerError> {
    let run_id = validate_hub_path_id(run_id, "run_id")?;
    validate_bundle_upload_payload(&bundle_payload)?;
    build_hub_upload_request(
        HubMethod::Post,
        api_url,
        &format!("/v1/runs/{run_id}/bundle"),
        Some(bundle_payload),
        bearer_token,
    )
}

pub fn build_run_claim_request(
    api_url: &str,
    run_id: &str,
    worker_id: &str,
    execution_mode: &str,
    bearer_token: Option<&str>,
) -> Result<HubJsonRequest, RunnerError> {
    let run_id = validate_hub_path_id(run_id, "run_id")?;
    let worker_id = validate_hub_path_id(worker_id, "worker_id")?;
    let execution_mode = execution_mode.trim();
    if execution_mode.is_empty() {
        return Err(RunnerError::new(
            "hub_execution_mode_invalid",
            "execution_mode is required to claim a Hub run.",
        ));
    }
    build_hub_json_request(
        HubMethod::Post,
        api_url,
        "/v1/runs/claim",
        Some(claim_run_job_payload(
            &worker_id,
            execution_mode,
            Some(&run_id),
            None,
            None,
        )),
        bearer_token,
    )
}

pub fn build_run_completion_request(
    api_url: &str,
    run_id: &str,
    worker_id: &str,
    bundle_id: &str,
    upload_response: Option<Value>,
    bearer_token: Option<&str>,
) -> Result<HubJsonRequest, RunnerError> {
    let run_id = validate_hub_path_id(run_id, "run_id")?;
    let worker_id = validate_hub_path_id(worker_id, "worker_id")?;
    let bundle_id = validate_hub_path_id(bundle_id, "bundle_id")?;
    build_hub_json_request(
        HubMethod::Post,
        api_url,
        &format!("/v1/runs/{run_id}/complete"),
        Some(json!({
            "worker_id": worker_id,
            "bundle_id": bundle_id,
            "upload": upload_response,
        })),
        bearer_token,
    )
}

fn validate_bundle_upload_payload(payload: &Value) -> Result<(), RunnerError> {
    let Some(object) = payload.as_object() else {
        return Err(RunnerError::new(
            "hub_bundle_payload_invalid",
            "Bundle upload payload must be a JSON object.",
        ));
    };
    if !object.get("manifest").is_some_and(Value::is_object) {
        return Err(RunnerError::new(
            "hub_bundle_payload_invalid",
            "Bundle upload payload is missing a manifest object.",
        ));
    }
    if !object.get("results").is_some_and(Value::is_array) {
        return Err(RunnerError::new(
            "hub_bundle_payload_invalid",
            "Bundle upload payload is missing a results array.",
        ));
    }
    Ok(())
}

/// Validate a string before interpolating it into a Hub URL path fragment.
/// Rejects whitespace, `/`, `?`, `#`, `.`/`..`, empty strings, and overlong
/// values. Used for run/runner/bundle ids and any other identifier the runner
/// puts directly into a URL.
pub fn validate_hub_path_id<'a>(value: &'a str, field_name: &str) -> Result<&'a str, RunnerError> {
    let trimmed = value.trim();
    if value != trimmed
        || trimmed.is_empty()
        || trimmed.len() > 160
        || !trimmed
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || ch == '_' || ch == '-' || ch == '.')
        || trimmed == "."
        || trimmed == ".."
    {
        return Err(RunnerError::new(
            "hub_path_id_invalid",
            format!("{field_name} must be a safe Hub identifier."),
        ));
    }
    Ok(trimmed)
}

fn response_detail(body: &Value, token: Option<&str>) -> String {
    let raw = body
        .get("detail")
        .or_else(|| body.get("error"))
        .map(|value| {
            if let Some(message) = value.get("message").and_then(Value::as_str) {
                message.to_string()
            } else if let Some(text) = value.as_str() {
                text.to_string()
            } else {
                value.to_string()
            }
        })
        .unwrap_or_else(|| "no detail".to_string());
    redact_response_detail(raw, token)
        .chars()
        .take(300)
        .collect()
}

fn redact_response_detail(detail: String, token: Option<&str>) -> String {
    let Some(token) = token.map(str::trim).filter(|value| !value.is_empty()) else {
        return detail;
    };
    detail
        .replace(token, "[redacted]")
        .replace(&format!("Bearer {token}"), "Bearer [redacted]")
}
