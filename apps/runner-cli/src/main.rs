use infergrade_runner_engine::{
    container_runtime_readiness, llama_cpp_runtime_plan, normalize_api_url, run_native_first_run,
    NativeCommandRuntime, NativeFirstRunInput, NativeFirstRunRuntime, NativeRuntimeOutput,
};
use serde_json::{json, Value};
use std::env;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

fn print_help() {
    println!(
        "InferGrade Runner CLI\n\nUSAGE:\n    infergrade-runner <command>\n\nCOMMANDS:\n    doctor [--api-url <url>]                   Validate shared runner-engine basics\n    runtime plan                               Show native runtime plan as JSON\n    containers check                           Check optional Docker/Podman sandbox support\n    first-run --model <path> --no-upload --dry-run [--output-dir <dir>]\n                                               Validate and render the native first-run contract\n    first-run --model <path> --no-upload --runtime-command <path> [--output-dir <dir>]\n                                               Run an explicit native command adapter\n    help                                       Show this help\n\nThis Rust CLI is an early frontend over runner-engine. The Python runner-core CLI remains the execution bridge during migration."
    );
}

fn print_json(value: Value) {
    println!(
        "{}",
        serde_json::to_string_pretty(&value).expect("JSON rendering should not fail")
    );
}

fn command_doctor(args: &[String]) -> Result<Value, String> {
    let mut api_url = "";
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--api-url" => {
                index += 1;
                api_url = args
                    .get(index)
                    .ok_or_else(|| "--api-url requires a value".to_string())?;
            }
            unknown => return Err(format!("unknown doctor option: {unknown}")),
        }
        index += 1;
    }
    Ok(json!({
        "status": "ok",
        "engine": "infergrade_runner_engine",
        "api_url": normalize_api_url(api_url)?,
        "native_first_run": {
            "docker_required": false,
            "message": "Docker is optional for advanced sandboxed benchmarks; it does not gate the native first-run path."
        }
    }))
}

fn command_runtime(args: &[String]) -> Result<Value, String> {
    match args.first().map(String::as_str) {
        Some("plan") => Ok(llama_cpp_runtime_plan(json!({
            "status": "not_selected",
            "selection": Value::Null,
        }))),
        Some(other) => Err(format!("unknown runtime command: {other}")),
        None => Err("runtime requires a subcommand: plan".to_string()),
    }
}

fn command_containers(args: &[String]) -> Result<Value, String> {
    match args.first().map(String::as_str) {
        Some("check") => Ok(container_runtime_readiness()),
        Some(other) => Err(format!("unknown containers command: {other}")),
        None => Err("containers requires a subcommand: check".to_string()),
    }
}

struct DryRunRuntime;

impl NativeFirstRunRuntime for DryRunRuntime {
    fn run(&self, input: &NativeFirstRunInput) -> Result<NativeRuntimeOutput, String> {
        Ok(NativeRuntimeOutput {
            runtime_id: input
                .runtime_hint
                .clone()
                .unwrap_or_else(|| "dry-run-native-runtime".to_string()),
            stdout: format!(
                "Dry run only. Would run prompt {:?} for up to {} tokens.",
                input.prompt, input.max_tokens
            ),
            stderr: String::new(),
            exit_code: 0,
            load_time_ms: 0,
            time_to_first_token_ms: 0,
            decode_tokens_per_second: 0.0,
            generated_tokens: 0,
            peak_memory_bytes: None,
        })
    }
}

fn write_first_run_artifact(output_dir: &Path, payload: &Value) -> Result<String, String> {
    std::fs::create_dir_all(output_dir)
        .map_err(|error| format!("could not create output directory: {error}"))?;
    let artifact_path = output_dir.join("native-first-run-result.json");
    let rendered = serde_json::to_string_pretty(payload)
        .map_err(|error| format!("could not render first-run artifact: {error}"))?;
    std::fs::write(&artifact_path, rendered)
        .map_err(|error| format!("could not write first-run artifact: {error}"))?;
    Ok(artifact_path.display().to_string())
}

