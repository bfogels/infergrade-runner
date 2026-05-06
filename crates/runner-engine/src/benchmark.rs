use crate::RunnerError;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::path::PathBuf;
use std::process::Command;

const METRIC_ENVELOPE_PREFIX: &str = "INFERGRADE_NATIVE_FIRST_RUN_METRICS ";

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct NativeFirstRunInput {
    pub model_path: PathBuf,
    pub runtime_hint: Option<String>,
    pub prompt: String,
    pub max_tokens: u32,
    pub upload: bool,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct NativeRuntimeOutput {
    pub runtime_id: String,
    pub stdout: String,
    pub stderr: String,
    pub exit_code: i32,
    pub load_time_ms: u64,
    pub time_to_first_token_ms: u64,
    pub decode_tokens_per_second: f64,
    pub generated_tokens: u32,
    pub peak_memory_bytes: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct NativeFirstRunMetrics {
    pub load_time_ms: u64,
    pub time_to_first_token_ms: u64,
    pub decode_tokens_per_second: f64,
    pub generated_tokens: u32,
    pub peak_memory_bytes: Option<u64>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct NativeFirstRunResult {
    pub status: String,
    pub evidence_kind: String,
    pub uploaded: bool,
    pub model_path: String,
    pub runtime_id: String,
    pub runtime_hint: Option<String>,
    pub metrics: NativeFirstRunMetrics,
    pub stdout_preview: String,
    pub stderr_preview: String,
}

pub trait NativeFirstRunRuntime {
    fn run(&self, input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeCommandRuntime {
    command_path: PathBuf,
    runtime_id: String,
}

impl NativeCommandRuntime {
    pub fn new(command_path: impl Into<PathBuf>, runtime_id: impl Into<String>) -> Self {
        Self {
            command_path: command_path.into(),
            runtime_id: runtime_id.into(),
        }
    }
}

fn metric_u64(metrics: &Value, key: &str) -> Result<u64, String> {
    metrics
        .get(key)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("metric envelope missing integer field `{key}`"))
}

fn metric_f64(metrics: &Value, key: &str) -> Result<f64, String> {
    metrics
        .get(key)
        .and_then(Value::as_f64)
        .ok_or_else(|| format!("metric envelope missing numeric field `{key}`"))
}

fn optional_metric_u64(metrics: &Value, key: &str) -> Result<Option<u64>, String> {
    match metrics.get(key) {
        Some(Value::Null) | None => Ok(None),
        Some(value) => value
            .as_u64()
            .map(Some)
            .ok_or_else(|| format!("metric envelope field `{key}` must be an integer or null")),
    }
}

fn parse_metric_envelope(stdout: &str) -> Result<Value, String> {
    let raw = stdout
        .lines()
        .find_map(|line| line.strip_prefix(METRIC_ENVELOPE_PREFIX))
        .ok_or_else(|| "native runtime output did not include a metric envelope".to_string())?;
    serde_json::from_str(raw).map_err(|error| format!("metric envelope is invalid JSON: {error}"))
}

impl NativeFirstRunRuntime for NativeCommandRuntime {
    fn run(&self, input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String> {
        let output = Command::new(&self.command_path)
            .arg("--model")
            .arg(&input.model_path)
            .arg("--prompt")
            .arg(&input.prompt)
            .arg("--max-tokens")
            .arg(input.max_tokens.to_string())
            .output()
            .map_err(|error| {
                format!(
                    "could not invoke native runtime `{}`: {error}",
                    self.command_path.display()
                )
            })?;
        let stdout = String::from_utf8_lossy(&output.stdout).to_string();
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let metrics = if output.status.success() {
            Some(parse_metric_envelope(&stdout)?)
        } else {
            None
        };
        Ok(NativeRuntimeOutput {
            runtime_id: self.runtime_id.clone(),
            stdout,
            stderr,
            exit_code: output.status.code().unwrap_or(-1),
            load_time_ms: metrics
                .as_ref()
                .map(|value| metric_u64(value, "load_time_ms"))
                .transpose()?
                .unwrap_or(0),
            time_to_first_token_ms: metrics
                .as_ref()
                .map(|value| metric_u64(value, "time_to_first_token_ms"))
                .transpose()?
                .unwrap_or(0),
            decode_tokens_per_second: metrics
                .as_ref()
                .map(|value| metric_f64(value, "decode_tokens_per_second"))
                .transpose()?
                .unwrap_or(0.0),
            generated_tokens: metrics
                .as_ref()
                .map(|value| metric_u64(value, "generated_tokens"))
                .transpose()?
                .unwrap_or(0) as u32,
            peak_memory_bytes: metrics
                .as_ref()
                .map(|value| optional_metric_u64(value, "peak_memory_bytes"))
                .transpose()?
                .flatten(),
        })
    }
}

fn preview(text: &str) -> String {
    text.chars().take(2_000).collect()
}

pub fn validate_native_first_run_input(input: &NativeFirstRunInput) -> Result<(), RunnerError> {
    if !input.model_path.is_file() {
        return Err(RunnerError::new(
            "model_path_missing",
            "Select a local GGUF model file before running the native first-run benchmark.",
        ));
    }
    if input.prompt.trim().is_empty() {
        return Err(RunnerError::new(
            "prompt_missing",
            "A short prompt is required for the native first-run benchmark.",
        ));
    }
    if input.max_tokens == 0 {
        return Err(RunnerError::new(
            "max_tokens_invalid",
            "max_tokens must be greater than zero for the native first-run benchmark.",
        ));
    }
    if input.upload {
        return Err(RunnerError::new(
            "upload_not_implemented",
            "Native first-run upload is not implemented in this engine slice.",
        ));
    }
    Ok(())
}

pub fn run_native_first_run(
    input: NativeFirstRunInput,
    runtime: &dyn NativeFirstRunRuntime,
) -> Result<NativeFirstRunResult, RunnerError> {
    validate_native_first_run_input(&input)?;
    let output = runtime.run(&input).map_err(|message| {
        RunnerError::new(
            "native_runtime_failed",
            format!("Native first-run runtime failed: {message}"),
        )
    })?;
    if output.exit_code != 0 {
        return Err(RunnerError::new(
            "native_runtime_failed",
            format!(
                "Native first-run runtime exited with code {}.",
                output.exit_code
            ),
        ));
    }

    Ok(NativeFirstRunResult {
        status: "completed".to_string(),
        evidence_kind: "native_first_run".to_string(),
        uploaded: false,
        model_path: input.model_path.display().to_string(),
        runtime_id: output.runtime_id,
        runtime_hint: input.runtime_hint,
        metrics: NativeFirstRunMetrics {
            load_time_ms: output.load_time_ms,
            time_to_first_token_ms: output.time_to_first_token_ms,
            decode_tokens_per_second: output.decode_tokens_per_second,
            generated_tokens: output.generated_tokens,
            peak_memory_bytes: output.peak_memory_bytes,
        },
        stdout_preview: preview(&output.stdout),
        stderr_preview: preview(&output.stderr),
    })
}
