use infergrade_runner_engine::{
    activate_runtime_catalog, build_run_bundle_upload_request, build_run_claim_request,
    build_run_completion_request, build_support_summary, container_runtime_readiness,
    execute_hub_json_request, install_active_runtime_catalog_target,
    install_managed_llama_cpp_runtime, install_runtime_catalog_target, llama_cpp_runtime_plan,
    llama_cpp_runtime_status, load_selected_llama_cpp_runtime, managed_llama_cpp_runtime_channels,
    managed_llama_cpp_runtime_manifest, native_first_run_bundle_payload, normalize_api_url,
    refresh_default_runtime_catalog, rollback_selected_llama_cpp_runtime,
    run_native_first_run_with_events, select_existing_llama_cpp_runtime,
    write_native_first_run_artifact, write_native_first_run_bundle_payload, LlamaCppRuntime,
    ManagedRuntimeInstallOptions, NativeCommandRuntime, NativeFirstRunBundleOptions,
    NativeFirstRunInput, NativeFirstRunResult, NativeFirstRunRuntime, NativeRuntimeOutput,
    RunnerEvent, RuntimeCatalogFiles,
};
use serde_json::{json, Value};
use std::env;
use std::io::{self, Write};
use std::path::PathBuf;
use std::process::ExitCode;

const HELP_TEXT: &str =
    "InferGrade Runner CLI\n\nUSAGE:\n    infergrade-runner <command>\n\nCOMMANDS:\n    doctor [--api-url <url>]                   Validate shared runner-engine basics\n    runtime plan                               Show native runtime plan as JSON\n    runtime list                               Show the managed llama.cpp runtime manifest as JSON\n    runtime channels                           Show managed/local/experimental runtime channel policy as JSON\n    runtime status                             Show selected/detected/managed runtime status as JSON\n    runtime install [--runtime-id <id>]        Explicitly download, verify, extract, smoke, and select a managed llama.cpp runtime\n    runtime catalog-refresh [--url <https-url>]\n                                               Refresh signed metadata or use unexpired last-known-good metadata\n    runtime catalog-use --target <name> --consent-build <sha256>\n                                               Download and select one exact signed-catalog runtime\n    runtime catalog-verify --catalog-dir <dir> --pinned-root <file> --cache-dir <dir>\n                                               Verify and atomically cache signed runtime metadata\n    runtime catalog-install --catalog-dir <dir> --pinned-root <file> --cache-dir <dir> --target <name> --consent-build <sha256> [--archive <file>]\n                                               Install one local signed-catalog runtime after exact-build consent\n    runtime rollback --runtime-build-id <sha256>\n                                               Re-select an exact installed immutable rollback build\n    runtime select-existing --runtime-path <path>\n                                               Record an existing llama.cpp runtime without running an install command\n    containers check                           Check optional Docker/Podman sandbox support\n    support summary [--first-run-artifact <path>] [--error <text>]\n                                               Print a secret-free support summary with runtime, pairing, first-run, and upload recovery hints\n    first-run --model <path> --runtime auto --no-upload [--runtime-path <path>] [--output-dir <dir>] [--json|--jsonl]\n                                               Run the built-in native llama.cpp first-run adapter locally\n    first-run --model <path> --runtime auto --upload --run-id <id> [--api-url <url>] [--runtime-path <path>] [--output-dir <dir>]\n                                               Upload native first-run evidence. The runner token is read from INFERGRADE_HUB_TOKEN by default;\n                                               override with --runner-token-env <VAR>, --runner-token-stdin, or (last resort, leaks via ps) --runner-token <token>.\n                                               --run-token <token> is a deprecated alias of --runner-token.\n    first-run --model <path> --no-upload --dry-run [--output-dir <dir>] [--json|--jsonl]\n                                               Validate and render the native first-run contract\n    first-run --model <path> --no-upload --runtime-command <path> [--output-dir <dir>] [--json|--jsonl]\n                                               Run an explicit native command adapter\n    help                                       Show this help\n\nArchitecture note: this Rust CLI plus runner-engine is the supported entry point. The desktop app shell is Rust, but the long-running listener still bridges to the Python runner-core during migration.";

fn print_help() {
    println!("{HELP_TEXT}");
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
        Some("plan") => Ok(llama_cpp_runtime_plan(load_selected_llama_cpp_runtime())),
        Some("list") => Ok(managed_llama_cpp_runtime_manifest()),
        Some("channels") => Ok(managed_llama_cpp_runtime_channels()),
        Some("status") => Ok(llama_cpp_runtime_status()),
        Some("install") => {
            let mut runtime_id: Option<String> = None;
            let mut index = 1;
            while index < args.len() {
                match args[index].as_str() {
                    "--runtime-id" => {
                        index += 1;
                        runtime_id = Some(
                            args.get(index)
                                .ok_or_else(|| "--runtime-id requires a value".to_string())?
                                .to_string(),
                        );
                    }
                    other => return Err(format!("unknown runtime install option: {other}")),
                }
                index += 1;
            }
            install_managed_llama_cpp_runtime(ManagedRuntimeInstallOptions {
                runtime_id,
                archive_bytes: None,
            })
        }
        Some("catalog-refresh") => {
            let mut url = None;
            let mut index = 1;
            while index < args.len() {
                match args[index].as_str() {
                    "--url" => {
                        index += 1;
                        url = args.get(index).map(String::as_str);
                        if url.is_none() {
                            return Err("--url requires a value".to_string());
                        }
                    }
                    other => {
                        return Err(format!("unknown runtime catalog-refresh option: {other}"))
                    }
                }
                index += 1;
            }
            refresh_default_runtime_catalog(url)
        }
        Some("catalog-use") => {
            let mut target = None;
            let mut consent_build = None;
            let mut index = 1;
            while index < args.len() {
                match args[index].as_str() {
                    "--target" => {
                        index += 1;
                        target = args.get(index).cloned();
                    }
                    "--consent-build" => {
                        index += 1;
                        consent_build = args.get(index).cloned();
                    }
                    other => return Err(format!("unknown runtime catalog-use option: {other}")),
                }
                index += 1;
            }
            install_active_runtime_catalog_target(
                target
                    .as_deref()
                    .ok_or_else(|| "--target is required".to_string())?,
                consent_build
                    .as_deref()
                    .ok_or_else(|| "--consent-build is required".to_string())?,
            )
        }
        Some("catalog-verify") | Some("catalog-install") => command_runtime_catalog(args),
        Some("rollback") => {
            let mut build_id = None;
            let mut index = 1;
            while index < args.len() {
                match args[index].as_str() {
                    "--runtime-build-id" => {
                        index += 1;
                        build_id = args.get(index).cloned();
                    }
                    other => return Err(format!("unknown runtime rollback option: {other}")),
                }
                index += 1;
            }
            rollback_selected_llama_cpp_runtime(
                build_id
                    .as_deref()
                    .ok_or_else(|| "--runtime-build-id requires a value".to_string())?,
            )
        }
        Some("select-existing") => {
            let mut runtime_path: Option<PathBuf> = None;
            let mut runtime_id: Option<String> = None;
            let mut index = 1;
            while index < args.len() {
                match args[index].as_str() {
                    "--runtime-path" | "--llama-cpp-cli-path" => {
                        index += 1;
                        runtime_path =
                            Some(PathBuf::from(args.get(index).ok_or_else(|| {
                                "--runtime-path requires a path".to_string()
                            })?));
                    }
                    "--runtime-id" => {
                        index += 1;
                        runtime_id = Some(
                            args.get(index)
                                .ok_or_else(|| "--runtime-id requires a value".to_string())?
                                .to_string(),
                        );
                    }
                    other => {
                        return Err(format!("unknown runtime select-existing option: {other}"))
                    }
                }
                index += 1;
            }
            select_existing_llama_cpp_runtime(runtime_id.as_deref(), runtime_path, None, None)
        }
        Some(other) => Err(format!("unknown runtime command: {other}")),
        None => Err(
            "runtime requires a subcommand: plan, list, status, install, or select-existing"
                .to_string(),
        ),
    }
}