fn command_first_run(args: &[String]) -> Result<Value, String> {
    let mut model_path: Option<PathBuf> = None;
    let mut runtime_hint = Some("auto".to_string());
    let mut prompt = "Say hello in one sentence.".to_string();
    let mut max_tokens = 32_u32;
    let mut dry_run = false;
    let mut no_upload = false;
    let mut runtime_command: Option<PathBuf> = None;
    let mut output_dir: Option<PathBuf> = None;
    let mut index = 0;
    while index < args.len() {
        match args[index].as_str() {
            "--model" => {
                index += 1;
                model_path = Some(PathBuf::from(
                    args.get(index)
                        .ok_or_else(|| "--model requires a path".to_string())?,
                ));
            }
            "--runtime" => {
                index += 1;
                runtime_hint = Some(
                    args.get(index)
                        .ok_or_else(|| "--runtime requires a value".to_string())?
                        .to_string(),
                );
            }
            "--prompt" => {
                index += 1;
                prompt = args
                    .get(index)
                    .ok_or_else(|| "--prompt requires a value".to_string())?
                    .to_string();
            }
            "--max-tokens" => {
                index += 1;
                max_tokens = args
                    .get(index)
                    .ok_or_else(|| "--max-tokens requires a value".to_string())?
                    .parse::<u32>()
                    .map_err(|_| "--max-tokens must be a positive integer".to_string())?;
            }
            "--runtime-command" => {
                index += 1;
                runtime_command =
                    Some(PathBuf::from(args.get(index).ok_or_else(|| {
                        "--runtime-command requires a path".to_string()
                    })?));
            }
            "--output-dir" => {
                index += 1;
                output_dir = Some(PathBuf::from(
                    args.get(index)
                        .ok_or_else(|| "--output-dir requires a path".to_string())?,
                ));
            }
            "--dry-run" => dry_run = true,
            "--no-upload" => no_upload = true,
            unknown => return Err(format!("unknown first-run option: {unknown}")),
        }
        index += 1;
    }
    if !no_upload {
        return Err(
            "first-run currently requires --no-upload; upload is not implemented yet".to_string(),
        );
    }
    if dry_run && runtime_command.is_some() {
        return Err(
            "first-run accepts either --dry-run or --runtime-command, not both".to_string(),
        );
    }
    if !dry_run && runtime_command.is_none() {
        return Err("first-run requires --dry-run or --runtime-command; built-in llama.cpp execution is not implemented yet".to_string());
    }
    let input = NativeFirstRunInput {
        model_path: model_path.ok_or_else(|| "--model is required".to_string())?,
        runtime_hint,
        prompt,
        max_tokens,
        upload: false,
    };
    let (mode, execution, message, result) = if let Some(command_path) = runtime_command {
        let runtime_id = input
            .runtime_hint
            .clone()
            .unwrap_or_else(|| "native-command-runtime".to_string());
        let runtime = NativeCommandRuntime::new(command_path, runtime_id);
        (
            "runtime_command",
            "explicit_command",
            "Native first-run command adapter completed. This is not built-in llama.cpp support.",
            run_native_first_run(input, &runtime).map_err(|error| error.to_string())?,
        )
    } else {
        (
            "dry_run",
            "simulated",
            "Native first-run contract validated. Real llama.cpp execution is not implemented in this CLI slice.",
            run_native_first_run(input, &DryRunRuntime).map_err(|error| error.to_string())?,
        )
    };
    let mut payload = json!({
        "mode": mode,
        "execution": execution,
        "message": message,
        "result": result,
    });
    if let Some(output_dir) = output_dir {
        let artifact_path = write_first_run_artifact(&output_dir, &payload)?;
        payload["artifact"] = json!({
            "path": artifact_path,
            "format": "infergrade.native_first_run.v1",
            "uploaded": false,
        });
    }
    Ok(payload)
}

fn run(args: &[String]) -> Result<Option<Value>, String> {
    match args.first().map(String::as_str) {
        None | Some("--help") | Some("-h") | Some("help") => {
            print_help();
            Ok(None)
        }
        Some("doctor") => command_doctor(&args[1..]).map(Some),
        Some("runtime") => command_runtime(&args[1..]).map(Some),
        Some("containers") => command_containers(&args[1..]).map(Some),
        Some("first-run") => command_first_run(&args[1..]).map(Some),
        Some(other) => Err(format!("unknown command: {other}")),
    }
}

