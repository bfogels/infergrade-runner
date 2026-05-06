use infergrade_runner_engine::{container_runtime_readiness, llama_cpp_runtime_plan, normalize_api_url};
use serde_json::{json, Value};
use std::env;
use std::process::ExitCode;

fn print_help() {
    println!(
        "InferGrade Runner CLI\n\nUSAGE:\n    infergrade-runner <command>\n\nCOMMANDS:\n    doctor [--api-url <url>]    Validate shared runner-engine basics\n    runtime plan                Show native runtime plan as JSON\n    containers check            Check optional Docker/Podman sandbox support\n    help                        Show this help\n\nThis Rust CLI is an early frontend over runner-engine. The Python runner-core CLI remains the execution bridge during migration."
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

fn run(args: &[String]) -> Result<Option<Value>, String> {
    match args.first().map(String::as_str) {
        None | Some("--help") | Some("-h") | Some("help") => {
            print_help();
            Ok(None)
        }
        Some("doctor") => command_doctor(&args[1..]).map(Some),
        Some("runtime") => command_runtime(&args[1..]).map(Some),
        Some("containers") => command_containers(&args[1..]).map(Some),
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
        assert_eq!(
            output["runtimes"]["podman"]["first_run_required"],
            false
        );
    }
}