fn command_runtime_catalog(args: &[String]) -> Result<Value, String> {
    let install = args.first().map(String::as_str) == Some("catalog-install");
    let mut catalog_dir: Option<PathBuf> = None;
    let mut pinned_root: Option<PathBuf> = None;
    let mut cache_dir: Option<PathBuf> = None;
    let mut target: Option<String> = None;
    let mut consent_build: Option<String> = None;
    let mut archive: Option<PathBuf> = None;
    let mut index = 1;
    while index < args.len() {
        let value = |index: &mut usize, option: &str| -> Result<&String, String> {
            *index += 1;
            args.get(*index)
                .ok_or_else(|| format!("{option} requires a value"))
        };
        match args[index].as_str() {
            "--catalog-dir" => {
                catalog_dir = Some(PathBuf::from(value(&mut index, "--catalog-dir")?))
            }
            "--pinned-root" => {
                pinned_root = Some(PathBuf::from(value(&mut index, "--pinned-root")?))
            }
            "--cache-dir" => cache_dir = Some(PathBuf::from(value(&mut index, "--cache-dir")?)),
            "--target" => target = Some(value(&mut index, "--target")?.to_string()),
            "--consent-build" => {
                consent_build = Some(value(&mut index, "--consent-build")?.to_string())
            }
            "--archive" => archive = Some(PathBuf::from(value(&mut index, "--archive")?)),
            other => return Err(format!("unknown runtime catalog option: {other}")),
        }
        index += 1;
    }
    let catalog_dir = catalog_dir.ok_or_else(|| "--catalog-dir is required".to_string())?;
    let pinned_root_path = pinned_root.ok_or_else(|| "--pinned-root is required".to_string())?;
    let cache_dir = cache_dir.ok_or_else(|| "--cache-dir is required".to_string())?;
    let read = |name: &str| {
        std::fs::read(catalog_dir.join(name))
            .map_err(|error| format!("could not read catalog {name}: {error}"))
    };
    let root = read("root.json")?;
    let timestamp = read("timestamp.json")?;
    let snapshot = read("snapshot.json")?;
    let targets = read("targets.json")?;
    let pinned_root = std::fs::read(pinned_root_path)
        .map_err(|error| format!("could not read pinned root: {error}"))?;
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|_| "system clock is before Unix epoch".to_string())?
        .as_secs();
    let activation = activate_runtime_catalog(
        &cache_dir,
        RuntimeCatalogFiles {
            root: &root,
            timestamp: &timestamp,
            snapshot: &snapshot,
            targets: &targets,
        },
        &pinned_root,
        now,
    )?;
    if !install {
        return serde_json::to_value(activation)
            .map_err(|error| format!("could not render runtime catalog status: {error}"));
    }
    let archive_bytes = archive
        .map(|path| {
            std::fs::read(path).map_err(|error| format!("could not read runtime archive: {error}"))
        })
        .transpose()?;
    install_runtime_catalog_target(
        &activation.catalog,
        target
            .as_deref()
            .ok_or_else(|| "--target is required".to_string())?,
        consent_build
            .as_deref()
            .ok_or_else(|| "--consent-build is required".to_string())?,
        archive_bytes,
    )
}

fn command_containers(args: &[String]) -> Result<Value, String> {
    match args.first().map(String::as_str) {
        Some("check") => Ok(container_runtime_readiness()),
        Some(other) => Err(format!("unknown containers command: {other}")),
        None => Err("containers requires a subcommand: check".to_string()),
    }
}

