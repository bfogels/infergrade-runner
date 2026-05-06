use std::env;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Output, Stdio};

fn runner_core_src(repo_root: &Path) -> PathBuf {
    repo_root.join("python").join("runner-core").join("src")
}

fn bundled_runner_core_src(bundle_root: &Path) -> PathBuf {
    bundle_root.join("src")
}

fn find_repo_root_from(start: &Path) -> Option<PathBuf> {
    let mut current = Some(start);
    while let Some(path) = current {
        if runner_core_src(path).join("infergrade").is_dir() {
            return Some(path.to_path_buf());
        }
        current = path.parent();
    }
    None
}

fn find_bundled_runner_core_from(start: &Path) -> Option<PathBuf> {
    let mut current = Some(start);
    while let Some(path) = current {
        for candidate in [
            path.join("runner-core"),
            path.join("Resources").join("runner-core"),
            path.join("..").join("Resources").join("runner-core"),
            path.join("..")
                .join("..")
                .join("Resources")
                .join("runner-core"),
        ] {
            if bundled_runner_core_src(&candidate)
                .join("infergrade")
                .is_dir()
            {
                return candidate.canonicalize().ok().or(Some(candidate));
            }
        }
        current = path.parent();
    }
    None
}

fn fallback_repo_root() -> Option<PathBuf> {
    if let Some(value) = env::var_os("INFERGRADE_BUNDLED_RUNNER_CORE") {
        let path = PathBuf::from(value);
        if bundled_runner_core_src(&path).join("infergrade").is_dir() {
            return Some(path);
        }
    }

    let executable = env::current_exe().ok()?;
    let executable_dir = executable.parent()?;
    if let Some(path) = find_bundled_runner_core_from(executable_dir) {
        return Some(path);
    }

    if let Some(value) = env::var_os("INFERGRADE_RUNNER_REPO") {
        let path = PathBuf::from(value);
        if runner_core_src(&path).join("infergrade").is_dir() {
            return Some(path);
        }
    }

    find_repo_root_from(executable_dir)
}

fn pythonpath_with_runner(
    repo_root: &Path,
    existing: Option<OsString>,
) -> Result<OsString, String> {
    let repo_src = runner_core_src(repo_root);
    let bundled_src = bundled_runner_core_src(repo_root);
    let runner_src = if repo_src.join("infergrade").is_dir() {
        repo_src
    } else {
        bundled_src
    };
    if !runner_src.join("infergrade").is_dir() {
        return Err(format!(
            "Runner core source was not found at {}",
            runner_src.display()
        ));
    }

    let mut paths = vec![runner_src];
    if let Some(existing_value) = existing {
        paths.extend(env::split_paths(&existing_value));
    }
    env::join_paths(paths).map_err(|error| format!("could not build PYTHONPATH: {error}"))
}

fn run_command(
    program: &str,
    args: &[OsString],
    pythonpath: Option<OsString>,
) -> std::io::Result<ExitStatus> {
    let mut command = Command::new(program);
    command.args(args);
    command.stdin(Stdio::inherit());
    command.stdout(Stdio::inherit());
    command.stderr(Stdio::inherit());
    if let Some(value) = pythonpath {
        command.env("PYTHONPATH", value);
    }
    command.status()
}

fn run_command_output(
    program: &str,
    args: &[OsString],
    pythonpath: Option<OsString>,
) -> std::io::Result<Output> {
    let mut command = Command::new(program);
    command.args(args);
    if let Some(value) = pythonpath {
        command.env("PYTHONPATH", value);
    }
    command.output()
}

fn repo_python_args(args: &[OsString]) -> Vec<OsString> {
    let mut python_args = vec![OsString::from("-m"), OsString::from("infergrade")];
    python_args.extend(args.iter().cloned());
    python_args
}

fn command_exists(program: &str) -> bool {
    let args = vec![OsString::from("--version")];
    matches!(run_command(program, &args, None), Ok(status) if status.success())
}

fn command_exists_quiet(program: &str, args: &[&str]) -> bool {
    let args = args.iter().map(OsString::from).collect::<Vec<_>>();
    matches!(run_command_output(program, &args, None), Ok(output) if output.status.success())
}

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
}

fn verify_repo_python_invocation(repo_root: &Path) -> Result<String, String> {
    let pythonpath = pythonpath_with_runner(repo_root, env::var_os("PYTHONPATH"))?;
    let args = repo_python_args(&[OsString::from("--version")]);
    let mut last_not_found = None;
    let mut failures = Vec::new();
    for program in python_programs() {
        match run_command_output(program, &args, Some(pythonpath.clone())) {
            Ok(output) if output.status.success() => {
                let detail = String::from_utf8_lossy(&output.stdout).trim().to_string();
                return Ok(if detail.is_empty() {
                    format!("{program} -m infergrade --version")
                } else {
                    detail
                });
            }
            Ok(output) => {
                let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
                failures.push(format!(
                    "{program} exited with code {}{}",
                    output.status.code().unwrap_or(1),
                    if detail.is_empty() {
                        String::new()
                    } else {
                        format!(": {detail}")
                    }
                ));
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                last_not_found = Some(error);
            }
            Err(error) => failures.push(format!("{program} could not launch: {error}")),
        }
    }

    if !failures.is_empty() {
        return Err(failures.join("; "));
    }
    Err(format!(
        "could not find a Python interpreter to run the bundled Runner core: {}",
        last_not_found
            .map(|error| error.to_string())
            .unwrap_or_else(|| "no interpreter candidates were tried".to_string())
    ))
}

