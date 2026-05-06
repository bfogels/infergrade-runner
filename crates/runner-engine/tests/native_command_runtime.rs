use infergrade_runner_engine::{run_native_first_run, NativeCommandRuntime, NativeFirstRunInput};
use std::path::{Path, PathBuf};

fn temp_path(name: &str, extension: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "infergrade-native-command-runtime-{name}-{}.{extension}",
        std::process::id()
    ))
}

#[cfg(unix)]
fn write_executable(path: &Path, body: &str) {
    use std::os::unix::fs::PermissionsExt;

    std::fs::write(path, body).expect("fake runtime script");
    let mut permissions = std::fs::metadata(path)
        .expect("script metadata")
        .permissions();
    permissions.set_mode(0o755);
    std::fs::set_permissions(path, permissions).expect("script executable");
}

#[cfg(windows)]
fn write_executable(path: &Path, body: &str) {
    std::fs::write(path, body).expect("fake runtime script");
}

#[test]
fn native_command_runtime_executes_process_and_reads_metric_envelope() {
    let extension = if cfg!(windows) { "cmd" } else { "sh" };
    let runtime_path = temp_path("runtime-ok", extension);
    let model_path = temp_path("model", "gguf");
    std::fs::write(&model_path, b"fake model").expect("model file");

    if cfg!(windows) {
        write_executable(
            &runtime_path,
            "@echo off\r\necho generated hello\r\necho INFERGRADE_NATIVE_FIRST_RUN_METRICS {\"load_time_ms\":321,\"time_to_first_token_ms\":45,\"decode_tokens_per_second\":67.5,\"generated_tokens\":9,\"peak_memory_bytes\":123456}\r\n",
        );
    } else {
        write_executable(
            &runtime_path,
            "#!/bin/sh\necho generated hello\necho 'INFERGRADE_NATIVE_FIRST_RUN_METRICS {\"load_time_ms\":321,\"time_to_first_token_ms\":45,\"decode_tokens_per_second\":67.5,\"generated_tokens\":9,\"peak_memory_bytes\":123456}'\n",
        );
    }

    let result = run_native_first_run(
        NativeFirstRunInput {
            model_path: model_path.clone(),
            runtime_hint: Some("fake-native-runtime".to_string()),
            prompt: "hello".to_string(),
            max_tokens: 9,
            upload: false,
        },
        &NativeCommandRuntime::new(runtime_path.clone(), "fake-native-runtime"),
    )
    .expect("command runtime result");

    assert_eq!(result.runtime_id, "fake-native-runtime");
    assert_eq!(result.metrics.load_time_ms, 321);
    assert_eq!(result.metrics.time_to_first_token_ms, 45);
    assert_eq!(result.metrics.decode_tokens_per_second, 67.5);
    assert_eq!(result.metrics.generated_tokens, 9);
    assert_eq!(result.metrics.peak_memory_bytes, Some(123456));
    assert!(result.stdout_preview.contains("generated hello"));
    assert!(result
        .stdout_preview
        .contains("INFERGRADE_NATIVE_FIRST_RUN_METRICS"));

    let _ = std::fs::remove_file(runtime_path);
    let _ = std::fs::remove_file(model_path);
}

#[test]
fn native_command_runtime_requires_metric_envelope() {
    let extension = if cfg!(windows) { "cmd" } else { "sh" };
    let runtime_path = temp_path("runtime-no-metrics", extension);
    let model_path = temp_path("model-no-metrics", "gguf");
    std::fs::write(&model_path, b"fake model").expect("model file");

    if cfg!(windows) {
        write_executable(&runtime_path, "@echo off\r\necho no metrics\r\n");
    } else {
        write_executable(&runtime_path, "#!/bin/sh\necho no metrics\n");
    }

    let error = run_native_first_run(
        NativeFirstRunInput {
            model_path: model_path.clone(),
            runtime_hint: None,
            prompt: "hello".to_string(),
            max_tokens: 9,
            upload: false,
        },
        &NativeCommandRuntime::new(runtime_path.clone(), "fake-native-runtime"),
    )
    .expect_err("missing metric envelope rejected");

    assert_eq!(error.code(), "native_runtime_failed");
    assert!(error.message().contains("metric envelope"));

    let _ = std::fs::remove_file(runtime_path);
    let _ = std::fs::remove_file(model_path);
}