fn command_support(args: &[String]) -> Result<Value, String> {
    match args.first().map(String::as_str) {
        Some("summary") => {
            let mut first_run_artifact: Option<Value> = None;
            let mut recent_errors: Vec<String> = Vec::new();
            let mut index = 1;
            while index < args.len() {
                match args[index].as_str() {
                    "--first-run-artifact" => {
                        index += 1;
                        let path = args
                            .get(index)
                            .ok_or_else(|| "--first-run-artifact requires a path".to_string())?;
                        let text = std::fs::read_to_string(path).map_err(|error| {
                            format!("could not read first-run artifact `{path}`: {error}")
                        })?;
                        first_run_artifact =
                            Some(serde_json::from_str(&text).map_err(|error| {
                                format!("could not parse first-run artifact `{path}`: {error}")
                            })?);
                    }
                    "--error" => {
                        index += 1;
                        recent_errors.push(
                            args.get(index)
                                .ok_or_else(|| "--error requires a value".to_string())?
                                .to_string(),
                        );
                    }
                    other => return Err(format!("unknown support summary option: {other}")),
                }
                index += 1;
            }
            Ok(build_support_summary(
                Some(env!("CARGO_PKG_VERSION")),
                json!({
                    "status": "not_loaded_by_cli",
                    "message": "The Rust CLI support summary does not read OS credential storage. Use Desktop support export for live pairing status.",
                }),
                first_run_artifact,
                &recent_errors,
            ))
        }
        Some(other) => Err(format!("unknown support command: {other}")),
        None => Err("support requires a subcommand: summary".to_string()),
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

fn command_first_run_with_events(
    args: &[String],
) -> Result<(Value, Vec<RunnerEvent>, bool), String> {
    command_first_run_with_event_sink(args, |event| event)
}

fn command_first_run_with_event_sink<F>(
    args: &[String],
    mut event_sink: F,
) -> Result<(Value, Vec<RunnerEvent>, bool), String>
where
    F: FnMut(RunnerEvent) -> RunnerEvent,
{
    let mut model_path: Option<PathBuf> = None;
    let mut runtime_hint = Some("auto".to_string());
    let mut prompt = "Say hello in one sentence.".to_string();
    let mut max_tokens = 32_u32;
    let mut dry_run = false;
    let mut no_upload = false;
    let mut upload = false;
    let mut api_url = "https://api.infergrade.com".to_string();
    let mut run_id: Option<String> = None;
    let mut run_token: Option<String> = None;
    let mut run_token_source: Option<&'static str> = None;
    let mut run_token_env_var: Option<String> = None;
    let mut run_token_stdin = false;
    let mut worker_id = "infergrade-runner-cli".to_string();
    let mut runtime_command: Option<PathBuf> = None;
    let mut runtime_path: Option<PathBuf> = None;
    let mut output_dir: Option<PathBuf> = None;
    let mut jsonl = false;
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
            "--runtime-path" => {
                index += 1;
                runtime_path =
                    Some(PathBuf::from(args.get(index).ok_or_else(|| {
                        "--runtime-path requires a path".to_string()
                    })?));
            }
            "--output-dir" => {
                index += 1;
                output_dir = Some(PathBuf::from(
                    args.get(index)
                        .ok_or_else(|| "--output-dir requires a path".to_string())?,
                ));
            }
            "--api-url" => {
                index += 1;
                api_url = args
                    .get(index)
                    .ok_or_else(|| "--api-url requires a value".to_string())?
                    .to_string();
            }
            "--run-id" => {
                index += 1;
                run_id = Some(
                    args.get(index)
                        .ok_or_else(|| "--run-id requires a value".to_string())?
                        .to_string(),
                );
            }
            "--runner-token" | "--run-token" => {
                let flag = args[index].clone();
                index += 1;
                run_token = Some(
                    args.get(index)
                        .ok_or_else(|| format!("{flag} requires a value"))?
                        .to_string(),
                );
                run_token_source = Some("argv");
                eprintln!(
                    "warning: passing the runner token on the command line exposes it to other local users via `ps`/`/proc`. Prefer INFERGRADE_HUB_TOKEN, --runner-token-env <VAR>, or --runner-token-stdin."
                );
            }
            "--runner-token-env" => {
                index += 1;
                let name = args
                    .get(index)
                    .ok_or_else(|| "--runner-token-env requires a variable name".to_string())?
                    .to_string();
                run_token_env_var = Some(name);
            }
            "--runner-token-stdin" => {
                run_token_stdin = true;
            }
            "--worker-id" => {
                index += 1;
                worker_id = args
                    .get(index)
                    .ok_or_else(|| "--worker-id requires a value".to_string())?
                    .to_string();
            }
            "--dry-run" => dry_run = true,
            "--no-upload" => no_upload = true,
            "--upload" => upload = true,
            "--json" => {}
            "--jsonl" => jsonl = true,
            unknown => return Err(format!("unknown first-run option: {unknown}")),
        }
        index += 1;
    }
    if no_upload && upload {
        return Err("first-run accepts either --no-upload or --upload, not both".to_string());
    }
    if !no_upload && !upload {
        return Err("first-run requires either --no-upload or explicit --upload".to_string());
    }
    if upload && dry_run {
        return Err(
            "first-run upload requires a real native run; dry-run cannot upload".to_string(),
        );
    }
    if upload && jsonl {
        return Err("first-run upload does not support --jsonl yet".to_string());
    }
    if upload {
        if run_id.is_none() {
            return Err("--upload requires --run-id".to_string());
        }
        let token_source_count = (run_token.is_some() as u8)
            + (run_token_env_var.is_some() as u8)
            + (run_token_stdin as u8);
        if token_source_count > 1 {
            return Err(
                "first-run accepts at most one of --runner-token, --runner-token-env, or --runner-token-stdin".to_string(),
            );
        }
        if run_token.is_none() {
            run_token = resolve_runner_token(
                run_token_env_var.as_deref(),
                run_token_stdin,
                &mut run_token_source,
            )?;
        }
        if run_token.is_none() {
            return Err(
                "--upload requires a runner token. Set INFERGRADE_HUB_TOKEN, pass --runner-token-env <VAR>, --runner-token-stdin, or (less safe) --runner-token <token>."
                    .to_string(),
            );
        }
        if let Some(source) = run_token_source {
            let label = match source {
                "env_default" => "INFERGRADE_HUB_TOKEN environment variable",
                "env_explicit" => "explicit --runner-token-env variable",
                "stdin" => "--runner-token-stdin",
                "argv" => "--runner-token argv (visible via ps/proc)",
                other => other,
            };
            eprintln!("info: using runner token from {label}");
        }
    }
    if dry_run && runtime_command.is_some() {
        return Err(
            "first-run accepts either --dry-run or --runtime-command, not both".to_string(),
        );
    }
    if runtime_command.is_some() && runtime_path.is_some() {
        return Err(
            "first-run accepts either --runtime-command or --runtime-path, not both".to_string(),
        );
    }
    let runtime_hint_value = runtime_hint.clone().unwrap_or_else(|| "auto".to_string());
    if !dry_run
        && runtime_command.is_none()
        && runtime_hint_value != "auto"
        && !runtime_hint_value.starts_with("llama.cpp")
    {
        return Err(
            "built-in first-run currently supports --runtime auto or llama.cpp runtime hints."
                .to_string(),
        );
    }
    let input = NativeFirstRunInput {
        model_path: model_path.ok_or_else(|| "--model is required".to_string())?,
        runtime_hint,
        prompt,
        max_tokens,
        upload: false,
    };
    let mut events = Vec::new();
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
            run_native_first_run_with_events(input, &runtime, |event| {
                events.push(event_sink(event))
            })
            .map_err(|error| error.to_string())?,
        )
    } else if dry_run {
        (
            "dry_run",
            "simulated",
            "Native first-run contract validated. Real llama.cpp execution was not requested.",
            run_native_first_run_with_events(input, &DryRunRuntime, |event| {
                events.push(event_sink(event))
            })
            .map_err(|error| error.to_string())?,
        )
    } else {
        let runtime = LlamaCppRuntime::resolve(runtime_path)
            .map_err(|error| format!("runtime missing or untrusted: {error}"))?;
        (
            "llama_cpp",
            "local_native",
            "Native first-run llama.cpp adapter completed. Upload remains disabled.",
            run_native_first_run_with_events(input, &runtime, |event| {
                events.push(event_sink(event))
            })
            .map_err(|error| error.to_string())?,
        )
    };
    let mut payload = json!({
        "mode": mode,
        "execution": execution,
        "message": message,
        "result": result,
    });
    if let Some(output_dir) = output_dir {
        let artifact = write_native_first_run_artifact(&output_dir, &payload)
            .map_err(|error| error.to_string())?;
        payload["artifact"] = serde_json::to_value(artifact).map_err(|error| error.to_string())?;
    }
    if upload {
        let run_id = run_id.expect("upload run_id was validated before runtime execution");
        let run_token =
            run_token.expect("upload runner token was validated before runtime execution");
        let result: NativeFirstRunResult = serde_json::from_value(payload["result"].clone())
            .map_err(|error| format!("Could not rebuild native first-run result: {error}"))?;
        let bundle_payload = native_first_run_bundle_payload(
            &result,
            NativeFirstRunBundleOptions {
                submission_channel: "infergrade_runner_cli".to_string(),
                ..NativeFirstRunBundleOptions::default()
            },
        );
        if let Some(output_dir) = payload
            .get("artifact")
            .and_then(|artifact| artifact.get("path"))
            .and_then(Value::as_str)
            .and_then(|path| PathBuf::from(path).parent().map(PathBuf::from))
        {
            let bundle_artifact =
                write_native_first_run_bundle_payload(&output_dir, &bundle_payload)
                    .map_err(|error| error.to_string())?;
            payload["bundle_artifact"] =
                serde_json::to_value(bundle_artifact).map_err(|error| error.to_string())?;
        }
        let claim_request = build_run_claim_request(
            &api_url,
            &run_id,
            &worker_id,
            "local_native",
            Some(&run_token),
        )
        .map_err(|error| error.to_string())?;
        let claim_response = block_on_hub_request(&claim_request)?;
        let redacted_claim_body = redact_value_token(claim_response.body.clone(), &run_token);
        let upload_request =
            build_run_bundle_upload_request(&api_url, &run_id, bundle_payload, Some(&run_token))
                .map_err(|error| error.to_string())?;
        let upload_response = block_on_hub_request(&upload_request)?;
        let bundle_id = upload_response
            .body
            .get("bundle_id")
            .and_then(Value::as_str)
            .ok_or_else(|| "Hub upload response did not include bundle_id".to_string())?
            .to_string();
        let redacted_upload_body = redact_value_token(upload_response.body.clone(), &run_token);
        let completion_request = build_run_completion_request(
            &api_url,
            &run_id,
            &worker_id,
            &bundle_id,
            Some(redacted_upload_body.clone()),
            Some(&run_token),
        )
        .map_err(|error| error.to_string())?;
        let completion_response = block_on_hub_request(&completion_request)?;
        let redacted_completion_body =
            redact_value_token(completion_response.body.clone(), &run_token);
        payload["upload"] = json!({
            "uploaded": true,
            "run_id": run_id,
            "bundle_id": bundle_id,
            "claim": redacted_claim_body,
            "server": redacted_upload_body,
            "completion": redacted_completion_body,
        });
    } else {
        payload["upload"] = json!({
            "uploaded": false,
            "reason": "explicit_no_upload",
        });
    }
    payload["events"] = serde_json::to_value(&events).map_err(|error| error.to_string())?;
    Ok((payload, events, jsonl))
}