fn main() -> ExitCode {
    let args = env::args().skip(1).collect::<Vec<_>>();
    match run(&args) {
        Ok(Some(value)) => {
            print_json(value);
            ExitCode::SUCCESS
        }
        Ok(None) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("error: {error}\n");
            print_help();
            ExitCode::from(2)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn doctor_normalizes_default_api_url_and_keeps_docker_optional() {
        let output = command_doctor(&[]).expect("doctor output");
        assert_eq!(output["api_url"], "https://api.infergrade.com/");
        assert_eq!(output["native_first_run"]["docker_required"], false);
    }

    #[test]
    fn runtime_plan_uses_shared_engine() {
        let output = command_runtime(&["plan".to_string()]).expect("runtime plan");
        assert_eq!(output["runtime_family"], "llama.cpp");
        assert_eq!(
            output["download_policy"]["requires_explicit_user_action"],
            true
        );
    }

    #[test]
    fn containers_check_uses_shared_engine_and_keeps_first_run_native() {
        let output = command_containers(&["check".to_string()]).expect("containers check");
        assert_eq!(output["docker_required_for_first_run"], false);
        assert_eq!(
            output["runtimes"]["docker"]["capability"],
            "advanced_sandboxed_benchmarks"
        );
        assert!(output["runtimes"]["docker"].get("cli").is_some());
        assert!(output["runtimes"]["docker"].get("daemon").is_some());
        assert_eq!(output["runtimes"]["podman"]["first_run_required"], false);
    }

    #[test]
    fn first_run_dry_run_validates_model_and_marks_simulated_no_upload() {
        let model_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-first-run-{}.gguf",
            std::process::id()
        ));
        std::fs::write(&model_path, b"fake gguf path validation only").expect("model file");

        let output = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--no-upload".to_string(),
            "--dry-run".to_string(),
        ])
        .expect("first-run dry-run output");

        assert_eq!(output["mode"], "dry_run");
        assert_eq!(output["execution"], "simulated");
        assert_eq!(output["result"]["evidence_kind"], "native_first_run");
        assert_eq!(output["result"]["uploaded"], false);
        assert_eq!(output["result"]["metrics"]["generated_tokens"], 0);

        let _ = std::fs::remove_file(model_path);
    }

    #[test]
    fn first_run_rejects_real_execution_until_runtime_adapter_exists() {
        let error = command_first_run(&[
            "--model".to_string(),
            "model.gguf".to_string(),
            "--no-upload".to_string(),
        ])
        .expect_err("real execution rejected");

        assert!(error.contains("requires --dry-run or --runtime-command"));
    }

    #[test]
    fn first_run_runtime_command_executes_explicit_adapter_metrics() {
        let model_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-runtime-command-model-{}.gguf",
            std::process::id()
        ));
        let extension = if cfg!(windows) { "cmd" } else { "sh" };
        let runtime_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-runtime-command-{}.{}",
            std::process::id(),
            extension
        ));
        std::fs::write(&model_path, b"fake gguf path validation only").expect("model file");
        if cfg!(windows) {
            std::fs::write(
                &runtime_path,
                "@echo off\r\necho INFERGRADE_NATIVE_FIRST_RUN_METRICS {\"load_time_ms\":12,\"time_to_first_token_ms\":3,\"decode_tokens_per_second\":4.5,\"generated_tokens\":6,\"peak_memory_bytes\":789}\r\n",
            )
            .expect("runtime script");
        } else {
            use std::os::unix::fs::PermissionsExt;
            std::fs::write(
                &runtime_path,
                "#!/bin/sh\necho 'INFERGRADE_NATIVE_FIRST_RUN_METRICS {\"load_time_ms\":12,\"time_to_first_token_ms\":3,\"decode_tokens_per_second\":4.5,\"generated_tokens\":6,\"peak_memory_bytes\":789}'\n",
            )
            .expect("runtime script");
            let mut permissions = std::fs::metadata(&runtime_path)
                .expect("runtime metadata")
                .permissions();
            permissions.set_mode(0o755);
            std::fs::set_permissions(&runtime_path, permissions).expect("runtime executable");
        }

        let output = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "explicit-test-runtime".to_string(),
            "--no-upload".to_string(),
            "--runtime-command".to_string(),
            runtime_path.display().to_string(),
        ])
        .expect("first-run runtime-command output");

        assert_eq!(output["mode"], "runtime_command");
        assert_eq!(output["execution"], "explicit_command");
        assert_eq!(output["result"]["runtime_id"], "explicit-test-runtime");
        assert_eq!(output["result"]["uploaded"], false);
        assert_eq!(output["result"]["metrics"]["generated_tokens"], 6);
        assert_eq!(output["result"]["metrics"]["decode_tokens_per_second"], 4.5);

        let _ = std::fs::remove_file(model_path);
        let _ = std::fs::remove_file(runtime_path);
    }

    #[test]
    fn first_run_output_dir_writes_local_no_upload_artifact() {
        let model_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-artifact-model-{}.gguf",
            std::process::id()
        ));
        let output_dir = env::temp_dir().join(format!(
            "infergrade-runner-cli-artifact-dir-{}",
            std::process::id()
        ));
        std::fs::write(&model_path, b"fake gguf path validation only").expect("model file");
        let _ = std::fs::remove_dir_all(&output_dir);

        let output = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--no-upload".to_string(),
            "--dry-run".to_string(),
            "--output-dir".to_string(),
            output_dir.display().to_string(),
        ])
        .expect("first-run artifact output");

        assert_eq!(output["artifact"]["uploaded"], false);
        assert_eq!(
            output["artifact"]["format"],
            "infergrade.native_first_run.v1"
        );
        let artifact_path = output["artifact"]["path"].as_str().expect("artifact path");
        let artifact = std::fs::read_to_string(artifact_path).expect("artifact JSON");
        let artifact_json: Value = serde_json::from_str(&artifact).expect("artifact parses");
        assert_eq!(artifact_json["mode"], "dry_run");
        assert_eq!(artifact_json["result"]["uploaded"], false);
        assert_eq!(artifact_json.get("artifact"), None);

        let _ = std::fs::remove_file(model_path);
        let _ = std::fs::remove_dir_all(output_dir);
    }
}
