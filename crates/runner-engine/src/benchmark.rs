use crate::RunnerError;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::env;
use std::io::Read;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const METRIC_ENVELOPE_PREFIX: &str = "INFERGRADE_NATIVE_FIRST_RUN_METRICS ";
const DEFAULT_NATIVE_RUNTIME_TIMEOUT: Duration = Duration::from_secs(120);
const PREVIEW_CHAR_LIMIT: usize = 2_000;
const MAX_FIRST_RUN_DURATION_MS: u64 = 86_400_000;
const MAX_DECODE_TOKENS_PER_SECOND: f64 = 1_000_000.0;
const MAX_PEAK_MEMORY_BYTES: u64 = 1 << 44;

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
    timeout: Duration,
}

impl NativeCommandRuntime {
    pub fn new(command_path: impl Into<PathBuf>, runtime_id: impl Into<String>) -> Self {
        Self {
            command_path: command_path.into(),
            runtime_id: runtime_id.into(),
            timeout: DEFAULT_NATIVE_RUNTIME_TIMEOUT,
        }
    }

    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }
}

fn metric_u64(metrics: &Value, key: &str) -> Result<u64, String> {
    metrics
        .get(key)
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("metric envelope missing integer field `{key}`"))
}

fn metric_f64(metrics: &Value, key: &str) -> Result<f64, String> {
    let value = metrics
        .get(key)
        .and_then(Value::as_f64)
        .ok_or_else(|| format!("metric envelope missing numeric field `{key}`"))?;
    if !value.is_finite() || !(0.0..=MAX_DECODE_TOKENS_PER_SECOND).contains(&value) {
        return Err(format!(
            "metric envelope field `{key}` is outside the supported range"
        ));
    }
    Ok(value)
}

fn metric_u32(metrics: &Value, key: &str) -> Result<u32, String> {
    let value = metric_u64(metrics, key)?;
    u32::try_from(value).map_err(|_| format!("metric envelope field `{key}` is too large"))
}

fn metric_duration_ms(metrics: &Value, key: &str) -> Result<u64, String> {
    let value = metric_u64(metrics, key)?;
    if value > MAX_FIRST_RUN_DURATION_MS {
        return Err(format!(
            "metric envelope field `{key}` is outside the supported range"
        ));
    }
    Ok(value)
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

fn read_process_stream(mut stream: impl Read) -> Result<String, String> {
    let mut bytes = Vec::new();
    stream
        .read_to_end(&mut bytes)
        .map_err(|error| format!("could not read native runtime output: {error}"))?;
    Ok(String::from_utf8_lossy(&bytes).to_string())
}

fn collect_process_stream(
    reader: std::thread::JoinHandle<Result<String, String>>,
    label: &str,
) -> Result<String, String> {
    reader
        .join()
        .map_err(|_| format!("native runtime {label} reader failed"))?
}

impl NativeFirstRunRuntime for NativeCommandRuntime {
    fn run(&self, input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String> {
        let mut child = Command::new(&self.command_path)
            .arg("--model")
            .arg(&input.model_path)
            .arg("--prompt")
            .arg(&input.prompt)
            .arg("--max-tokens")
            .arg(input.max_tokens.to_string())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|error| {
                format!(
                    "could not invoke native runtime `{}`: {error}",
                    self.command_path.display()
                )
            })?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "could not capture native runtime stdout".to_string())?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| "could not capture native runtime stderr".to_string())?;
        let stdout_reader = std::thread::spawn(move || read_process_stream(stdout));
        let stderr_reader = std::thread::spawn(move || read_process_stream(stderr));
        let started_at = Instant::now();
        let status = loop {
            if let Some(status) = child
                .try_wait()
                .map_err(|error| format!("could not wait for native runtime: {error}"))?
            {
                break status;
            }
            if started_at.elapsed() >= self.timeout {
                let _ = child.kill();
                let _ = child.wait();
                let stdout = collect_process_stream(stdout_reader, "stdout")?;
                let stderr = collect_process_stream(stderr_reader, "stderr")?;
                return Err(format!(
                    "native runtime timed out after {} seconds. stdout preview: `{}` stderr preview: `{}`",
                    self.timeout.as_secs(),
                    preview(&stdout),
                    preview(&stderr)
                ));
            }
            std::thread::sleep(Duration::from_millis(25));
        };
        let stdout = collect_process_stream(stdout_reader, "stdout")?;
        let stderr = collect_process_stream(stderr_reader, "stderr")?;
        let metrics = if status.success() {
            Some(parse_metric_envelope(&stdout)?)
        } else {
            None
        };
        Ok(NativeRuntimeOutput {
            runtime_id: self.runtime_id.clone(),
            stdout,
            stderr,
            exit_code: status.code().unwrap_or(-1),
            load_time_ms: metrics
                .as_ref()
                .map(|value| metric_duration_ms(value, "load_time_ms"))
                .transpose()?
                .unwrap_or(0),
            time_to_first_token_ms: metrics
                .as_ref()
                .map(|value| metric_duration_ms(value, "time_to_first_token_ms"))
                .transpose()?
                .unwrap_or(0),
            decode_tokens_per_second: metrics
                .as_ref()
                .map(|value| metric_f64(value, "decode_tokens_per_second"))
                .transpose()?
                .unwrap_or(0.0),
            generated_tokens: metrics
                .as_ref()
                .map(|value| metric_u32(value, "generated_tokens"))
                .transpose()?
                .unwrap_or(0),
            peak_memory_bytes: metrics
                .as_ref()
                .map(|value| optional_metric_u64(value, "peak_memory_bytes"))
                .transpose()?
                .flatten(),
        })
    }
}