fn resolve_runner_token(
    env_var: Option<&str>,
    from_stdin: bool,
    source: &mut Option<&'static str>,
) -> Result<Option<String>, String> {
    if from_stdin {
        let mut buffer = String::new();
        io::stdin()
            .read_line(&mut buffer)
            .map_err(|error| format!("could not read runner token from stdin: {error}"))?;
        let trimmed = buffer.trim().to_string();
        if trimmed.is_empty() {
            return Err("--runner-token-stdin received empty input".to_string());
        }
        *source = Some("stdin");
        return Ok(Some(trimmed));
    }
    if let Some(name) = env_var {
        let value = env::var(name)
            .map_err(|_| format!("environment variable `{name}` is not set or not unicode"))?;
        let trimmed = value.trim().to_string();
        if trimmed.is_empty() {
            return Err(format!("environment variable `{name}` is empty"));
        }
        *source = Some("env_explicit");
        return Ok(Some(trimmed));
    }
    if let Ok(value) = env::var("INFERGRADE_HUB_TOKEN") {
        let trimmed = value.trim().to_string();
        if !trimmed.is_empty() {
            *source = Some("env_default");
            return Ok(Some(trimmed));
        }
    }
    Ok(None)
}

fn block_on_hub_request(
    request: &infergrade_runner_engine::HubJsonRequest,
) -> Result<infergrade_runner_engine::HubJsonResponse, String> {
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|error| format!("Could not start native Hub transport: {error}"))?
        .block_on(execute_hub_json_request(request))
        .map_err(|error| error.to_string())
}

fn redact_value_token(value: Value, token: &str) -> Value {
    let token = token.trim();
    if token.is_empty() {
        return value;
    }
    match value {
        Value::String(text) => Value::String(text.replace(token, "[redacted]")),
        Value::Array(items) => Value::Array(
            items
                .into_iter()
                .map(|item| redact_value_token(item, token))
                .collect(),
        ),
        Value::Object(map) => Value::Object(
            map.into_iter()
                .map(|(key, item)| (key, redact_value_token(item, token)))
                .collect(),
        ),
        other => other,
    }
}

fn command_first_run(args: &[String]) -> Result<Value, String> {
    command_first_run_with_events(args).map(|(payload, _events, _jsonl)| payload)
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
        Some("support") => command_support(&args[1..]).map(Some),
        Some("first-run") => command_first_run(&args[1..]).map(Some),
        Some(other) => Err(format!("unknown command: {other}")),
    }
}

