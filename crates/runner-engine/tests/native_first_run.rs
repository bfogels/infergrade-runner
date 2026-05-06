use infergrade_runner_engine::{
    run_native_first_run, NativeFirstRunInput, NativeFirstRunRuntime, NativeRuntimeOutput,
};
use std::path::PathBuf;

struct FakeRuntime;

impl NativeFirstRunRuntime for FakeRuntime {
    fn run(&self, input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String> {
        Ok(NativeRuntimeOutput {
            runtime_id: "fake-llama-cpp-metal".to_string(),
            stdout: format!("prompt={}", input.prompt),
            stderr: String::new(),
            exit_code: 0,
            load_time_ms: 1200,
            time_to_first_token_ms: 180,
            decode_tokens_per_second: 42.5,
            generated_tokens: 32,
            peak_memory_bytes: Some(2_147_483_648),
        })
    }
}

fn temp_model_path(name: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "infergrade-runner-engine-test-{name}-{}-{}.gguf",
        std::process::id(),
        std::thread::current().name().unwrap_or("thread")
    ))
}

#[test]
fn native_first_run_uses_fake_runtime_and_labels_no_upload_evidence() {
    let model_path = temp_model_path("ok");
    std::fs::write(&model_path, b"not a real model, only path validation").expect("model file");

    let result = run_native_first_run(
        NativeFirstRunInput {
            model_path: model_path.clone(),
            runtime_hint: Some("llama.cpp-metal".to_string()),
            prompt: "Say hello in one sentence.".to_string(),
            max_tokens: 32,
            upload: false,
        },
        &FakeRuntime,
    )
    .expect("native first run result");

    assert_eq!(result.status, "completed");
    assert_eq!(result.evidence_kind, "native_first_run");
    assert_eq!(result.uploaded, false);
    assert_eq!(result.model_path, model_path.display().to_string());
    assert_eq!(result.runtime_id, "fake-llama-cpp-metal");
    assert_eq!(result.metrics.decode_tokens_per_second, 42.5);
    assert_eq!(result.metrics.time_to_first_token_ms, 180);
    assert_eq!(result.metrics.generated_tokens, 32);

    let _ = std::fs::remove_file(model_path);
}

#[test]
fn native_first_run_rejects_missing_model_before_runtime_execution() {
    let missing_model = temp_model_path("missing");
    let error = run_native_first_run(
        NativeFirstRunInput {
            model_path: missing_model,
            runtime_hint: None,
            prompt: "hello".to_string(),
            max_tokens: 16,
            upload: false,
        },
        &FakeRuntime,
    )
    .expect_err("missing model is rejected");

    assert_eq!(error.code(), "model_path_missing");
    assert!(error.message().contains("Select a local GGUF model"));
}