fn desktop_hardware_hint() -> (&'static str, &'static str) {
    if cfg!(target_os = "macos") && cfg!(target_arch = "aarch64") {
        return ("apple_silicon", "metal");
    }
    if command_exists_quiet("nvidia-smi", &["--query-gpu=name", "--format=csv,noheader"]) {
        return ("nvidia_gpu", "cuda");
    }
    if command_exists_quiet("rocm-smi", &["--showproductname"]) {
        return ("amd_gpu", "rocm");
    }
    ("cpu_only", "cpu")
}

fn llama_runtime_status(accelerator_api: &str) -> (&'static str, &'static str, &'static str) {
    let cli = command_exists_quiet("llama-cli", &["--version"]);
    let server = command_exists_quiet("llama-server", &["--version"]);
    if cli && server {
        return (
            "available",
            match accelerator_api {
                "metal" => "llama.cpp detected. Metal should be used when this build supports it.",
                "cuda" => "llama.cpp detected. CUDA runtime support depends on the selected build.",
                "rocm" => "llama.cpp detected. AMD runtime support depends on the selected build.",
                _ => "llama.cpp detected. CPU/Vulkan fallback may be available depending on the selected build.",
            },
            "ready",
        );
    }
    (
        "missing",
        "No app-managed or selected llama.cpp runtime is available yet.",
        "blocked",
    )
}

fn optional_container_status(program: &str) -> (&'static str, String) {
    if command_exists_quiet(program, &["--version"]) {
        (
            "found",
            format!("{program} detected; advanced sandboxed benchmarks can be enabled."),
        )
    } else {
        (
            "not_found",
            format!("{program} not found; advanced sandboxed benchmarks are disabled."),
        )
    }
}

fn desktop_readiness() -> String {
    let (hardware_class, accelerator_api) = desktop_hardware_hint();
    let (runtime_status, runtime_message, first_run) = llama_runtime_status(accelerator_api);
    let (docker_status, docker_message) = optional_container_status("docker");
    let (podman_status, podman_message) = optional_container_status("podman");
    format!(
        concat!(
            "{{",
            "\"status\":\"ok\",",
            "\"hardware_class\":\"{}\",",
            "\"accelerator_api\":\"{}\",",
            "\"native_benchmark_suite\":\"ready\",",
            "\"native_benchmark_message\":\"Docker is not required for your first local benchmark.\",",
            "\"llama_cpp_runtime\":\"{}\",",
            "\"llama_cpp_message\":\"{}\",",
            "\"first_run\":\"{}\",",
            "\"first_run_message\":\"{}\",",
            "\"docker\":{{\"status\":\"{}\",\"message\":\"{}\"}},",
            "\"podman\":{{\"status\":\"{}\",\"message\":\"{}\"}}",
            "}}"
        ),
        json_escape(hardware_class),
        json_escape(accelerator_api),
        json_escape(runtime_status),
        json_escape(runtime_message),
        json_escape(first_run),
        if first_run == "ready" {
            "Native first-run benchmark is ready."
        } else {
            "Select or install a native llama.cpp runtime before the first local benchmark."
        },
        json_escape(docker_status),
        json_escape(&docker_message),
        json_escape(podman_status),
        json_escape(&podman_message),
    )
}

fn desktop_self_test() -> Result<String, String> {
    if let Some(repo_root) = fallback_repo_root() {
        let pythonpath = pythonpath_with_runner(&repo_root, env::var_os("PYTHONPATH"))?;
        let first_path = env::split_paths(&pythonpath)
            .next()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "unknown".to_string());
        let version = verify_repo_python_invocation(&repo_root)?;
        return Ok(format!(
            "{{\"status\":\"ok\",\"runner_core\":\"bundled_or_repo\",\"invocation\":\"ok\",\"path\":\"{}\",\"version\":\"{}\"}}",
            json_escape(&first_path),
            json_escape(&version)
        ));
    }
    if command_exists("infergrade") {
        return Ok("{\"status\":\"ok\",\"runner_core\":\"path\",\"detail\":\"infergrade is available on PATH\"}".to_string());
    }
    Err(
        "Packaged Runner core is unavailable. The desktop app could not find its bundled runner-core resource, and infergrade is not on PATH.".to_string(),
    )
}

