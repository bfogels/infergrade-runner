use crate::RunnerError;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

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
            format!("Native first-run runtime exited with code {}.", output.exit_code),
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
