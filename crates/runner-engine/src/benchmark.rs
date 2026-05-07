use crate::{RunnerError, RunnerEvent};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::env;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

const NATIVE_FIRST_RUN_ARTIFACT_FORMAT: &str = "infergrade.native_first_run.v1";
const NATIVE_FIRST_RUN_BUNDLE_PAYLOAD_FORMAT: &str = "infergrade.bundle_upload.v1";
const METRIC_ENVELOPE_PREFIX: &str = "INFERGRADE_NATIVE_FIRST_RUN_METRICS ";
const DEFAULT_NATIVE_RUNTIME_TIMEOUT: Duration = Duration::from_secs(120);
const PREVIEW_CHAR_LIMIT: usize = 2_000;
const PREVIEW_TRUNCATED_MARKER: &str = "\n[preview truncated]";
const MAX_FIRST_RUN_DURATION_MS: u64 = 86_400_000;
const MAX_DECODE_TOKENS_PER_SECOND: f64 = 1_000_000.0;
const MAX_PEAK_MEMORY_BYTES: u64 = 1 << 44;
const LLAMA_CPP_AUTO_RUNTIME_ID: &str = "llama.cpp-auto";
const NATIVE_FIRST_RUN_BENCHMARK_ID: &str = "native_first_run";

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

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct NativeFirstRunArtifact {
    pub path: String,
    pub format: String,
    pub uploaded: bool,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct NativeFirstRunBundleOptions {
    pub bundle_id: Option<String>,
    pub created_at: Option<String>,
    pub deployment_profile_id: String,
    pub use_case: String,
    pub submission_channel: String,
}

impl Default for NativeFirstRunBundleOptions {
    fn default() -> Self {
        Self {
            bundle_id: None,
            created_at: None,
            deployment_profile_id: "interactive_chat_v1".to_string(),
            use_case: "general_assistant".to_string(),
            submission_channel: "infergrade_rust_runner".to_string(),
        }
    }
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LlamaCppRuntime {
    command_path: PathBuf,
    runtime_id: String,
    timeout: Duration,
}

#[derive(Clone, Debug, Default, PartialEq)]
struct LlamaTimings {
    load_time_ms: Option<f64>,
    eval_time_ms: Option<f64>,
    eval_tokens: Option<f64>,
    eval_tokens_per_second: Option<f64>,
    total_time_ms: Option<f64>,
}

#[derive(Clone, Debug)]
struct ProcessStream {
    text: String,
    first_byte_ms: Option<u64>,
}

#[derive(Clone, Debug)]
struct ProcessRun {
    stdout: String,
    stderr: String,
    exit_code: i32,
    elapsed_ms: u64,
    stdout_first_byte_ms: Option<u64>,
}

impl LlamaCppRuntime {
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

    pub fn resolve(command_path: Option<PathBuf>) -> Result<Self, String> {
        let command_path = match command_path {
            Some(path) => validate_llama_cpp_command_path(path)?,
            None => selected_llama_cpp_cli_path()?.ok_or_else(|| {
                "No selected llama.cpp runtime was found. Pass --runtime-path or select an app-managed llama.cpp runtime before using --runtime auto.".to_string()
            })?,
        };
        Ok(Self::new(command_path, LLAMA_CPP_AUTO_RUNTIME_ID))
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

fn read_process_stream(
    mut stream: impl Read,
    started_at: Instant,
) -> Result<ProcessStream, String> {
    let mut bytes = Vec::new();
    let mut first_byte_ms = None;
    let mut buffer = [0_u8; 8192];
    loop {
        let count = stream
            .read(&mut buffer)
            .map_err(|error| format!("could not read native runtime output: {error}"))?;
        if count == 0 {
            break;
        }
        if first_byte_ms.is_none() {
            first_byte_ms = Some(duration_ms(started_at.elapsed()));
        }
        bytes.extend_from_slice(&buffer[..count]);
    }
    Ok(ProcessStream {
        text: String::from_utf8_lossy(&bytes).to_string(),
        first_byte_ms,
    })
}

fn collect_process_stream(
    reader: std::thread::JoinHandle<Result<ProcessStream, String>>,
    label: &str,
) -> Result<ProcessStream, String> {
    reader
        .join()
        .map_err(|_| format!("native runtime {label} reader failed"))?
}

fn duration_ms(duration: Duration) -> u64 {
    u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
}

fn run_process_with_timeout(
    mut command: Command,
    timeout: Duration,
    extra_sensitive_values: &[String],
) -> Result<ProcessRun, String> {
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|error| format!("could not invoke native runtime: {error}"))?;
    let started_at = Instant::now();
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "could not capture native runtime stdout".to_string())?;
    let stderr = child
        .stderr
        .take()
        .ok_or_else(|| "could not capture native runtime stderr".to_string())?;
    let stdout_reader = std::thread::spawn(move || read_process_stream(stdout, started_at));
    let stderr_reader = std::thread::spawn(move || read_process_stream(stderr, started_at));
    let status = loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|error| format!("could not wait for native runtime: {error}"))?
        {
            break status;
        }
        if started_at.elapsed() >= timeout {
            let _ = child.kill();
            let _ = child.wait();
            let stdout = collect_process_stream(stdout_reader, "stdout")?;
            let stderr = collect_process_stream(stderr_reader, "stderr")?;
            return Err(format!(
                "native runtime timed out after {} seconds. stdout preview: `{}` stderr preview: `{}`",
                timeout.as_secs(),
                preview(&stdout.text, extra_sensitive_values),
                preview(&stderr.text, extra_sensitive_values)
            ));
        }
        std::thread::sleep(Duration::from_millis(25));
    };
    let elapsed_ms = duration_ms(started_at.elapsed());
    let stdout = collect_process_stream(stdout_reader, "stdout")?;
    let stderr = collect_process_stream(stderr_reader, "stderr")?;
    Ok(ProcessRun {
        stdout: stdout.text,
        stderr: stderr.text,
        exit_code: status.code().unwrap_or(-1),
        elapsed_ms,
        stdout_first_byte_ms: stdout.first_byte_ms,
    })
}