fn run_repo_python(repo_root: &Path, args: &[OsString]) -> Result<ExitStatus, String> {
    let pythonpath = pythonpath_with_runner(repo_root, env::var_os("PYTHONPATH"))?;
    let python_args = repo_python_args(args);
    let mut last_not_found = None;
    for program in python_programs() {
        match run_command(program, &python_args, Some(pythonpath.clone())) {
            Ok(status) => return Ok(status),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                last_not_found = Some(error);
            }
            Err(error) => return Err(format!("could not launch {program}: {error}")),
        }
    }
    Err(format!(
        "could not find a Python interpreter to run the bundled Runner core: {}",
        last_not_found
            .map(|error| error.to_string())
            .unwrap_or_else(|| "no interpreter candidates were tried".to_string())
    ))
}

fn python_programs() -> &'static [&'static str] {
    if cfg!(windows) {
        &["py", "python", "python3"]
    } else {
        &["python3", "python"]
    }
}

fn main() {
    let args = env::args_os().skip(1).collect::<Vec<_>>();
    if args == [OsString::from("desktop-self-test")] {
        match desktop_self_test() {
            Ok(payload) => {
                println!("{payload}");
                std::process::exit(0);
            }
            Err(error) => {
                eprintln!("{error}");
                std::process::exit(1);
            }
        }
    }
    if args == [OsString::from("desktop-readiness")] {
        println!("{}", desktop_readiness());
        std::process::exit(0);
    }

    if let Some(repo_root) = fallback_repo_root() {
        match run_repo_python(&repo_root, &args) {
            Ok(status) => std::process::exit(status.code().unwrap_or(1)),
            Err(error) => {
                eprintln!("{error}");
                std::process::exit(1);
            }
        }
    }

    match run_command("infergrade", &args, None) {
        Ok(status) => std::process::exit(status.code().unwrap_or(1)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            eprintln!(
                "infergrade was not found on PATH, no bundled Runner core resource was found, and INFERGRADE_RUNNER_REPO does not point to a Runner checkout."
            );
            std::process::exit(1);
        }
        Err(error) => {
            eprintln!("could not launch infergrade from PATH: {error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn finds_repo_root_from_nested_sidecar_path() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("..")
            .canonicalize()
            .expect("repo root");
        let nested = root
            .join("apps")
            .join("desktop-runner")
            .join("src-tauri")
            .join("binaries");

        assert_eq!(find_repo_root_from(&nested), Some(root));
    }

    #[test]
    fn prepends_runner_core_to_pythonpath() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("..")
            .join("..")
            .join("..")
            .canonicalize()
            .expect("repo root");
        let existing = env::join_paths([PathBuf::from("existing")]).expect("existing path");

        let pythonpath = pythonpath_with_runner(&root, Some(existing)).expect("pythonpath");
        let paths = env::split_paths(&pythonpath).collect::<Vec<_>>();

        assert_eq!(paths[0], runner_core_src(&root));
        assert_eq!(paths[1], PathBuf::from("existing"));
    }

    #[test]
    fn repo_python_invocation_runs_infergrade_module() {
        let args = vec![OsString::from("--version")];
        let python_args = repo_python_args(&args);

        assert_eq!(python_args[0], OsString::from("-m"));
        assert_eq!(python_args[1], OsString::from("infergrade"));
        assert_eq!(python_args[2], OsString::from("--version"));
    }

    #[test]
    fn uses_windows_python_launcher_first_on_windows() {
        if cfg!(windows) {
            assert_eq!(python_programs()[0], "py");
        } else {
            assert_eq!(python_programs()[0], "python3");
        }
    }

    #[test]
    fn finds_bundled_runner_core_resource_near_packaged_sidecar() {
        let temp = env::temp_dir().join(format!("infergrade-sidecar-test-{}", std::process::id()));
        let sidecar_dir = temp
            .join("InferGrade Runner.app")
            .join("Contents")
            .join("MacOS")
            .join("binaries");
        let bundled_src = temp
            .join("InferGrade Runner.app")
            .join("Contents")
            .join("Resources")
            .join("runner-core")
            .join("src")
            .join("infergrade");
        std::fs::create_dir_all(&sidecar_dir).expect("sidecar dir");
        std::fs::create_dir_all(&bundled_src).expect("bundled infergrade package");

        let resolved = find_bundled_runner_core_from(&sidecar_dir).expect("bundled runner core");
        assert_eq!(
            resolved,
            temp.join("InferGrade Runner.app")
                .join("Contents")
                .join("Resources")
                .join("runner-core")
                .canonicalize()
                .expect("canonical bundled runner core")
        );

        let _ = std::fs::remove_dir_all(temp);
    }

    #[test]
    fn desktop_self_test_reports_invocable_runner_core() {
        let payload = desktop_self_test().expect("desktop self-test");

        assert!(payload.contains("\"runner_core\":\"bundled_or_repo\""));
        assert!(payload.contains("\"invocation\":\"ok\""));
    }

    #[test]
    fn desktop_readiness_reports_native_first_and_optional_containers() {
        let payload = desktop_readiness();

        assert!(payload.contains("\"native_benchmark_suite\":\"ready\""));
        assert!(payload.contains("\"first_run\""));
        assert!(payload.contains("\"docker\""));
        assert!(payload.contains("Docker is not required for your first local benchmark."));
        assert!(payload.contains("\"podman\""));
    }
}
