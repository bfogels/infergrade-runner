use crate::{desktop_environment, normalize_api_url, RunnerError};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RunnerCapabilities {
    pub run_token_supported: bool,
    pub auto_upload: bool,
}

impl Default for RunnerCapabilities {
    fn default() -> Self {
        Self {
            run_token_supported: true,
            auto_upload: true,
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RunnerRegisterRequest {
    pub runner_id: String,
    pub execution_modes: Vec<String>,
    pub status: String,
    pub label: String,
    pub runner_kind: String,
    pub hostname: Option<String>,
    pub provider_id: Option<String>,
    pub instance_type_id: Option<String>,
    pub capabilities: RunnerCapabilities,
    pub version: String,
    pub environment: Value,
    pub contract: Value,
    pub diagnostics: Value,
}

impl RunnerRegisterRequest {
    pub fn new(runner_id: &str, execution_mode: &str, hostname: Option<String>) -> Self {
        Self {
            runner_id: runner_id.to_string(),
            execution_modes: vec![execution_mode.to_string()],
            status: "starting".to_string(),
            label: runner_id.to_string(),
            runner_kind: if execution_mode == "cloud_container" {
                "cloud_worker".to_string()
            } else {
                "local_listener".to_string()
            },
            hostname,
            provider_id: None,
            instance_type_id: None,
            capabilities: RunnerCapabilities::default(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            environment: desktop_environment(),
            contract: json!({}),
            diagnostics: json!({}),
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RunnerHeartbeatRequest {
    pub status: String,
    pub current_run_id: Option<String>,
    pub hostname: Option<String>,
    pub provider_id: Option<String>,
    pub instance_type_id: Option<String>,
    pub metadata: Value,
    pub environment: Value,
    pub contract: Value,
    pub diagnostics: Value,
}

impl RunnerHeartbeatRequest {
    pub fn new(
        status: &str,
        current_run_id: Option<&str>,
        hostname: Option<String>,
        message: Option<&str>,
    ) -> Self {
        Self {
            status: status.to_string(),
            current_run_id: current_run_id.map(str::to_string),
            hostname,
            provider_id: None,
            instance_type_id: None,
            metadata: match message {
                Some(message) => json!({"message": message}),
                None => json!({}),
            },
            environment: desktop_environment(),
            contract: json!({}),
            diagnostics: json!({}),
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct ClaimRunJobRequest {
    pub worker_id: String,
    pub execution_mode: String,
    pub run_id: Option<String>,
    pub run_config_id: Option<String>,
    pub provider_id: Option<String>,
    pub instance_type_id: Option<String>,
    pub hostname: Option<String>,
}

impl ClaimRunJobRequest {
    pub fn new(
        worker_id: &str,
        execution_mode: &str,
        run_id: Option<&str>,
        run_config_id: Option<&str>,
        hostname: Option<String>,
    ) -> Self {
        Self {
            worker_id: worker_id.to_string(),
            execution_mode: execution_mode.to_string(),
            run_id: run_id.map(str::to_string),
            run_config_id: run_config_id.map(str::to_string),
            provider_id: None,
            instance_type_id: None,
            hostname,
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RunnerProtocolPreview {
    pub api_url: String,
    pub runner_id: String,
    pub execution_mode: String,
    pub endpoints: RunnerProtocolEndpoints,
    pub register: RunnerRegisterRequest,
    pub heartbeat: RunnerHeartbeatRequest,
    pub claim: ClaimRunJobRequest,
    pub secret_boundary: String,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RunnerProtocolEndpoints {
    pub register: String,
    pub heartbeat: String,
    pub claim: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunnerProtocolPreviewInput {
    pub api_url: String,
    pub runner_id: String,
    pub execution_mode: String,
    pub hostname: Option<String>,
}

impl RunnerProtocolPreviewInput {
    pub fn build(self) -> Result<RunnerProtocolPreview, RunnerError> {
        let api_url = normalize_api_url(&self.api_url)
            .map_err(|error| RunnerError::new("hub_url_invalid", error))?;
        let runner_id = self.runner_id.trim().to_string();
        if runner_id.is_empty() {
            return Err(RunnerError::new(
                "runner_id_missing",
                "Runner protocol preview requires a runner id.",
            ));
        }
        let execution_mode = self.execution_mode.trim().to_string();
        if execution_mode.is_empty() {
            return Err(RunnerError::new(
                "execution_mode_missing",
                "Runner protocol preview requires an execution mode.",
            ));
        }

        Ok(RunnerProtocolPreview {
            api_url,
            runner_id: runner_id.clone(),
            execution_mode: execution_mode.clone(),
            endpoints: RunnerProtocolEndpoints {
                register: "/v1/runners/register".to_string(),
                heartbeat: format!("/v1/runners/{runner_id}/heartbeat"),
                claim: "/v1/runs/claim".to_string(),
            },
            register: RunnerRegisterRequest::new(
                &runner_id,
                &execution_mode,
                self.hostname.clone(),
            ),
            heartbeat: RunnerHeartbeatRequest::new(
                "listening",
                None,
                self.hostname.clone(),
                Some("Runner registered and is listening for jobs."),
            ),
            claim: ClaimRunJobRequest::new(&runner_id, &execution_mode, None, None, self.hostname),
            secret_boundary:
                "payload preview excludes bearer tokens; Rust attaches authorization only when sending requests"
                    .to_string(),
        })
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RunnerProtocolPingPlan {
    pub api_url: String,
    pub runner_id: String,
    pub execution_mode: String,
    pub register_endpoint: String,
    pub heartbeat_endpoint: String,
    pub register: RunnerRegisterRequest,
    pub heartbeat: RunnerHeartbeatRequest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunnerProtocolPingInput {
    pub api_url: String,
    pub runner_id: String,
    pub execution_mode: String,
    pub hostname: Option<String>,
}

impl RunnerProtocolPingInput {
    pub fn build(self) -> Result<RunnerProtocolPingPlan, RunnerError> {
        let preview = RunnerProtocolPreviewInput {
            api_url: self.api_url,
            runner_id: self.runner_id,
            execution_mode: self.execution_mode,
            hostname: self.hostname,
        }
        .build()?;

        Ok(RunnerProtocolPingPlan {
            api_url: preview.api_url,
            runner_id: preview.runner_id,
            execution_mode: preview.execution_mode,
            register_endpoint: preview.endpoints.register,
            heartbeat_endpoint: preview.endpoints.heartbeat,
            register: preview.register,
            heartbeat: preview.heartbeat,
        })
    }
}

pub fn runner_register_payload(
    runner_id: &str,
    execution_mode: &str,
    hostname: Option<String>,
) -> Value {
    serde_json::to_value(RunnerRegisterRequest::new(
        runner_id,
        execution_mode,
        hostname,
    ))
    .expect("runner register request serializes")
}

pub fn runner_heartbeat_payload(
    status: &str,
    current_run_id: Option<&str>,
    hostname: Option<String>,
    message: Option<&str>,
) -> Value {
    serde_json::to_value(RunnerHeartbeatRequest::new(
        status,
        current_run_id,
        hostname,
        message,
    ))
    .expect("runner heartbeat request serializes")
}

pub fn claim_run_job_payload(
    worker_id: &str,
    execution_mode: &str,
    run_id: Option<&str>,
    run_config_id: Option<&str>,
    hostname: Option<String>,
) -> Value {
    serde_json::to_value(ClaimRunJobRequest::new(
        worker_id,
        execution_mode,
        run_id,
        run_config_id,
        hostname,
    ))
    .expect("claim run job request serializes")
}