fn preview(text: &str) -> String {
    let mut redacted = text.to_string();
    for (key, value) in env::vars() {
        let key = key.to_ascii_lowercase();
        if value.len() >= 8
            && (key.contains("token")
                || key.contains("secret")
                || key.contains("password")
                || key.contains("credential")
                || key.contains("authorization"))
        {
            redacted = redacted.replace(&value, "[redacted]");
        }
    }
    redacted
        .lines()
        .map(redact_sensitive_line)
        .collect::<Vec<_>>()
        .join("\n")
        .chars()
        .take(PREVIEW_CHAR_LIMIT)
        .collect()
}

fn redact_sensitive_line(line: &str) -> String {
    let lower = line.to_ascii_lowercase();
    let sensitive_markers = [
        "authorization:",
        "bearer ",
        "api_key",
        "api-key",
        "apikey",
        "access_token",
        "access-token",
        "refresh_token",
        "refresh-token",
        "runner_token",
        "runner-token",
        "infergrade_api_token",
        "token=",
        "password=",
        "secret=",
    ];
    if sensitive_markers
        .iter()
        .any(|marker| lower.contains(marker))
    {
        "[redacted sensitive output line]".to_string()
    } else {
        line.to_string()
    }
}

fn validate_runtime_output(
    output: &NativeRuntimeOutput,
    max_tokens: u32,
) -> Result<NativeFirstRunMetrics, RunnerError> {
    if output.load_time_ms > MAX_FIRST_RUN_DURATION_MS {
        return Err(RunnerError::new(
            "native_runtime_invalid_metrics",
            "Native first-run runtime reported an unsupported load time.",
        ));
    }
    if output.time_to_first_token_ms > MAX_FIRST_RUN_DURATION_MS {
        return Err(RunnerError::new(
            "native_runtime_invalid_metrics",
            "Native first-run runtime reported an unsupported time to first token.",
        ));
    }
    if !output.decode_tokens_per_second.is_finite()
        || !(0.0..=MAX_DECODE_TOKENS_PER_SECOND).contains(&output.decode_tokens_per_second)
    {
        return Err(RunnerError::new(
            "native_runtime_invalid_metrics",
            "Native first-run runtime reported an unsupported decode speed.",
        ));
    }
    if output.generated_tokens > max_tokens {
        return Err(RunnerError::new(
            "native_runtime_invalid_metrics",
            "Native first-run runtime reported more generated tokens than requested.",
        ));
    }
    if output
        .peak_memory_bytes
        .is_some_and(|value| value > MAX_PEAK_MEMORY_BYTES)
    {
        return Err(RunnerError::new(
            "native_runtime_invalid_metrics",
            "Native first-run runtime reported an unsupported memory footprint.",
        ));
    }
    Ok(NativeFirstRunMetrics {
        load_time_ms: output.load_time_ms,
        time_to_first_token_ms: output.time_to_first_token_ms,
        decode_tokens_per_second: output.decode_tokens_per_second,
        generated_tokens: output.generated_tokens,
        peak_memory_bytes: output.peak_memory_bytes,
    })
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
                "Native first-run runtime exited with code {}. stdout preview: `{}` stderr preview: `{}`",
                output.exit_code,
                preview(&output.stdout),
                preview(&output.stderr)
            ),
        ));
    }
    let metrics = validate_runtime_output(&output, input.max_tokens)?;

    Ok(NativeFirstRunResult {
        status: "completed".to_string(),
        evidence_kind: "native_first_run".to_string(),
        uploaded: false,
        model_path: input.model_path.display().to_string(),
        runtime_id: output.runtime_id,
        runtime_hint: input.runtime_hint,
        metrics,
        stdout_preview: preview(&output.stdout),
        stderr_preview: preview(&output.stderr),
    })
}