impl NativeFirstRunRuntime for NativeCommandRuntime {
    fn run(&self, input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String> {
        let mut command = Command::new(&self.command_path);
        command
            .arg("--model")
            .arg(&input.model_path)
            .arg("--prompt")
            .arg(&input.prompt)
            .arg("--max-tokens")
            .arg(input.max_tokens.to_string());
        let prompt_redactions = [input.prompt.clone()];
        let output = run_process_with_timeout(command, self.timeout, &prompt_redactions).map_err(
            |error| {
                format!(
                    "could not invoke native runtime `{}`: {error}",
                    self.command_path.display()
                )
            },
        )?;
        let metrics = if output.exit_code == 0 {
            Some(parse_metric_envelope(&output.stdout)?)
        } else {
            None
        };
        Ok(NativeRuntimeOutput {
            runtime_id: self.runtime_id.clone(),
            stdout: output.stdout,
            stderr: output.stderr,
            exit_code: output.exit_code,
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

impl NativeFirstRunRuntime for LlamaCppRuntime {
    fn run(&self, input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String> {
        let command_path = first_run_llama_cpp_command_path(&self.command_path);
        let mut command = Command::new(&command_path);
        command
            .arg("-m")
            .arg(&input.model_path)
            .arg("-p")
            .arg(&input.prompt)
            .arg("-n")
            .arg(input.max_tokens.to_string())
            .arg("--no-display-prompt")
            .arg("--single-turn")
            .arg("--simple-io")
            .arg("--perf");
        if should_request_llama_cpp_metal_offload() {
            command.arg("-ngl").arg("999");
        }
        let prompt_redactions = [input.prompt.clone()];
        let output = run_process_with_timeout(command, self.timeout, &prompt_redactions).map_err(
            |error| {
                format!(
                    "could not invoke llama.cpp runtime `{}`: {error}",
                    command_path.display()
                )
            },
        )?;
        if output.exit_code != 0 {
            return Ok(NativeRuntimeOutput {
                runtime_id: self.runtime_id.clone(),
                stdout: output.stdout,
                stderr: output.stderr,
                exit_code: output.exit_code,
                load_time_ms: 0,
                time_to_first_token_ms: 0,
                decode_tokens_per_second: 0.0,
                generated_tokens: 0,
                peak_memory_bytes: None,
            });
        }
        let combined_log = format!("{}\n{}", output.stdout, output.stderr);
        let timings = parse_llama_timings(&combined_log);
        let generated_tokens = match timings.eval_tokens {
            Some(value) => timing_u32(Some(value), "eval tokens")?,
            None => return Err("llama.cpp output did not include eval tokens".to_string()),
        };
        let decode_tokens_per_second = timing_decode_tokens_per_second(&timings, generated_tokens)?;
        Ok(NativeRuntimeOutput {
            runtime_id: self.runtime_id.clone(),
            stdout: output.stdout,
            stderr: output.stderr,
            exit_code: output.exit_code,
            load_time_ms: timing_ms(timings.load_time_ms).unwrap_or(output.elapsed_ms),
            time_to_first_token_ms: output
                .stdout_first_byte_ms
                .or_else(|| timing_ms(timings.total_time_ms))
                .unwrap_or(output.elapsed_ms),
            decode_tokens_per_second,
            generated_tokens,
            peak_memory_bytes: None,
        })
    }
}

fn should_request_llama_cpp_metal_offload() -> bool {
    cfg!(target_os = "macos") && cfg!(target_arch = "aarch64")
}

fn first_run_llama_cpp_command_path(cli_path: &Path) -> PathBuf {
    let Some(parent) = cli_path.parent() else {
        return cli_path.to_path_buf();
    };
    let extension = cli_path.extension().and_then(|value| value.to_str());
    let completion_name = match extension {
        Some(extension) if !extension.is_empty() => format!("llama-completion.{extension}"),
        _ => "llama-completion".to_string(),
    };
    let completion_path = parent.join(completion_name);
    if completion_path.is_file() {
        completion_path
    } else {
        cli_path.to_path_buf()
    }
}

fn validate_llama_cpp_command_path(path: PathBuf) -> Result<PathBuf, String> {
    if !path.is_file() {
        return Err(format!(
            "llama.cpp runtime path `{}` does not exist or is not a file.",
            path.display()
        ));
    }
    Ok(path)
}

fn selected_llama_cpp_cli_path() -> Result<Option<PathBuf>, String> {
    let path = crate::selected_llama_cpp_runtime_path()?;
    let text = match std::fs::read_to_string(&path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => {
            return Err(format!(
                "could not read selected llama.cpp runtime at `{}`: {error}",
                path.display()
            ))
        }
    };
    let value: Value = serde_json::from_str(&text).map_err(|error| {
        format!(
            "selected llama.cpp runtime at `{}` is not valid JSON: {error}",
            path.display()
        )
    })?;
    let raw = value
        .pointer("/binaries/cli")
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| {
            format!(
                "selected llama.cpp runtime at `{}` does not include binaries.cli.",
                path.display()
            )
        })?;
    validate_llama_cpp_command_path(PathBuf::from(raw)).map(Some)
}

fn parse_llama_timings(raw_log: &str) -> LlamaTimings {
    let mut timings = LlamaTimings::default();
    for line in raw_log.lines() {
        let lowered = line.to_ascii_lowercase();
        if lowered.contains("load time") {
            timings.load_time_ms = parse_ms_value(line);
        } else if lowered.contains("eval time") && !lowered.contains("prompt eval time") {
            timings.eval_time_ms = parse_ms_value(line);
            timings.eval_tokens = parse_slash_count(line);
            timings.eval_tokens_per_second = parse_tokens_per_second(line);
        } else if lowered.contains("total time") {
            timings.total_time_ms = parse_ms_value(line);
        }
    }
    timings
}

fn parse_ms_value(line: &str) -> Option<f64> {
    line.split_once('=')?
        .1
        .split("ms")
        .next()?
        .trim()
        .parse()
        .ok()
}

fn parse_slash_count(line: &str) -> Option<f64> {
    line.split_once('/')?
        .1
        .split_whitespace()
        .next()?
        .trim()
        .parse()
        .ok()
}

fn parse_tokens_per_second(line: &str) -> Option<f64> {
    let marker = "tokens per second";
    let lower = line.to_ascii_lowercase();
    let marker_start = lower.find(marker)?;
    let before_marker = &line[..marker_start];
    before_marker
        .split(|ch: char| !(ch.is_ascii_digit() || ch == '.'))
        .filter(|part| !part.is_empty())
        .last()?
        .parse()
        .ok()
}

fn timing_ms(value: Option<f64>) -> Option<u64> {
    let value = value?;
    if value.is_finite() && value >= 0.0 && value <= MAX_FIRST_RUN_DURATION_MS as f64 {
        Some(value.round() as u64)
    } else {
        None
    }
}

fn timing_u32(value: Option<f64>, label: &str) -> Result<u32, String> {
    let value = value.ok_or_else(|| format!("llama.cpp output did not include {label}"))?;
    if value.is_finite() && value >= 0.0 && value <= u32::MAX as f64 {
        Ok(value.round() as u32)
    } else {
        Err(format!("llama.cpp output included unsupported {label}"))
    }
}

fn timing_decode_tokens_per_second(
    timings: &LlamaTimings,
    generated_tokens: u32,
) -> Result<f64, String> {
    if let Some(value) = timings.eval_tokens_per_second {
        if value.is_finite() && value >= 0.0 && value <= MAX_DECODE_TOKENS_PER_SECOND {
            return Ok(value);
        }
    }
    let eval_time_ms = timings
        .eval_time_ms
        .filter(|value| value.is_finite() && *value > 0.0)
        .ok_or_else(|| "llama.cpp output did not include usable eval timing".to_string())?;
    Ok(generated_tokens as f64 / (eval_time_ms / 1000.0))
}

fn preview(text: &str, extra_sensitive_values: &[String]) -> String {
    let mut sensitive_values = sensitive_env_values();
    sensitive_values.extend(
        extra_sensitive_values
            .iter()
            .map(|value| value.trim())
            .filter(|value| value.len() >= 8)
            .map(|value| (value.to_string(), "[redacted prompt]")),
    );
    let mut output = String::new();
    let mut remaining = PREVIEW_CHAR_LIMIT;
    let mut truncated = false;
    let mut lines = text.lines().peekable();
    while let Some(line) = lines.next() {
        let redacted = redact_sensitive_line_with_env(line, &sensitive_values);
        if !output.is_empty() {
            if remaining == 0 {
                truncated = true;
                break;
            }
            output.push('\n');
            remaining = remaining.saturating_sub(1);
        }
        let mut chars = redacted.chars();
        let fragment: String = chars.by_ref().take(remaining).collect();
        output.push_str(&fragment);
        remaining = remaining.saturating_sub(fragment.chars().count());
        if chars.next().is_some() {
            truncated = true;
            break;
        }
        if remaining == 0 && lines.peek().is_some() {
            truncated = true;
            break;
        }
    }
    if truncated {
        let marker_len = PREVIEW_TRUNCATED_MARKER.chars().count();
        if output.chars().count() + marker_len > PREVIEW_CHAR_LIMIT {
            output = output
                .chars()
                .take(PREVIEW_CHAR_LIMIT.saturating_sub(marker_len))
                .collect();
        }
        output.push_str(PREVIEW_TRUNCATED_MARKER);
    }
    output
}

fn redact_sensitive_line_with_env(
    line: &str,
    sensitive_values: &[(String, &'static str)],
) -> String {
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
        let mut redacted = line.to_string();
        for (value, replacement) in sensitive_values {
            redacted = redacted.replace(value, replacement);
        }
        redacted
    }
}

fn sensitive_env_values() -> Vec<(String, &'static str)> {
    env::vars()
        .filter_map(|(key, value)| {
            let key = key.to_ascii_lowercase();
            if value.len() >= 8
                && (key.contains("token")
                    || key.contains("secret")
                    || key.contains("password")
                    || key.contains("credential")
                    || key.contains("authorization"))
            {
                Some((value, "[redacted]"))
            } else {
                None
            }
        })
        .collect()
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
    run_native_first_run_with_events(input, runtime, |_| {})
}

pub fn run_native_first_run_with_events<F>(
    input: NativeFirstRunInput,
    runtime: &dyn NativeFirstRunRuntime,
    mut emit: F,
) -> Result<NativeFirstRunResult, RunnerError>
where
    F: FnMut(RunnerEvent),
{
    emit(RunnerEvent::BenchmarkStarted {
        benchmark_id: NATIVE_FIRST_RUN_BENCHMARK_ID.to_string(),
    });
    emit(RunnerEvent::BenchmarkProgress {
        benchmark_id: NATIVE_FIRST_RUN_BENCHMARK_ID.to_string(),
        message: "Validating local model and first-run request.".to_string(),
        progress_percent: Some(5.0),
    });
    if let Err(error) = validate_native_first_run_input(&input) {
        emit(RunnerEvent::Error {
            code: error.code().to_string(),
            message: error.message().to_string(),
        });
        return Err(error);
    }
    emit(RunnerEvent::BenchmarkProgress {
        benchmark_id: NATIVE_FIRST_RUN_BENCHMARK_ID.to_string(),
        message: "Starting native runtime.".to_string(),
        progress_percent: Some(20.0),
    });
    let output = runtime.run(&input).map_err(|message| {
        let error = RunnerError::new(
            "native_runtime_failed",
            format!("Native first-run runtime failed: {message}"),
        );
        emit(RunnerEvent::Error {
            code: error.code().to_string(),
            message: error.message().to_string(),
        });
        error
    })?;
    let prompt_redactions = [input.prompt.clone()];
    emit(RunnerEvent::BenchmarkProgress {
        benchmark_id: NATIVE_FIRST_RUN_BENCHMARK_ID.to_string(),
        message: "Native runtime completed; validating metrics.".to_string(),
        progress_percent: Some(80.0),
    });
    if output.exit_code != 0 {
        let error = RunnerError::new(
            "native_runtime_failed",
            format!(
                "Native first-run runtime exited with code {}. stdout preview: `{}` stderr preview: `{}`",
                output.exit_code,
                preview(&output.stdout, &prompt_redactions),
                preview(&output.stderr, &prompt_redactions)
            ),
        );
        emit(RunnerEvent::Error {
            code: error.code().to_string(),
            message: error.message().to_string(),
        });
        return Err(error);
    }
    let metrics = match validate_runtime_output(&output, input.max_tokens) {
        Ok(metrics) => metrics,
        Err(error) => {
            emit(RunnerEvent::Error {
                code: error.code().to_string(),
                message: error.message().to_string(),
            });
            return Err(error);
        }
    };

    let result = NativeFirstRunResult {
        status: "completed".to_string(),
        evidence_kind: "native_first_run".to_string(),
        uploaded: false,
        model_path: input.model_path.display().to_string(),
        runtime_id: output.runtime_id,
        runtime_hint: input.runtime_hint,
        metrics,
        stdout_preview: preview(&output.stdout, &prompt_redactions),
        stderr_preview: preview(&output.stderr, &prompt_redactions),
    };
    emit(RunnerEvent::BenchmarkCompleted {
        benchmark_id: NATIVE_FIRST_RUN_BENCHMARK_ID.to_string(),
    });
    Ok(result)
}

pub fn write_native_first_run_artifact(
    output_dir: impl AsRef<Path>,
    payload: &Value,
) -> Result<NativeFirstRunArtifact, RunnerError> {
    write_json_artifact(
        output_dir,
        "native-first-run-result.json",
        NATIVE_FIRST_RUN_ARTIFACT_FORMAT,
        payload,
    )
}

pub fn write_native_first_run_bundle_payload(
    output_dir: impl AsRef<Path>,
    payload: &Value,
) -> Result<NativeFirstRunArtifact, RunnerError> {
    write_json_artifact(
        output_dir,
        "native-first-run-bundle.json",
        NATIVE_FIRST_RUN_BUNDLE_PAYLOAD_FORMAT,
        payload,
    )
}

fn write_json_artifact(
    output_dir: impl AsRef<Path>,
    filename: &str,
    format: &str,
    payload: &Value,
) -> Result<NativeFirstRunArtifact, RunnerError> {
    let output_dir = output_dir.as_ref();
    std::fs::create_dir_all(output_dir).map_err(|error| {
        RunnerError::new(
            "native_first_run_artifact_failed",
            format!("Could not create native first-run artifact directory: {error}"),
        )
    })?;
    let artifact_path = output_dir.join(filename);
    let rendered = serde_json::to_string_pretty(payload).map_err(|error| {
        RunnerError::new(
            "native_first_run_artifact_failed",
            format!("Could not render native first-run artifact: {error}"),
        )
    })?;
    std::fs::write(&artifact_path, rendered).map_err(|error| {
        RunnerError::new(
            "native_first_run_artifact_failed",
            format!("Could not write native first-run artifact: {error}"),
        )
    })?;
    Ok(NativeFirstRunArtifact {
        path: artifact_path.display().to_string(),
        format: format.to_string(),
        uploaded: false,
    })
}

pub fn native_first_run_bundle_payload(
    result: &NativeFirstRunResult,
    options: NativeFirstRunBundleOptions,
) -> Value {
    let created_at = options
        .created_at
        .unwrap_or_else(native_first_run_timestamp);
    let model_name = model_name_from_path(&result.model_path);
    let model_slug = slug_fragment(&model_name);
    let bundle_id = options.bundle_id.unwrap_or_else(|| {
        format!(
            "nfr_{}_{}",
            created_at
                .chars()
                .filter(|ch| ch.is_ascii_alphanumeric())
                .collect::<String>(),
            model_slug
        )
        .chars()
        .take(128)
        .collect()
    });
    let result_id = format!(
        "{}_{}",
        bundle_id,
        slug_fragment(&options.deployment_profile_id)
    )
    .chars()
    .take(160)
    .collect::<String>();
    let runtime_id = result.runtime_id.trim();
    let backend_version_pinned = false;
    let runtime_binding_id = if runtime_id.is_empty() {
        "llama.cpp-native-first-run"
    } else {
        runtime_id
    };
    let runtime_ms = result
        .metrics
        .load_time_ms
        .saturating_add(result.metrics.time_to_first_token_ms);
    let runtime_seconds = i64::try_from(std::cmp::max(1, runtime_ms / 1000)).unwrap_or(i64::MAX);
    let decode_speed = result.metrics.decode_tokens_per_second;
    let ttft_ms = result.metrics.time_to_first_token_ms as f64;
    let load_time_ms = result.metrics.load_time_ms as f64;
    let missing_requirements = vec![
        "quant_artifact_sha256",
        "backend_version_pinned",
        "capability_suite_not_run",
        "multi_run_variance_not_captured",
    ];
    let result_record = json!({
        "spec_version": "0.1-draft",
        "bundle_id": bundle_id,
        "result_id": result_id,
        "ontology": {
            "benchmark_subject": {
                "subject_id": format!("native_first_run_{}", model_slug),
                "subject_type": "local_gguf_model",
            },
            "model_family": {
                "family_name": model_name,
            },
            "checkpoint": {
                "checkpoint_name": model_name,
            },
            "quantization": {
                "quantization_label": "unknown",
                "quantization_format": "gguf",
            },
            "runtime_binding": {
                "runtime_binding_id": runtime_binding_id,
                "backend_engine": "llama.cpp",
            },
        },
        "configuration": {
            "configuration_id": format!("cfg_{}", slug_fragment(&format!("{}-{}", model_slug, runtime_binding_id))),
            "model_base": model_name,
            "model_variant": Value::Null,
            "model_instance_name": model_name,
            "model_source": "local_file",
            "model_source_repo": Value::Null,
            "model_revision": "local",
            "quant_label": "unknown",
            "quant_format": "gguf",
            "quant_artifact_sha256": Value::Null,
            "backend_engine": "llama.cpp",
            "backend_wrapper": "infergrade_runner_engine",
            "backend_version": "unverified",
            "backend_execution": "native",
            "backend_flags": [],
            "tokenizer_id": Value::Null,
            "chat_template_id": Value::Null,
            "generation_preset_id": "native_first_run_v1",
        },
        "hardware": native_first_run_hardware_summary(),
        "verification": {
            "verification_level": "experimental",
            "artifact_pinned": false,
            "backend_version_pinned": backend_version_pinned,
            "hardware_captured": true,
            "missing_requirements": missing_requirements,
            "local_comparison_grade_candidate": "informational_only",
        },
        "execution": {
            "execution_profile_id": "local_native_v1",
            "execution_mode": "local_native",
            "launcher": "infergrade-runner",
            "started_at": created_at,
            "completed_at": created_at,
            "benchmark_job_runtime_seconds": runtime_seconds,
            "execution_cost_source": "none",
            "simulated": false,
        },
        "deployment": {
            "deployment_profile_id": options.deployment_profile_id,
            "deployment_status": result.status,
            "ttft_p50_ms": ttft_ms,
            "ttft_p95_ms": ttft_ms,
            "latency_p50_ms": ttft_ms,
            "latency_p95_ms": ttft_ms,
            "decode_tokens_per_second_p50": decode_speed,
            "decode_tokens_per_second_p95": decode_speed,
            "request_throughput_per_minute": Value::Null,
            "peak_vram_mb": result.metrics.peak_memory_bytes.map(|bytes| bytes as f64 / 1024.0 / 1024.0),
            "load_time_ms": load_time_ms,
            "oom_or_failure_rate": 0.0,
            "deployment_confidence": 0.25,
        },
        "capability": {
            "use_case": options.use_case,
            "capability_suite_id": "native_first_run_v1",
            "benchmark_tier": "native_first_run",
            "capability_state": "not_yet_benchmarked",
            "capability_score": Value::Null,
            "capability_status": "not_yet_benchmarked",
        },
        "cost": {
            "cost_source": "none",
            "benchmark_job_cost_included": false,
            "benchmark_job_cost_usd": Value::Null,
        },
        "derived": {
            "passes_capability_floor": false,
            "passes_verification_floor": false,
            "comparison_grade": "informational_only",
            "native_first_run": true,
            "canonical_analysis_slice_ids": [],
        },
        "provenance": {
            "submitter": "local_runner",
            "submission_channel": options.submission_channel,
            "source_bundle_origin": "infergrade_native_first_run",
            "normalized_at": created_at,
            "normalizer_version": env!("CARGO_PKG_VERSION"),
            "notes": "Native first-run evidence is useful local telemetry, not a full decision-grade benchmark.",
        },
    });
    json!({
        "manifest": {
            "bundle_spec_version": "0.1-draft",
            "result_spec_version": "0.1-draft",
            "bundle_id": bundle_id,
            "created_at": created_at,
            "runner": {
                "name": "infergrade-runner-engine",
                "version": env!("CARGO_PKG_VERSION"),
            },
            "status": {
                "execution_status": "completed",
                "deployment_status": result.status,
                "capability_status": "not_yet_benchmarked",
                "validation_status": "client_preview",
            },
            "files": {
                "results": ["results/native-first-run.json"],
                "environment": "artifacts/environment.json",
                "ontology": "artifacts/ontology.json",
                "validation": "validation.json",
                "summary": "summary.json",
            },
        },
        "results": [result_record],
        "summary": {
            "bundle_id": bundle_id,
            "result_count": 1,
            "result_ids": [result_id],
            "benchmark_subject_ids": [format!("native_first_run_{}", model_slug)],
            "checkpoints": [model_name],
            "model_families": [model_name],
            "deployment_profiles": [options.deployment_profile_id],
            "use_cases": [options.use_case],
            "verification_levels": ["experimental"],
            "comparison_grade_candidates": ["informational_only"],
            "created_at": created_at,
            "native_first_run": true,
            "uploaded": false,
        },
        "validation": {
            "client": {
                "valid": true,
                "bundle_id": bundle_id,
                "warnings": [
                    "native_first_run bundles remain experimental until Hub server validation accepts and labels them"
                ],
            }
        }
    })
}

fn native_first_run_timestamp() -> String {
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    format!("unix-{seconds}")
}

fn model_name_from_path(path: &str) -> String {
    Path::new(path)
        .file_stem()
        .and_then(|value| value.to_str())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or("local-gguf-model")
        .to_string()
}

fn slug_fragment(value: &str) -> String {
    let mut output = String::new();
    let mut last_was_separator = false;
    for ch in value.chars().flat_map(char::to_lowercase) {
        if ch.is_ascii_alphanumeric() {
            output.push(ch);
            last_was_separator = false;
        } else if !last_was_separator && !output.is_empty() {
            output.push('_');
            last_was_separator = true;
        }
    }
    while output.ends_with('_') {
        output.pop();
    }
    if output.is_empty() {
        "local_gguf_model".to_string()
    } else {
        output
    }
}

fn native_first_run_hardware_summary() -> Value {
    let accelerator_type = if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
        "metal"
    } else {
        "unknown"
    };
    json!({
        "hardware_id": format!("local_{}_{}", env::consts::OS, env::consts::ARCH),
        "environment_class": "local_native",
        "accelerator_type": accelerator_type,
        "accelerator_vendor": if accelerator_type == "metal" { "apple" } else { "unknown" },
        "accelerator_model": Value::Null,
        "accelerator_vram_gb": Value::Null,
        "accelerator_count": if accelerator_type == "unknown" { 0 } else { 1 },
        "cpu_model": Value::Null,
        "memory_gb": Value::Null,
        "os": env::consts::OS,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preview_is_bounded_and_redacts_sensitive_large_runtime_output() {
        let sensitive_line = "Authorization: Bearer igrt_runtime_preview_secret";
        let mut output = String::new();
        for index in 0..20_000 {
            output.push_str(&format!("llama.cpp diagnostic line {index}\n"));
        }
        output.push_str(sensitive_line);

        let preview = preview(&output, &[]);

        assert!(preview.len() <= PREVIEW_CHAR_LIMIT);
        assert!(preview.contains("[preview truncated]"));
        assert!(!preview.contains("igrt_runtime_preview_secret"));
        assert!(!preview.contains("Authorization: Bearer"));
    }
}
