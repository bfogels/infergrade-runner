use infergrade_runner_engine::{
    run_native_first_run, LlamaCppRuntime, NativeCommandRuntime, NativeFirstRunInput,
};
use std::path::{Path, PathBuf};
use std::time::Duration;

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
fn native_command_runtime_drains_chatty_success_before_metric_envelope() {
    let extension = if cfg!(windows) { "cmd" } else { "sh" };
    let runtime_path = temp_path("runtime-chatty", extension);
    let model_path = temp_path("model-chatty", "gguf");
    std::fs::write(&model_path, b"fake model").expect("model file");

    if cfg!(windows) {
        write_executable(
            &runtime_path,
            "@echo off\r\nfor /L %%i in (1,1,6000) do echo chatty-line-%%i-abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz\r\necho INFERGRADE_NATIVE_FIRST_RUN_METRICS {\"load_time_ms\":321,\"time_to_first_token_ms\":45,\"decode_tokens_per_second\":67.5,\"generated_tokens\":9,\"peak_memory_bytes\":123456}\r\n",
        );
    } else {
        write_executable(
            &runtime_path,
            "#!/bin/sh\ni=0\nwhile [ \"$i\" -lt 6000 ]; do echo \"chatty-line-$i-abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuvwxyz\"; i=$((i + 1)); done\necho 'INFERGRADE_NATIVE_FIRST_RUN_METRICS {\"load_time_ms\":321,\"time_to_first_token_ms\":45,\"decode_tokens_per_second\":67.5,\"generated_tokens\":9,\"peak_memory_bytes\":123456}'\n",
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
        &NativeCommandRuntime::new(runtime_path.clone(), "fake-native-runtime")
            .with_timeout(Duration::from_secs(5)),
    )
    .expect("chatty runtime should not block on a full pipe");

    assert_eq!(result.metrics.generated_tokens, 9);
    assert!(result.stdout_preview.len() <= 2_000);
    assert!(result.stdout_preview.contains("chatty-line"));

    let _ = std::fs::remove_file(runtime_path);
    let _ = std::fs::remove_file(model_path);
}

#[test]
fn llama_cpp_runtime_executes_cli_and_parses_timings() {
    let extension = if cfg!(windows) { "cmd" } else { "sh" };
    let runtime_path = temp_path("llama-cli-ok", extension);
    let model_path = temp_path("llama-model", "gguf");
    std::fs::write(&model_path, b"fake model").expect("model file");

    if cfg!(windows) {
        write_executable(
            &runtime_path,
            "@echo off\r\necho hello from llama\r\necho llama_print_timings:        load time =     617.57 ms 1>&2\r\necho llama_print_timings:        eval time =    1285.25 ms /    9 runs   (40.16 ms per token, 24.90 tokens per second) 1>&2\r\necho llama_print_timings:       total time =    1901.48 ms /    12 tokens 1>&2\r\n",
        );
    } else {
        write_executable(
            &runtime_path,
            "#!/bin/sh\necho 'hello from llama'\necho 'llama_print_timings:        load time =     617.57 ms' >&2\necho 'llama_print_timings:        eval time =    1285.25 ms /    9 runs   (40.16 ms per token, 24.90 tokens per second)' >&2\necho 'llama_print_timings:       total time =    1901.48 ms /    12 tokens' >&2\n",
        );
    }

    let result = run_native_first_run(
        NativeFirstRunInput {
            model_path: model_path.clone(),
            runtime_hint: Some("auto".to_string()),
            prompt: "hello".to_string(),
            max_tokens: 9,
            upload: false,
        },
        &LlamaCppRuntime::new(runtime_path.clone(), "llama.cpp-test")
            .with_timeout(Duration::from_secs(5)),
    )
    .expect("llama.cpp runtime result");

    assert_eq!(result.runtime_id, "llama.cpp-test");
    assert_eq!(result.metrics.load_time_ms, 618);
    assert_eq!(result.metrics.generated_tokens, 9);
    assert_eq!(result.metrics.decode_tokens_per_second, 24.9);
    assert!(result.metrics.time_to_first_token_ms <= result.metrics.load_time_ms);
    assert!(result.stdout_preview.contains("hello from llama"));

    let _ = std::fs::remove_file(runtime_path);
    let _ = std::fs::remove_file(model_path);
}

#[test]
fn llama_cpp_runtime_disables_prompt_echo_before_measuring_ttft() {
    let extension = if cfg!(windows) { "cmd" } else { "sh" };
    let runtime_path = temp_path("llama-cli-no-prompt", extension);
    let model_path = temp_path("llama-model-no-prompt", "gguf");
    let args_path = temp_path("llama-args-no-prompt", "txt");
    std::fs::write(&model_path, b"fake model").expect("model file");

    if cfg!(windows) {
        write_executable(
            &runtime_path,
            &format!(
                "@echo off\r\necho %* > \"{}\"\r\ntimeout /t 1 /nobreak > nul\r\necho generated token\r\necho llama_print_timings:        load time =     1500.00 ms 1>&2\r\necho llama_print_timings:        eval time =    1000.00 ms /    4 runs   (250.00 ms per token, 4.00 tokens per second) 1>&2\r\n",
                args_path.display()
            ),
        );
    } else {
        write_executable(
            &runtime_path,
            &format!(
                "#!/bin/sh\nprintf '%s\\n' \"$*\" > '{}'\nsleep 1\necho 'generated token'\necho 'llama_print_timings:        load time =     1500.00 ms' >&2\necho 'llama_print_timings:        eval time =    1000.00 ms /    4 runs   (250.00 ms per token, 4.00 tokens per second)' >&2\n",
                args_path.display()
            ),
        );
    }

    let result = run_native_first_run(
        NativeFirstRunInput {
            model_path: model_path.clone(),
            runtime_hint: Some("auto".to_string()),
            prompt: "prompt that must not be echoed".to_string(),
            max_tokens: 4,
            upload: false,
        },
        &LlamaCppRuntime::new(runtime_path.clone(), "llama.cpp-test")
            .with_timeout(Duration::from_secs(5)),
    )
    .expect("llama.cpp no-display-prompt result");

    let args = std::fs::read_to_string(&args_path).expect("runtime args");
    assert!(args.contains("--no-display-prompt"));
    assert!(!result
        .stdout_preview
        .contains("prompt that must not be echoed"));
    assert!(result.metrics.time_to_first_token_ms >= 900);

    let _ = std::fs::remove_file(runtime_path);
    let _ = std::fs::remove_file(model_path);
    let _ = std::fs::remove_file(args_path);
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

#[test]
fn native_command_runtime_times_out_and_redacts_sensitive_previews() {
    let extension = if cfg!(windows) { "cmd" } else { "sh" };
    let runtime_path = temp_path("runtime-timeout", extension);
    let model_path = temp_path("model-timeout", "gguf");
    std::fs::write(&model_path, b"fake model").expect("model file");
    std::env::set_var("INFERGRADE_NATIVE_TEST_TOKEN", "igrt_timeout_secret_value");

    if cfg!(windows) {
        write_executable(
            &runtime_path,
            "@echo off\r\necho Authorization: Bearer igrt_timeout_secret_value\r\nping -n 3 127.0.0.1 > nul\r\n",
        );
    } else {
        write_executable(
            &runtime_path,
            "#!/bin/sh\necho 'Authorization: Bearer igrt_timeout_secret_value'\nsleep 2\n",
        );
    }

    let error = run_native_first_run(
        NativeFirstRunInput {
            model_path: model_path.clone(),
            runtime_hint: None,
            prompt: "hello".to_string(),
            max_tokens: 9,
            upload: false,
        },
        &NativeCommandRuntime::new(runtime_path.clone(), "fake-native-runtime")
            .with_timeout(Duration::from_millis(50)),
    )
    .expect_err("timeout rejected");

    assert_eq!(error.code(), "native_runtime_failed");
    assert!(error.message().contains("timed out"));
    assert!(!error.message().contains("igrt_timeout_secret_value"));

    std::env::remove_var("INFERGRADE_NATIVE_TEST_TOKEN");
    let _ = std::fs::remove_file(runtime_path);
    let _ = std::fs::remove_file(model_path);
}

#[test]
fn native_command_runtime_redacts_nonzero_failure_previews() {
    let extension = if cfg!(windows) { "cmd" } else { "sh" };
    let runtime_path = temp_path("runtime-secret-failure", extension);
    let model_path = temp_path("model-secret-failure", "gguf");
    std::fs::write(&model_path, b"fake model").expect("model file");
    std::env::set_var("INFERGRADE_NATIVE_TEST_TOKEN", "igrt_failure_secret_value");

    if cfg!(windows) {
        write_executable(
            &runtime_path,
            "@echo off\r\necho Authorization: Bearer igrt_failure_secret_value\r\necho x-access-token=igrt_failure_secret_value 1>&2\r\nexit /b 7\r\n",
        );
    } else {
        write_executable(
            &runtime_path,
            "#!/bin/sh\necho 'Authorization: Bearer igrt_failure_secret_value'\necho 'x-access-token=igrt_failure_secret_value' >&2\nexit 7\n",
        );
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
    .expect_err("nonzero runtime exit rejected");

    assert_eq!(error.code(), "native_runtime_failed");
    assert!(error.message().contains("exited with code"));
    assert!(!error.message().contains("igrt_failure_secret_value"));
    assert!(error.message().contains("[redacted sensitive output line]"));

    std::env::remove_var("INFERGRADE_NATIVE_TEST_TOKEN");
    let _ = std::fs::remove_file(runtime_path);
    let _ = std::fs::remove_file(model_path);
}

#[test]
fn native_command_runtime_rejects_metric_values_that_do_not_fit_contract() {
    let extension = if cfg!(windows) { "cmd" } else { "sh" };
    let runtime_path = temp_path("runtime-bad-metrics", extension);
    let model_path = temp_path("model-bad-metrics", "gguf");
    std::fs::write(&model_path, b"fake model").expect("model file");

    if cfg!(windows) {
        write_executable(
            &runtime_path,
            "@echo off\r\necho INFERGRADE_NATIVE_FIRST_RUN_METRICS {\"load_time_ms\":1,\"time_to_first_token_ms\":1,\"decode_tokens_per_second\":2.0,\"generated_tokens\":4294967296,\"peak_memory_bytes\":null}\r\n",
        );
    } else {
        write_executable(
            &runtime_path,
            "#!/bin/sh\necho 'INFERGRADE_NATIVE_FIRST_RUN_METRICS {\"load_time_ms\":1,\"time_to_first_token_ms\":1,\"decode_tokens_per_second\":2.0,\"generated_tokens\":4294967296,\"peak_memory_bytes\":null}'\n",
        );
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
    .expect_err("oversized generated token count rejected");

    assert_eq!(error.code(), "native_runtime_failed");
    assert!(error.message().contains("generated_tokens"));
    assert!(error.message().contains("too large"));

    let _ = std::fs::remove_file(runtime_path);
    let _ = std::fs::remove_file(model_path);
}
