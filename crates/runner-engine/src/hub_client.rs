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
