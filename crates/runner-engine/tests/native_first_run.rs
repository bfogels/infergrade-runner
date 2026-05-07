use infergrade_runner_engine::{
    native_first_run_bundle_payload, run_native_first_run, run_native_first_run_with_events,
    write_native_first_run_artifact, NativeFirstRunBundleOptions, NativeFirstRunInput,
    NativeFirstRunMetrics, NativeFirstRunResult, NativeFirstRunRuntime, NativeRuntimeOutput,
    RunnerEvent,
};
use serde_json::{json, Value};
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

struct PanicRuntime;

impl NativeFirstRunRuntime for PanicRuntime {
    fn run(&self, _input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String> {
        panic!("runtime should not execute when input validation fails")
    }
}

struct InvalidMetricsRuntime;

impl NativeFirstRunRuntime for InvalidMetricsRuntime {
    fn run(&self, _input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String> {
        Ok(NativeRuntimeOutput {
            runtime_id: "fake-llama-cpp-metal".to_string(),
            stdout: "generated text".to_string(),
            stderr: String::new(),
            exit_code: 0,
            load_time_ms: 1200,
            time_to_first_token_ms: 180,
            decode_tokens_per_second: f64::INFINITY,
            generated_tokens: 33,
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
fn native_first_run_emits_typed_progress_events() {
    let model_path = temp_model_path("events-ok");
    std::fs::write(&model_path, b"not a real model, only path validation").expect("model file");
    let mut events = Vec::new();

    let result = run_native_first_run_with_events(
        NativeFirstRunInput {
            model_path: model_path.clone(),
            runtime_hint: Some("llama.cpp-metal".to_string()),
            prompt: "Say hello in one sentence.".to_string(),
            max_tokens: 32,
            upload: false,
        },
        &FakeRuntime,
        |event| events.push(event),
    )
    .expect("native first run result");

    assert_eq!(result.status, "completed");
    assert!(matches!(
        events.first(),
        Some(RunnerEvent::BenchmarkStarted { benchmark_id })
            if benchmark_id == "native_first_run"
    ));
    assert!(events.iter().any(|event| matches!(
        event,
        RunnerEvent::BenchmarkProgress {
            benchmark_id,
            progress_percent: Some(80.0),
            ..
        } if benchmark_id == "native_first_run"
    )));
    assert!(matches!(
        events.last(),
        Some(RunnerEvent::BenchmarkCompleted { benchmark_id })
            if benchmark_id == "native_first_run"
    ));

    let _ = std::fs::remove_file(model_path);
}

#[test]
fn native_first_run_writes_local_no_upload_artifact_without_recursion() {
    let output_dir = temp_model_path("artifact-dir");
    let _ = std::fs::remove_dir_all(&output_dir);
    let payload = json!({
        "mode": "llama_cpp",
        "execution": "local_native",
        "result": {
            "evidence_kind": "native_first_run",
            "uploaded": false,
        }
    });

    let artifact =
        write_native_first_run_artifact(&output_dir, &payload).expect("artifact written");

    assert_eq!(artifact.format, "infergrade.native_first_run.v1");
    assert_eq!(artifact.uploaded, false);
    let artifact_text = std::fs::read_to_string(&artifact.path).expect("artifact text");
    let artifact_json: Value = serde_json::from_str(&artifact_text).expect("artifact JSON");
    assert_eq!(artifact_json["execution"], "local_native");
    assert_eq!(artifact_json["result"]["evidence_kind"], "native_first_run");
    assert_eq!(artifact_json["result"]["uploaded"], false);
    assert_eq!(artifact_json.get("artifact"), None);

    let _ = std::fs::remove_dir_all(output_dir);
}

#[test]
fn native_first_run_builds_hub_bundle_payload_with_experimental_evidence() {
    let result = NativeFirstRunResult {
        status: "completed".to_string(),
        evidence_kind: "native_first_run".to_string(),
        uploaded: false,
        model_path: "/models/Qwen2.5-Coder-14B-Q4_K_M.gguf".to_string(),
        runtime_id: "llama.cpp-auto".to_string(),
        runtime_hint: Some("auto".to_string()),
        metrics: NativeFirstRunMetrics {
            load_time_ms: 1200,
            time_to_first_token_ms: 250,
            decode_tokens_per_second: 42.5,
            generated_tokens: 32,
            peak_memory_bytes: Some(2_147_483_648),
        },
        stdout_preview: "hello".to_string(),
        stderr_preview: String::new(),
    };

    let payload = native_first_run_bundle_payload(
        &result,
        NativeFirstRunBundleOptions {
            bundle_id: Some("nfr_test_bundle".to_string()),
            created_at: Some("2026-05-06T00:00:00Z".to_string()),
            deployment_profile_id: "interactive_chat_v1".to_string(),
            use_case: "general_assistant".to_string(),
            submission_channel: "test".to_string(),
        },
    );

    assert_eq!(payload["manifest"]["bundle_id"], "nfr_test_bundle");
    assert_eq!(
        payload["manifest"]["files"]["results"][0],
        "results/native-first-run.json"
    );
    assert_eq!(payload["summary"]["native_first_run"], true);
    assert_eq!(payload["summary"]["uploaded"], false);
    assert_eq!(payload["summary"]["created_at"], "2026-05-06T00:00:00Z");
    assert_eq!(
        payload["summary"]["comparison_grade_candidates"][0],
        "informational_only"
    );
    let record = &payload["results"][0];
    assert_eq!(record["bundle_id"], "nfr_test_bundle");
    assert_eq!(record["result_id"], "nfr_test_bundle_interactive_chat_v1");
    assert_eq!(record["configuration"]["backend_engine"], "llama.cpp");
    assert_eq!(record["configuration"]["backend_version"], "unverified");
    assert_eq!(record["verification"]["verification_level"], "experimental");
    assert_eq!(record["verification"]["artifact_pinned"], false);
    assert_eq!(record["verification"]["backend_version_pinned"], false);
    assert!(record["verification"]["missing_requirements"]
        .as_array()
        .expect("missing requirements")
        .iter()
        .any(|item| item == "backend_version_pinned"));
    assert_eq!(record["deployment"]["decode_tokens_per_second_p50"], 42.5);
    assert_eq!(record["deployment"]["ttft_p50_ms"], 250.0);
    assert_eq!(
        record["capability"]["capability_state"],
        "not_yet_benchmarked"
    );
    assert_eq!(record["derived"]["comparison_grade"], "informational_only");
    assert_eq!(
        record["provenance"]["source_bundle_origin"],
        "infergrade_native_first_run"
    );
    let rendered = serde_json::to_string(&payload).expect("payload JSON");
    assert!(!rendered.contains("/tmp/model.gguf"));
    assert!(!rendered.to_ascii_lowercase().contains("runner_token"));
    assert!(!rendered.to_ascii_lowercase().contains("access_token"));
}

#[test]
fn native_first_run_emits_error_event_on_validation_failure() {
    let missing_model = temp_model_path("events-missing");
    let mut events = Vec::new();

    let error = run_native_first_run_with_events(
        NativeFirstRunInput {
            model_path: missing_model,
            runtime_hint: None,
            prompt: "hello".to_string(),
            max_tokens: 16,
            upload: false,
        },
        &PanicRuntime,
        |event| events.push(event),
    )
    .expect_err("missing model is rejected");

    assert_eq!(error.code(), "model_path_missing");
    assert!(events.iter().any(|event| matches!(
        event,
        RunnerEvent::BenchmarkStarted { benchmark_id }
            if benchmark_id == "native_first_run"
    )));
    assert!(!events
        .iter()
        .any(|event| matches!(event, RunnerEvent::BenchmarkCompleted { .. })));
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
        &PanicRuntime,
    )
    .expect_err("missing model is rejected");

    assert_eq!(error.code(), "model_path_missing");
    assert!(error.message().contains("Select a local GGUF model"));
}

#[test]
fn native_first_run_rejects_invalid_runtime_metrics() {
    let model_path = temp_model_path("invalid-metrics");
    std::fs::write(&model_path, b"not a real model, only path validation").expect("model file");

    let error = run_native_first_run(
        NativeFirstRunInput {
            model_path: model_path.clone(),
            runtime_hint: Some("llama.cpp-metal".to_string()),
            prompt: "Say hello in one sentence.".to_string(),
            max_tokens: 32,
            upload: false,
        },
        &InvalidMetricsRuntime,
    )
    .expect_err("invalid runtime metrics are rejected");

    assert_eq!(error.code(), "native_runtime_invalid_metrics");
    assert!(error.message().contains("decode speed"));

    let _ = std::fs::remove_file(model_path);
}
