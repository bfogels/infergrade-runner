use crate::{RunnerError, RunnerEvent};
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

fn run_process_with_timeout(mut command: Command, timeout: Duration) -> Result<ProcessRun, String> {
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
                preview(&stdout.text),
                preview(&stderr.text)
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
        let output = run_process_with_timeout(command, self.timeout).map_err(|error| {
            format!(
                "could not invoke native runtime `{}`: {error}",
                self.command_path.display()
            )
        })?;
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
        let mut command = Command::new(&self.command_path);
        command
            .arg("-m")
            .arg(&input.model_path)
            .arg("-p")
            .arg(&input.prompt)
            .arg("-n")
            .arg(input.max_tokens.to_string())
            .arg("--no-display-prompt");
        let output = run_process_with_timeout(command, self.timeout).map_err(|error| {
            format!(
                "could not invoke llama.cpp runtime `{}`: {error}",
                self.command_path.display()
            )
        })?;
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
        let generated_tokens = timing_u32(timings.eval_tokens, "eval tokens")?;
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
                preview(&output.stdout),
                preview(&output.stderr)
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
        stdout_preview: preview(&output.stdout),
        stderr_preview: preview(&output.stderr),
    };
    emit(RunnerEvent::BenchmarkCompleted {
        benchmark_id: NATIVE_FIRST_RUN_BENCHMARK_ID.to_string(),
    });
    Ok(result)
}