fn main() -> ExitCode {
    let args = env::args().skip(1).collect::<Vec<_>>();
    if args.first().map(String::as_str) == Some("first-run")
        && args.iter().any(|arg| arg == "--jsonl")
    {
        let result = command_first_run_with_event_sink(&args[1..], |event| {
            print_json_line(&serde_json::to_value(&event).expect("event JSON"));
            let _ = io::stdout().flush();
            event
        });
        match result {
            Ok((mut payload, _events, _jsonl)) => {
                if let Some(object) = payload.as_object_mut() {
                    object.remove("events");
                }
                print_json_line(&json!({
                    "type": "first_run_result",
                    "payload": payload,
                }));
                return ExitCode::SUCCESS;
            }
            Err(error) => {
                print_json_line(&json!({
                    "type": "first_run_error",
                    "error": error,
                }));
                return ExitCode::from(2);
            }
        }
    }
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

fn print_json_line(value: &Value) {
    println!(
        "{}",
        serde_json::to_string(value).expect("JSONL rendering should not fail")
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::{mpsc, Mutex, OnceLock};
    use std::thread;

    fn env_test_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    fn write_test_llama_binary(path: &std::path::Path) {
        #[cfg(windows)]
        std::fs::write(
            path,
            "@echo off\r\necho llama-cli version 0.0-test\r\necho llama_print_timings:        load time =     617.57 ms 1>&2\r\necho llama_print_timings:        eval time =    1285.25 ms /    6 runs   (40.16 ms per token, 24.90 tokens per second) 1>&2\r\n",
        )
        .expect("test llama binary");
        #[cfg(not(windows))]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::write(
                path,
                "#!/bin/sh\necho 'llama-cli version 0.0-test'\necho 'llama_print_timings:        load time =     617.57 ms' >&2\necho 'llama_print_timings:        eval time =    1285.25 ms /    6 runs   (40.16 ms per token, 24.90 tokens per second)' >&2\n",
            )
            .expect("test llama binary");
            let mut permissions = std::fs::metadata(path)
                .expect("test binary metadata")
                .permissions();
            permissions.set_mode(0o755);
            std::fs::set_permissions(path, permissions).expect("test binary executable");
        }
    }

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
    fn runtime_list_and_status_use_shared_engine_manifest() {
        let list = command_runtime(&["list".to_string()]).expect("runtime list");
        assert_eq!(list["runtime_family"], "llama.cpp");
        assert!(list["channels"]["channels"]
            .as_array()
            .expect("channels")
            .iter()
            .any(|entry| entry["channel"] == "infergrade_stable"));
        assert!(list["runtimes"]
            .as_array()
            .expect("runtime entries")
            .iter()
            .any(|entry| {
                entry["runtime_id"] == "llama-cpp-b9050-macos-arm64-metal"
                    && entry["channel"] == "infergrade_stable"
            }));
        assert!(list["runtimes"]
            .as_array()
            .expect("runtime entries")
            .iter()
            .any(|entry| {
                entry["runtime_id"] == "llama-cpp-b9994-macos-arm64-metal"
                    && entry["channel"] == "reviewed_candidate"
            }));

        let channels = command_runtime(&["channels".to_string()]).expect("runtime channels");
        assert_eq!(channels["runtime_family"], "llama.cpp");
        assert!(channels["channels"]
            .as_array()
            .expect("channel entries")
            .iter()
            .any(|entry| entry["channel"] == "local_binary"));
        assert!(HELP_TEXT.contains("runtime channels"));

        let status = command_runtime(&["status".to_string()]).expect("runtime status");
        assert_eq!(status["runtime_family"], "llama.cpp");
        assert!(status["selected_runtime"].get("status").is_some());
        assert!(status["recommended_runtime"].get("runtime_id").is_some());
        assert_eq!(status["update_policy"]["automatic_updates"], false);
    }

    #[test]
    fn runtime_install_is_explicit_shared_engine_command() {
        assert!(HELP_TEXT.contains("runtime install [--runtime-id <id>]"));
        let error = command_runtime(&[
            "install".to_string(),
            "--runtime-id".to_string(),
            "unknown-runtime".to_string(),
        ])
        .expect_err("unknown managed runtime rejected before download");
        assert!(error.contains("unknown managed llama.cpp runtime"));
    }

    #[test]
    fn runtime_catalog_commands_require_https_and_exact_build_consent() {
        assert!(HELP_TEXT.contains("runtime catalog-refresh"));
        assert!(HELP_TEXT.contains("--consent-build <sha256>"));
        let insecure = command_runtime(&[
            "catalog-refresh".to_string(),
            "--url".to_string(),
            "http://example.test/runtime-catalog/".to_string(),
        ])
        .expect_err("insecure catalog URL rejected before network access");
        assert!(insecure.contains("must use HTTPS"));
        let missing_consent = command_runtime(&[
            "catalog-use".to_string(),
            "--target".to_string(),
            "infergrade/llama-cpp/test.tar.gz".to_string(),
        ])
        .expect_err("catalog install requires exact build consent");
        assert!(missing_consent.contains("--consent-build is required"));
    }

    #[test]
    fn runtime_select_existing_uses_shared_engine_and_records_explicit_path() {
        let _guard = env_test_lock().lock().expect("env lock");
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-cli-runtime-cache-{}",
            std::process::id()
        ));
        let runtime_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-select-runtime-{}{}",
            std::process::id(),
            if cfg!(windows) { ".cmd" } else { "" }
        ));
        write_test_llama_binary(&runtime_path);
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);

        let output = command_runtime(&[
            "select-existing".to_string(),
            "--runtime-path".to_string(),
            runtime_path.display().to_string(),
        ])
        .expect("runtime selected");

        assert_eq!(output["status"], "selected");
        assert_eq!(output["selection"]["source"], "selected_existing");
        assert!(output["selection"]["runtime_id"]
            .as_str()
            .unwrap_or("")
            .starts_with("llama-cpp-local-"));
        assert_eq!(output["selection"]["runtime_identity_basis"], "cli_sha256");
        assert!(output["selection"]["version_label"]
            .as_str()
            .unwrap_or("")
            .contains("0.0-test"));
        assert!(output["message"]
            .as_str()
            .unwrap_or("")
            .contains("No download or install command was run"));

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = std::fs::remove_file(runtime_path);
        let _ = std::fs::remove_dir_all(runtime_cache_dir);
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
    fn support_summary_reports_retry_upload_without_token_echoes() {
        let output_dir = env::temp_dir().join(format!(
            "infergrade-runner-cli-support-summary-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&output_dir);
        std::fs::create_dir_all(&output_dir).expect("support output dir");
        let artifact_path = output_dir.join("native-first-run-result.json");
        std::fs::write(
            &artifact_path,
            serde_json::to_string_pretty(&json!({
                "result": {
                    "status": "completed",
                    "evidence_kind": "native_first_run"
                },
                "artifact": {
                    "path": "/tmp/qbhr_cli_path_secret/native-first-run-result.json"
                },
                "bundle_artifact": {
                    "path": "/tmp/infergrade/IGRP-8421-cli-bundle.json"
                },
                "upload": {
                    "uploaded": false,
                    "reason": "Bearer qbhr_cli_reason_secret",
                    "run_id": "qbhr_cli_run_secret",
                    "bundle_id": "igrp_cli_bundle_secret",
                    "server": {
                        "echo": "qbhr_cli_secret_token"
                    }
                }
            }))
            .expect("artifact JSON"),
        )
        .expect("artifact write");

        let output = command_support(&[
            "summary".to_string(),
            "--first-run-artifact".to_string(),
            artifact_path.display().to_string(),
            "--error".to_string(),
            "Authorization: Bearer qbhr_cli_secret_token for pairing code IGRP-8421".to_string(),
        ])
        .expect("support summary");

        assert_eq!(
            output["export_kind"],
            "infergrade_runner_support_summary_v1"
        );
        assert_eq!(output["secrets_excluded"], true);
        assert_eq!(
            output["first_run"]["upload_status"],
            "not_uploaded_or_failed"
        );
        assert_eq!(
            output["first_run"]["upload_reason"],
            "[redacted] [redacted]"
        );
        assert_eq!(output["first_run"]["run_id"], "[redacted]");
        assert_eq!(output["first_run"]["bundle_id"], "[redacted]");
        assert!(!output["first_run"]["artifact_path"]
            .as_str()
            .expect("artifact path")
            .contains("qbhr_cli_path_secret"));
        assert!(!output["first_run"]["bundle_artifact_path"]
            .as_str()
            .expect("bundle artifact path")
            .contains("IGRP-8421"));
        assert!(output["next_actions"]
            .as_array()
            .expect("next actions")
            .iter()
            .any(|action| action["action"] == "retry_upload"));
        assert!(HELP_TEXT.contains("support summary"));
        let rendered = serde_json::to_string(&output).expect("support JSON");
        assert!(!rendered.contains("qbhr_cli_secret_token"));
        assert!(!rendered.contains("qbhr_cli_reason_secret"));
        assert!(!rendered.contains("qbhr_cli_run_secret"));
        assert!(!rendered.contains("igrp_cli_bundle_secret"));
        assert!(!rendered.contains("qbhr_cli_path_secret"));
        assert!(!rendered.contains("IGRP-8421"));
        assert!(!rendered.contains("Bearer qbhr"));

        let _ = std::fs::remove_dir_all(output_dir);
    }

    #[test]
    fn help_marks_run_token_deprecated_alias() {
        assert!(HELP_TEXT.contains("--run-token <token>"));
        assert!(HELP_TEXT.contains("deprecated alias of --runner-token"));
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
        assert_eq!(output["events"][0]["type"], "benchmark_started");
        assert_eq!(
            output["events"]
                .as_array()
                .expect("events array")
                .last()
                .expect("last event")["type"],
            "benchmark_completed"
        );

        let _ = std::fs::remove_file(model_path);
    }

    #[test]
    fn first_run_jsonl_flag_keeps_typed_events_for_streaming() {
        let model_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-jsonl-model-{}.gguf",
            std::process::id()
        ));
        std::fs::write(&model_path, b"fake gguf path validation only").expect("model file");

        let (output, events, jsonl) = command_first_run_with_events(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--no-upload".to_string(),
            "--dry-run".to_string(),
            "--jsonl".to_string(),
        ])
        .expect("first-run jsonl output");

        assert!(jsonl);
        assert_eq!(events.len(), output["events"].as_array().unwrap().len());
        assert!(matches!(
            events.first(),
            Some(RunnerEvent::BenchmarkStarted { benchmark_id })
                if benchmark_id == "native_first_run"
        ));

        let _ = std::fs::remove_file(model_path);
    }

    #[test]
    fn first_run_event_sink_observes_error_events_before_failure() {
        let missing_model = env::temp_dir().join(format!(
            "infergrade-runner-cli-jsonl-missing-model-{}.gguf",
            std::process::id()
        ));
        let mut streamed_events = Vec::new();

        let error = command_first_run_with_event_sink(
            &[
                "--model".to_string(),
                missing_model.display().to_string(),
                "--runtime".to_string(),
                "auto".to_string(),
                "--no-upload".to_string(),
                "--dry-run".to_string(),
                "--jsonl".to_string(),
            ],
            |event| {
                streamed_events.push(serde_json::to_value(&event).expect("event JSON"));
                event
            },
        )
        .expect_err("missing model fails after emitting error");

        assert!(error.contains("model_path_missing"));
        assert_eq!(streamed_events[0]["type"], "benchmark_started");
        assert!(streamed_events
            .iter()
            .any(|event| { event["type"] == "error" && event["code"] == "model_path_missing" }));
    }

    #[test]
    fn first_run_auto_requires_selected_or_explicit_llama_runtime() {
        let model_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-missing-runtime-model-{}.gguf",
            std::process::id()
        ));
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-cli-missing-runtime-cache-{}",
            std::process::id()
        ));
        std::fs::write(&model_path, b"fake gguf path validation only").expect("model file");
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        let error = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--no-upload".to_string(),
        ])
        .expect_err("missing runtime rejected");

        assert!(error.contains("No selected llama.cpp runtime"));
        assert!(error.contains("--runtime-path"));

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = std::fs::remove_file(model_path);
        let _ = std::fs::remove_dir_all(runtime_cache_dir);
    }

    #[test]
    fn first_run_runtime_path_executes_builtin_llama_cpp_adapter() {
        let model_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-llama-model-{}.gguf",
            std::process::id()
        ));
        let extension = if cfg!(windows) { "cmd" } else { "sh" };
        let runtime_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-llama-runtime-{}.{}",
            std::process::id(),
            extension
        ));
        std::fs::write(&model_path, b"fake gguf path validation only").expect("model file");
        if cfg!(windows) {
            std::fs::write(
                &runtime_path,
                "@echo off\r\necho hello from llama\r\necho llama_print_timings:        load time =     617.57 ms 1>&2\r\necho llama_print_timings:        eval time =    1285.25 ms /    6 runs   (40.16 ms per token, 24.90 tokens per second) 1>&2\r\n",
            )
            .expect("runtime script");
        } else {
            use std::os::unix::fs::PermissionsExt;
            std::fs::write(
                &runtime_path,
                "#!/bin/sh\necho 'hello from llama'\necho 'llama_print_timings:        load time =     617.57 ms' >&2\necho 'llama_print_timings:        eval time =    1285.25 ms /    6 runs   (40.16 ms per token, 24.90 tokens per second)' >&2\n",
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
            "auto".to_string(),
            "--no-upload".to_string(),
            "--runtime-path".to_string(),
            runtime_path.display().to_string(),
        ])
        .expect("first-run llama.cpp runtime-path output");

        assert_eq!(output["mode"], "llama_cpp");
        assert_eq!(output["execution"], "local_native");
        assert_eq!(output["result"]["runtime_id"], "llama.cpp-auto");
        assert_eq!(output["result"]["uploaded"], false);
        assert_eq!(output["result"]["metrics"]["generated_tokens"], 6);
        assert_eq!(
            output["result"]["metrics"]["decode_tokens_per_second"],
            24.9
        );

        let _ = std::fs::remove_file(model_path);
        let _ = std::fs::remove_file(runtime_path);
    }

    #[test]
    fn first_run_auto_uses_selected_runtime_id_for_artifact_provenance() {
        let _guard = env_test_lock().lock().expect("env lock");
        let model_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-selected-runtime-model-{}.gguf",
            std::process::id()
        ));
        let runtime_cache_dir = env::temp_dir().join(format!(
            "infergrade-runner-cli-selected-runtime-cache-{}",
            std::process::id()
        ));
        let extension = if cfg!(windows) { "cmd" } else { "sh" };
        let runtime_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-selected-runtime-{}.{}",
            std::process::id(),
            extension
        ));
        std::fs::write(&model_path, b"fake gguf path validation only").expect("model file");
        write_test_llama_binary(&runtime_path);
        let previous_cache_dir = env::var("INFERGRADE_RUNTIME_CACHE_DIR").ok();
        env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &runtime_cache_dir);
        select_existing_llama_cpp_runtime(
            Some("llama-cpp-managed-test"),
            Some(runtime_path.clone()),
            None,
            None,
        )
        .expect("selected runtime");

        let output = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--no-upload".to_string(),
        ])
        .expect("first-run selected runtime output");

        assert_eq!(output["mode"], "llama_cpp");
        assert_eq!(output["result"]["runtime_id"], "llama-cpp-managed-test");

        if let Some(previous_cache_dir) = previous_cache_dir {
            env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", previous_cache_dir);
        } else {
            env::remove_var("INFERGRADE_RUNTIME_CACHE_DIR");
        }
        let _ = std::fs::remove_file(model_path);
        let _ = std::fs::remove_file(runtime_path);
        let _ = std::fs::remove_dir_all(runtime_cache_dir);
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

    #[test]
    fn first_run_upload_posts_bundle_and_completion_to_run_scope() {
        let model_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-upload-model-{}.gguf",
            std::process::id()
        ));
        let extension = if cfg!(windows) { "cmd" } else { "sh" };
        let runtime_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-upload-runtime-{}.{}",
            std::process::id(),
            extension
        ));
        let output_dir = env::temp_dir().join(format!(
            "infergrade-runner-cli-upload-dir-{}",
            std::process::id()
        ));
        let (api_url, received) = spawn_cli_hub_server();
        std::fs::write(&model_path, b"fake gguf path validation only").expect("model file");
        if cfg!(windows) {
            std::fs::write(
                &runtime_path,
                "@echo off\r\necho hello from upload runtime\r\necho llama_print_timings:        load time =      10.00 ms 1>&2\r\necho llama_print_timings:        eval time =     100.00 ms /    5 runs   (20.00 ms per token, 50.00 tokens per second) 1>&2\r\n",
            )
            .expect("runtime script");
        } else {
            use std::os::unix::fs::PermissionsExt;
            std::fs::write(
                &runtime_path,
                "#!/bin/sh\necho 'hello from upload runtime'\necho 'llama_print_timings:        load time =      10.00 ms' >&2\necho 'llama_print_timings:        eval time =     100.00 ms /    5 runs   (20.00 ms per token, 50.00 tokens per second)' >&2\n",
            )
            .expect("runtime script");
            let mut permissions = std::fs::metadata(&runtime_path)
                .expect("runtime metadata")
                .permissions();
            permissions.set_mode(0o755);
            std::fs::set_permissions(&runtime_path, permissions).expect("runtime executable");
        }
        let _ = std::fs::remove_dir_all(&output_dir);

        let output = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--upload".to_string(),
            "--api-url".to_string(),
            api_url,
            "--run-id".to_string(),
            "run_cli_upload_123".to_string(),
            "--runner-token".to_string(),
            "rtok_cli_secret".to_string(),
            "--worker-id".to_string(),
            "worker-cli-upload".to_string(),
            "--runtime-path".to_string(),
            runtime_path.display().to_string(),
            "--output-dir".to_string(),
            output_dir.display().to_string(),
        ])
        .expect("uploaded first-run output");

        assert_eq!(output["upload"]["uploaded"], true);
        assert_eq!(output["upload"]["run_id"], "run_cli_upload_123");
        assert_eq!(output["upload"]["bundle_id"], "nfr_cli_bundle");
        assert_eq!(output["upload"]["claim"]["run"]["status"], "running");
        assert_eq!(output["upload"]["server"]["stored"], true);
        assert_eq!(output["upload"]["server"]["echo"], "[redacted]");
        assert_eq!(output["upload"]["completion"]["run"]["status"], "completed");
        assert_eq!(
            output["bundle_artifact"]["format"],
            "infergrade.bundle_upload.v1"
        );
        let rendered = serde_json::to_string(&output).expect("output JSON");
        assert!(!rendered.contains("rtok_cli_secret"));

        let claim_request = received.recv().expect("claim request");
        let bundle_request = received.recv().expect("bundle request");
        let complete_request = received.recv().expect("complete request");
        assert!(claim_request.starts_with("POST /v1/runs/claim HTTP/1.1"));
        assert!(claim_request.contains("authorization: Bearer rtok_cli_secret"));
        assert!(claim_request.contains("\"run_id\":\"run_cli_upload_123\""));
        assert!(claim_request.contains("\"worker_id\":\"worker-cli-upload\""));
        assert!(bundle_request.starts_with("POST /v1/runs/run_cli_upload_123/bundle HTTP/1.1"));
        assert!(bundle_request.contains("authorization: Bearer rtok_cli_secret"));
        assert!(bundle_request.contains("\"source_bundle_origin\":\"infergrade_native_first_run\""));
        assert!(!bundle_request.contains(model_path.display().to_string().as_str()));
        assert!(complete_request.starts_with("POST /v1/runs/run_cli_upload_123/complete HTTP/1.1"));
        assert!(complete_request.contains("\"worker_id\":\"worker-cli-upload\""));
        assert!(complete_request.contains("\"bundle_id\":\"nfr_cli_bundle\""));

        let _ = std::fs::remove_file(model_path);
        let _ = std::fs::remove_file(runtime_path);
        let _ = std::fs::remove_dir_all(output_dir);
    }

    #[test]
    fn first_run_upload_requires_run_scope_and_rejects_dry_run() {
        let _guard = env_test_lock().lock().expect("env lock");
        let saved_hub_token = env::var("INFERGRADE_HUB_TOKEN").ok();
        env::remove_var("INFERGRADE_HUB_TOKEN");
        let model_path = env::temp_dir().join(format!(
            "infergrade-runner-cli-upload-validation-model-{}.gguf",
            std::process::id()
        ));
        std::fs::write(&model_path, b"fake gguf path validation only").expect("model file");

        let missing_token = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--upload".to_string(),
            "--run-id".to_string(),
            "run_cli_upload_123".to_string(),
            "--dry-run".to_string(),
        ])
        .expect_err("dry-run upload rejected first");
        assert!(missing_token.contains("dry-run cannot upload"));

        let missing_upload_choice = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--dry-run".to_string(),
        ])
        .expect_err("upload mode required");
        assert!(missing_upload_choice.contains("requires either --no-upload or explicit --upload"));

        let missing_runner_token = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--upload".to_string(),
            "--run-id".to_string(),
            "run_cli_upload_123".to_string(),
        ])
        .expect_err("runner token required");
        assert!(missing_runner_token.contains("INFERGRADE_HUB_TOKEN"));
        assert!(missing_runner_token.contains("--runner-token"));

        let missing_deprecated_alias_value = command_first_run(&[
            "--model".to_string(),
            model_path.display().to_string(),
            "--runtime".to_string(),
            "auto".to_string(),
            "--upload".to_string(),
            "--run-id".to_string(),
            "run_cli_upload_123".to_string(),
            "--run-token".to_string(),
        ])
        .expect_err("deprecated alias still requires value");
        assert!(missing_deprecated_alias_value.contains("--run-token requires a value"));

        let _ = std::fs::remove_file(model_path);
        if let Some(token) = saved_hub_token {
            env::set_var("INFERGRADE_HUB_TOKEN", token);
        }
    }

    fn spawn_cli_hub_server() -> (String, mpsc::Receiver<String>) {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind test server");
        let address = listener.local_addr().expect("server address");
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            for index in 0..3 {
                let (mut stream, _) = listener.accept().expect("accept request");
                let request = read_http_request(&mut stream);
                sender.send(request).expect("send request");
                let body = if index == 0 {
                    r#"{"run":{"run_id":"run_cli_upload_123","status":"running"}}"#
                } else if index == 1 {
                    r#"{"stored":true,"bundle_id":"nfr_cli_bundle","echo":"rtok_cli_secret","server_validation":{"verification_levels":["experimental"],"comparison_grades":["informational_only"]}}"#
                } else {
                    r#"{"run":{"run_id":"run_cli_upload_123","status":"completed"}}"#
                };
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                stream
                    .write_all(response.as_bytes())
                    .expect("write response");
            }
        });
        (format!("http://{address}"), receiver)
    }

    fn read_http_request(stream: &mut impl Read) -> String {
        let mut bytes = Vec::new();
        let mut buffer = [0_u8; 1024];
        let header_end = loop {
            let bytes_read = stream.read(&mut buffer).expect("read request");
            assert!(bytes_read > 0, "connection closed before headers");
            bytes.extend_from_slice(&buffer[..bytes_read]);
            if let Some(index) = bytes.windows(4).position(|window| window == b"\r\n\r\n") {
                break index + 4;
            }
        };
        let headers = String::from_utf8_lossy(&bytes[..header_end]).to_string();
        let content_length = headers
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().ok())
                    .flatten()
            })
            .unwrap_or(0);
        while bytes.len().saturating_sub(header_end) < content_length {
            let bytes_read = stream.read(&mut buffer).expect("read body");
            assert!(bytes_read > 0, "connection closed before body");
            bytes.extend_from_slice(&buffer[..bytes_read]);
        }
        String::from_utf8_lossy(&bytes).to_string()
    }

    #[test]
    fn resolve_runner_token_prefers_explicit_env_var_over_default() {
        let _guard = env_test_lock().lock().expect("env lock");
        let var_name = format!("INFERGRADE_TEST_TOKEN_{}", std::process::id());
        env::set_var(&var_name, "explicit_env_value");
        env::set_var("INFERGRADE_HUB_TOKEN", "default_env_value");
        let mut source: Option<&'static str> = None;
        let token = resolve_runner_token(Some(&var_name), false, &mut source)
            .expect("explicit env var")
            .expect("token returned");
        assert_eq!(token, "explicit_env_value");
        assert_eq!(source, Some("env_explicit"));
        env::remove_var(&var_name);
        env::remove_var("INFERGRADE_HUB_TOKEN");
    }

    #[test]
    fn resolve_runner_token_falls_back_to_infergrade_hub_token_env() {
        let _guard = env_test_lock().lock().expect("env lock");
        env::set_var("INFERGRADE_HUB_TOKEN", "default_token_value");
        let mut source: Option<&'static str> = None;
        let token = resolve_runner_token(None, false, &mut source)
            .expect("default env")
            .expect("token returned");
        assert_eq!(token, "default_token_value");
        assert_eq!(source, Some("env_default"));
        env::remove_var("INFERGRADE_HUB_TOKEN");
    }

    #[test]
    fn resolve_runner_token_returns_none_when_no_source_configured() {
        let _guard = env_test_lock().lock().expect("env lock");
        env::remove_var("INFERGRADE_HUB_TOKEN");
        let mut source: Option<&'static str> = None;
        let token = resolve_runner_token(None, false, &mut source).expect("no source");
        assert!(token.is_none());
        assert!(source.is_none());
    }

    #[test]
    fn resolve_runner_token_errors_when_explicit_env_var_missing() {
        let _guard = env_test_lock().lock().expect("env lock");
        let var_name = format!("INFERGRADE_NOT_SET_{}", std::process::id());
        env::remove_var(&var_name);
        let mut source: Option<&'static str> = None;
        let error = resolve_runner_token(Some(&var_name), false, &mut source)
            .expect_err("missing env var rejected");
        assert!(error.contains(&var_name));
    }

    #[test]
    fn help_documents_token_handling_without_contradiction() {
        assert!(HELP_TEXT.contains("INFERGRADE_HUB_TOKEN"));
        assert!(HELP_TEXT.contains("--runner-token-env"));
        assert!(HELP_TEXT.contains("--runner-token-stdin"));
        assert!(HELP_TEXT.contains("leaks via ps"));
        assert!(!HELP_TEXT.contains("normal Hub handoff is token-free"));
    }
}
