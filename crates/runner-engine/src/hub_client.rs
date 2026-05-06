use crate::{normalize_api_url, RunnerError};
use serde_json::{json, Value};
use std::fmt;

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
    })
}

pub fn build_run_bundle_upload_request(
    api_url: &str,
    run_id: &str,
    bundle_payload: Value,
    bearer_token: Option<&str>,
) -> Result<HubJsonRequest, RunnerError> {
    let run_id = validate_hub_path_id(run_id, "run_id")?;
    validate_bundle_upload_payload(&bundle_payload)?;
    build_hub_json_request(
        HubMethod::Post,
        api_url,
        &format!("/v1/runs/{run_id}/bundle"),
        Some(bundle_payload),
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

fn validate_hub_path_id<'a>(value: &'a str, field_name: &str) -> Result<&'a str, RunnerError> {
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
