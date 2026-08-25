use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::env;
use std::ffi::OsString;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Output, Stdio};

const MACOS_GUI_PATH_DEFAULTS: &[&str] = &[
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/Applications/Docker.app/Contents/Resources/bin",
    "/usr/bin",
    "/bin",
    "/usr/sbin",
    "/sbin",
];
const BUNDLED_PYTHON_RECEIPT: &str = "infergrade-python-runtime-receipt.json";

#[derive(Clone, Debug)]
struct BundledPythonRuntime {
    root: PathBuf,
    executable: PathBuf,
    ca_bundle: PathBuf,
    receipt: Value,
}

fn runner_core_src(repo_root: &Path) -> PathBuf {
    repo_root.join("python").join("runner-core").join("src")
}

fn bundled_runner_core_src(bundle_root: &Path) -> PathBuf {
    bundle_root.join("src")
}

fn requires_bundled_python(runner_root: &Path) -> bool {
    bundled_runner_core_src(runner_root)
        .join("infergrade")
        .is_dir()
        && !runner_core_src(runner_root).join("infergrade").is_dir()
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
            path.join("usr")
                .join("lib")
                .join("InferGrade Runner")
                .join("runner-core"),
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

    #[cfg(target_os = "linux")]
    for candidate in [
        PathBuf::from("/usr/lib/InferGrade Runner/runner-core"),
        PathBuf::from("/usr/lib/infergrade-desktop-runner/runner-core"),
    ] {
        if bundled_runner_core_src(&candidate)
            .join("infergrade")
            .is_dir()
        {
            return candidate.canonicalize().ok().or(Some(candidate));
        }
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

    if let Some(value) = env::var_os("INFERGRADE_RUNNER_REPO") {
        let path = PathBuf::from(value);
        if runner_core_src(&path).join("infergrade").is_dir() {
            return Some(path);
        }
    }

    let executable = env::current_exe().ok()?;
    let executable_dir = executable.parent()?;
    if let Some(path) = find_repo_root_from(executable_dir) {
        return Some(path);
    }
    if let Some(path) = find_bundled_runner_core_from(executable_dir) {
        return Some(path);
    }
    None
}

fn relative_receipt_path(root: &Path, value: &Value) -> Option<PathBuf> {
    let raw = value.as_str()?;
    let path = PathBuf::from(raw);
    if path.is_absolute()
        || path
            .components()
            .any(|component| !matches!(component, std::path::Component::Normal(_)))
    {
        return None;
    }
    Some(root.join(path))
}

fn file_sha256(path: &Path) -> Option<String> {
    let mut file = File::open(path).ok()?;
    let mut digest = Sha256::new();
    // Windows processes commonly start with a 1 MiB main-thread stack. Keep
    // the integrity buffer on the heap so receipt verification cannot exhaust
    // that stack before the bundled interpreter is launched.
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        let count = file.read(&mut buffer).ok()?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Some(format!("{:x}", digest.finalize()))
}

fn bundled_python_runtime_at(root: &Path) -> Option<BundledPythonRuntime> {
    let receipt_path = root.join(BUNDLED_PYTHON_RECEIPT);
    let receipt: Value = serde_json::from_slice(&std::fs::read(receipt_path).ok()?).ok()?;
    if receipt.get("schema_version")?.as_str()? != "infergrade.desktop_python_runtime_receipt.v1" {
        return None;
    }
    let executable = relative_receipt_path(root, receipt.get("executable")?)?;
    let ca_bundle = relative_receipt_path(root, receipt.get("ca_bundle")?)?;
    let license = relative_receipt_path(root, receipt.get("license_path")?)?;
    if !executable.is_file() || !ca_bundle.is_file() || !license.is_file() {
        return None;
    }
    for (path, field) in [
        (&executable, "executable_sha256"),
        (&ca_bundle, "ca_bundle_sha256"),
        (&license, "license_sha256"),
    ] {
        if file_sha256(path)?.as_str() != receipt.get(field)?.as_str()? {
            return None;
        }
    }
    Some(BundledPythonRuntime {
        root: root.to_path_buf(),
        executable,
        ca_bundle,
        receipt,
    })
}

fn find_bundled_python_from(start: &Path) -> Result<Option<BundledPythonRuntime>, String> {
    let mut current = Some(start);
    while let Some(path) = current {
        for candidate in [
            path.join("python-runtime"),
            path.join("Resources").join("python-runtime"),
            path.join("usr")
                .join("lib")
                .join("InferGrade Runner")
                .join("python-runtime"),
            path.join("usr")
                .join("lib")
                .join("infergrade-desktop-runner")
                .join("python-runtime"),
        ] {
            if candidate.join(BUNDLED_PYTHON_RECEIPT).is_file() {
                return bundled_python_runtime_at(&candidate)
                    .map(Some)
                    .ok_or_else(|| {
                        format!(
                        "bundled Python runtime failed its receipt or file-integrity check at {}",
                        candidate.display()
                    )
                    });
            }
        }
        current = path.parent();
    }

    #[cfg(target_os = "linux")]
    for candidate in [
        PathBuf::from("/usr/lib/InferGrade Runner/python-runtime"),
        PathBuf::from("/usr/lib/infergrade-desktop-runner/python-runtime"),
    ] {
        if candidate.join(BUNDLED_PYTHON_RECEIPT).is_file() {
            return bundled_python_runtime_at(&candidate)
                .map(Some)
                .ok_or_else(|| {
                    format!(
                        "bundled Python runtime failed its receipt or file-integrity check at {}",
                        candidate.display()
                    )
                });
        }
    }
    Ok(None)
}

fn bundled_python_runtime() -> Result<Option<BundledPythonRuntime>, String> {
    if let Some(value) = env::var_os("INFERGRADE_BUNDLED_PYTHON_ROOT") {
        let root = PathBuf::from(value);
        return bundled_python_runtime_at(&root).map(Some).ok_or_else(|| {
            format!(
                "configured bundled Python runtime failed its receipt or file-integrity check at {}",
                root.display()
            )
        });
    }
    let executable = env::current_exe()
        .map_err(|error| format!("could not resolve the sidecar executable: {error}"))?;
    let executable_dir = executable
        .parent()
        .ok_or_else(|| "sidecar executable has no parent directory".to_string())?;
    find_bundled_python_from(executable_dir)
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

fn path_with_macos_gui_defaults(existing: Option<OsString>) -> Option<OsString> {
    if !cfg!(target_os = "macos") {
        return existing;
    }

    let mut paths = Vec::new();
    if let Some(existing_value) = existing {
        paths.extend(env::split_paths(&existing_value));
    }
    for path in MACOS_GUI_PATH_DEFAULTS {
        let path = PathBuf::from(path);
        if !paths.iter().any(|existing| existing == &path) {
            paths.push(path);
        }
    }
    env::join_paths(paths).ok()
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
    if let Some(value) = path_with_macos_gui_defaults(env::var_os("PATH")) {
        command.env("PATH", value);
    }
    #[cfg(windows)]
    return run_in_kill_on_close_job(command);
    #[cfg(not(windows))]
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
    if let Some(value) = path_with_macos_gui_defaults(env::var_os("PATH")) {
        command.env("PATH", value);
    }
    command.output()
}

fn configure_bundled_python(command: &mut Command, runtime: &BundledPythonRuntime) {
    command.env("PYTHONHOME", &runtime.root);
    command.env("PYTHONNOUSERSITE", "1");
    command.env("PYTHONDONTWRITEBYTECODE", "1");
    if env::var_os("SSL_CERT_FILE").is_none() {
        command.env("SSL_CERT_FILE", &runtime.ca_bundle);
    }
}

fn run_bundled_python(
    runtime: &BundledPythonRuntime,
    args: &[OsString],
    pythonpath: OsString,
) -> std::io::Result<ExitStatus> {
    let mut command = Command::new(&runtime.executable);
    command.args(args);
    command.stdin(Stdio::inherit());
    command.stdout(Stdio::inherit());
    command.stderr(Stdio::inherit());
    command.env("PYTHONPATH", pythonpath);
    configure_bundled_python(&mut command, runtime);
    if let Some(value) = path_with_macos_gui_defaults(env::var_os("PATH")) {
        command.env("PATH", value);
    }
    #[cfg(windows)]
    return run_in_kill_on_close_job(command);
    #[cfg(not(windows))]
    command.status()
}

#[cfg(windows)]
fn run_in_kill_on_close_job(mut command: Command) -> std::io::Result<ExitStatus> {
    use std::mem::size_of;
    use std::os::windows::io::AsRawHandle;
    use std::ptr;
    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
        SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    unsafe {
        let job = CreateJobObjectW(ptr::null(), ptr::null());
        if job.is_null() {
            return Err(std::io::Error::last_os_error());
        }
        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        ) == 0
        {
            let error = std::io::Error::last_os_error();
            CloseHandle(job);
            return Err(error);
        }
        let mut child = match command.spawn() {
            Ok(child) => child,
            Err(error) => {
                CloseHandle(job);
                return Err(error);
            }
        };
        if AssignProcessToJobObject(job, child.as_raw_handle() as _) == 0 {
            let error = std::io::Error::last_os_error();
            let _ = child.kill();
            let _ = child.wait();
            CloseHandle(job);
            return Err(error);
        }
        let status = child.wait();
        CloseHandle(job);
        status
    }
}

fn run_bundled_python_output(
    runtime: &BundledPythonRuntime,
    args: &[OsString],
    pythonpath: OsString,
) -> std::io::Result<Output> {
    let mut command = Command::new(&runtime.executable);
    command.args(args);
    command.env("PYTHONPATH", pythonpath);
    configure_bundled_python(&mut command, runtime);
    if let Some(value) = path_with_macos_gui_defaults(env::var_os("PATH")) {
        command.env("PATH", value);
    }
    command.output()
}

#[cfg(unix)]
fn exec_command(program: &str, args: &[OsString], pythonpath: Option<OsString>) -> std::io::Error {
    use std::os::unix::process::CommandExt;

    let mut command = Command::new(program);
    command.args(args);
    command.stdin(Stdio::inherit());
    command.stdout(Stdio::inherit());
    command.stderr(Stdio::inherit());
    if let Some(value) = pythonpath {
        command.env("PYTHONPATH", value);
    }
    if let Some(value) = path_with_macos_gui_defaults(env::var_os("PATH")) {
        command.env("PATH", value);
    }
    command.exec()
}

#[cfg(unix)]
fn exec_bundled_python(
    runtime: &BundledPythonRuntime,
    args: &[OsString],
    pythonpath: OsString,
) -> std::io::Error {
    use std::os::unix::process::CommandExt;

    let mut command = Command::new(&runtime.executable);
    command.args(args);
    command.stdin(Stdio::inherit());
    command.stdout(Stdio::inherit());
    command.stderr(Stdio::inherit());
    command.env("PYTHONPATH", pythonpath);
    configure_bundled_python(&mut command, runtime);
    if let Some(value) = path_with_macos_gui_defaults(env::var_os("PATH")) {
        command.env("PATH", value);
    }
    command.exec()
}

fn repo_python_args(args: &[OsString]) -> Vec<OsString> {
    // The runner core can live inside a code-signed application bundle. Prevent
    // Python imports from adding __pycache__ resources that invalidate the seal.
    let mut python_args = vec![
        OsString::from("-B"),
        OsString::from("-m"),
        OsString::from("infergrade"),
    ];
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

fn verify_repo_python_invocation(
    repo_root: &Path,
) -> Result<(String, Option<BundledPythonRuntime>), String> {
    let pythonpath = pythonpath_with_runner(repo_root, env::var_os("PYTHONPATH"))?;
    let args = repo_python_args(&[OsString::from("--version")]);
    if let Some(runtime) = bundled_python_runtime()? {
        match run_bundled_python_output(&runtime, &args, pythonpath.clone()) {
            Ok(output) if output.status.success() => {
                let detail = String::from_utf8_lossy(&output.stdout).trim().to_string();
                return Ok((detail, Some(runtime)));
            }
            Ok(output) => {
                let detail = String::from_utf8_lossy(&output.stderr).trim().to_string();
                return Err(format!(
                    "bundled Python exited with code {}{}",
                    output.status.code().unwrap_or(1),
                    if detail.is_empty() {
                        String::new()
                    } else {
                        format!(": {detail}")
                    }
                ));
            }
            Err(error) => return Err(format!("bundled Python could not launch: {error}")),
        }
    }
    if requires_bundled_python(repo_root) {
        return Err(
            "packaged Runner core is present but its self-contained Python runtime is missing"
                .to_string(),
        );
    }
    let mut last_not_found = None;
    let mut failures = Vec::new();
    for program in python_programs() {
        match run_command_output(program, &args, Some(pythonpath.clone())) {
            Ok(output) if output.status.success() => {
                let detail = String::from_utf8_lossy(&output.stdout).trim().to_string();
                return Ok((
                    if detail.is_empty() {
                        format!("{program} -m infergrade --version")
                    } else {
                        detail
                    },
                    None,
                ));
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

fn native_suite_status(
    runtime_first_run: &str,
) -> (&'static str, &'static str, &'static str, &'static str) {
    if runtime_first_run == "ready" {
        (
            "ready",
            "Native llama.cpp runtime is available. First-run can run locally with a selected GGUF model; Docker remains optional for advanced sandboxed benchmarks.",
            "ready",
            "Native first-run is available after selecting a local GGUF model.",
        )
    } else {
        (
            "setup_needed",
            "Select or install a native llama.cpp runtime first.",
            "blocked",
            "Select or install a native llama.cpp runtime before starting first-run.",
        )
    }
}

fn desktop_readiness() -> String {
    let (hardware_class, accelerator_api) = desktop_hardware_hint();
    let (runtime_status, runtime_message, runtime_first_run) =
        llama_runtime_status(accelerator_api);
    let (native_suite, native_message, first_run, first_run_message) =
        native_suite_status(runtime_first_run);
    let (docker_status, docker_message) = optional_container_status("docker");
    let (podman_status, podman_message) = optional_container_status("podman");
    json!({
        "status": "ok",
        "hardware_class": hardware_class,
        "accelerator_api": accelerator_api,
        "native_benchmark_suite": native_suite,
        "native_benchmark_message": native_message,
        "llama_cpp_runtime": runtime_status,
        "llama_cpp_message": runtime_message,
        "first_run": first_run,
        "first_run_message": first_run_message,
        "docker": {"status": docker_status, "message": docker_message},
        "podman": {"status": podman_status, "message": podman_message},
    })
    .to_string()
}

fn desktop_self_test() -> Result<String, String> {
    if let Some(repo_root) = fallback_repo_root() {
        let pythonpath = pythonpath_with_runner(&repo_root, env::var_os("PYTHONPATH"))?;
        let first_path = env::split_paths(&pythonpath)
            .next()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "unknown".to_string());
        let (version, bundled_python) = verify_repo_python_invocation(&repo_root)?;
        let python_runtime = bundled_python
            .as_ref()
            .map(|runtime| {
                json!({
                    "source": "bundled",
                    "self_contained": true,
                    "distribution": runtime.receipt.get("distribution"),
                    "release": runtime.receipt.get("release"),
                    "python_version": runtime.receipt.get("python_version"),
                    "target": runtime.receipt.get("target"),
                    "archive_sha256": runtime.receipt.get("archive_sha256"),
                    "ca_bundle": "bundled_verified",
                })
            })
            .unwrap_or_else(|| {
                json!({
                    "source": "system_fallback",
                    "self_contained": false,
                })
            });
        return Ok(json!({
            "status": "ok",
            "runner_core": "bundled_or_repo",
            "invocation": "ok",
            "path": first_path,
            "version": version,
            "python_runtime": python_runtime,
        })
        .to_string());
    }
    if command_exists("infergrade") {
        return Ok(json!({
            "status": "ok",
            "runner_core": "path",
            "detail": "infergrade is available on PATH",
        })
        .to_string());
    }
    Err(
        "Packaged Runner core is unavailable. The desktop app could not find its bundled runner-core resource, and infergrade is not on PATH.".to_string(),
    )
}

fn run_repo_python(repo_root: &Path, args: &[OsString]) -> Result<ExitStatus, String> {
    let pythonpath = pythonpath_with_runner(repo_root, env::var_os("PYTHONPATH"))?;
    let python_args = repo_python_args(args);
    if let Some(runtime) = bundled_python_runtime()? {
        return run_bundled_python(&runtime, &python_args, pythonpath)
            .map_err(|error| format!("could not launch bundled Python: {error}"));
    }
    if requires_bundled_python(repo_root) {
        return Err(
            "packaged Runner core is present but its self-contained Python runtime is missing"
                .to_string(),
        );
    }
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

#[cfg(unix)]
fn exec_repo_python(repo_root: &Path, args: &[OsString]) -> Result<(), String> {
    let pythonpath = pythonpath_with_runner(repo_root, env::var_os("PYTHONPATH"))?;
    let python_args = repo_python_args(args);
    if let Some(runtime) = bundled_python_runtime()? {
        let error = exec_bundled_python(&runtime, &python_args, pythonpath);
        return Err(format!("could not launch bundled Python: {error}"));
    }
    if requires_bundled_python(repo_root) {
        return Err(
            "packaged Runner core is present but its self-contained Python runtime is missing"
                .to_string(),
        );
    }
    let mut last_not_found = None;
    for program in python_programs() {
        let error = exec_command(program, &python_args, Some(pythonpath.clone()));
        if error.kind() == std::io::ErrorKind::NotFound {
            last_not_found = Some(error);
            continue;
        }
        return Err(format!("could not launch {program}: {error}"));
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

#[cfg(unix)]
fn is_long_running_command(args: &[OsString]) -> bool {
    args.first()
        .and_then(|value| value.to_str())
        .map(|value| matches!(value, "start" | "observe-runtime"))
        .unwrap_or(false)
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

    #[cfg(unix)]
    if is_long_running_command(&args) {
        if let Some(repo_root) = fallback_repo_root() {
            if let Err(error) = exec_repo_python(&repo_root, &args) {
                eprintln!("{error}");
                std::process::exit(1);
            }
        }

        let error = exec_command("infergrade", &args, None);
        if error.kind() == std::io::ErrorKind::NotFound {
            eprintln!(
                "infergrade was not found on PATH, no bundled Runner core resource was found, and INFERGRADE_RUNNER_REPO does not point to a Runner checkout."
            );
        } else {
            eprintln!("could not launch infergrade from PATH: {error}");
        }
        std::process::exit(1);
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
    fn macos_gui_path_defaults_include_homebrew_and_docker_locations() {
        let existing = env::join_paths([PathBuf::from("/usr/bin")]).expect("existing path");
        let path = path_with_macos_gui_defaults(Some(existing)).expect("path");
        let paths = env::split_paths(&path).collect::<Vec<_>>();

        if cfg!(target_os = "macos") {
            assert!(paths.contains(&PathBuf::from("/usr/local/bin")));
            assert!(paths.contains(&PathBuf::from("/opt/homebrew/bin")));
            assert!(paths.contains(&PathBuf::from(
                "/Applications/Docker.app/Contents/Resources/bin"
            )));
            assert_eq!(
                paths
                    .iter()
                    .filter(|path| path.as_path() == Path::new("/usr/bin"))
                    .count(),
                1
            );
        } else {
            assert_eq!(paths, vec![PathBuf::from("/usr/bin")]);
        }
    }

    #[test]
    fn repo_python_invocation_runs_infergrade_module() {
        let args = vec![OsString::from("--version")];
        let python_args = repo_python_args(&args);

        assert_eq!(python_args[0], OsString::from("-B"));
        assert_eq!(python_args[1], OsString::from("-m"));
        assert_eq!(python_args[2], OsString::from("infergrade"));
        assert_eq!(python_args[3], OsString::from("--version"));
    }

    #[cfg(unix)]
    #[test]
    fn long_running_commands_replace_the_unix_sidecar_process() {
        assert!(is_long_running_command(&[OsString::from("start")]));
        assert!(is_long_running_command(&[OsString::from(
            "observe-runtime"
        )]));
        assert!(!is_long_running_command(&[OsString::from(
            "desktop-readiness"
        )]));
        assert!(!is_long_running_command(&[OsString::from(
            "desktop-self-test"
        )]));
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
    fn finds_bundled_runner_core_resource_in_appimage_layout() {
        let temp = env::temp_dir().join(format!(
            "infergrade-sidecar-appimage-test-{}",
            std::process::id()
        ));
        let sidecar_dir = temp.join("usr").join("bin");
        let bundled_src = temp
            .join("usr")
            .join("lib")
            .join("InferGrade Runner")
            .join("runner-core")
            .join("src")
            .join("infergrade");
        std::fs::create_dir_all(&sidecar_dir).expect("sidecar dir");
        std::fs::create_dir_all(&bundled_src).expect("bundled infergrade package");

        let resolved = find_bundled_runner_core_from(&sidecar_dir).expect("bundled runner core");
        assert_eq!(
            resolved,
            temp.join("usr")
                .join("lib")
                .join("InferGrade Runner")
                .join("runner-core")
                .canonicalize()
                .expect("canonical bundled runner core")
        );

        let _ = std::fs::remove_dir_all(temp);
    }

    #[test]
    fn packaged_runner_core_requires_the_bundled_python_runtime() {
        let temp = env::temp_dir().join(format!(
            "infergrade-sidecar-packaged-runtime-test-{}",
            std::process::id()
        ));
        let bundled_src = temp.join("src").join("infergrade");
        std::fs::create_dir_all(&bundled_src).expect("bundled infergrade package");

        assert!(requires_bundled_python(&temp));

        let _ = std::fs::remove_dir_all(temp);
    }

    #[test]
    fn bundled_python_requires_receipt_and_matching_file_digests() {
        let temp = env::temp_dir().join(format!(
            "infergrade-bundled-python-test-{}",
            std::process::id()
        ));
        let root = temp.join("python-runtime");
        let executable = root.join("bin").join("python-test");
        let ca_bundle = root.join("certs").join("cacert.pem");
        let license = root.join("LICENSE.txt");
        std::fs::create_dir_all(executable.parent().expect("executable parent"))
            .expect("executable parent");
        std::fs::create_dir_all(ca_bundle.parent().expect("CA parent")).expect("CA parent");
        std::fs::write(&executable, b"python-runtime").expect("executable");
        std::fs::write(&ca_bundle, b"ca-bundle").expect("CA bundle");
        std::fs::write(&license, b"license").expect("license");
        let receipt = json!({
            "schema_version": "infergrade.desktop_python_runtime_receipt.v1",
            "distribution": "test",
            "release": "test",
            "python_version": "3.12.0",
            "target": "test-target",
            "archive_sha256": "a".repeat(64),
            "executable": "bin/python-test",
            "executable_sha256": file_sha256(&executable).expect("executable digest"),
            "ca_bundle": "certs/cacert.pem",
            "ca_bundle_sha256": file_sha256(&ca_bundle).expect("CA digest"),
            "license_path": "LICENSE.txt",
            "license_sha256": file_sha256(&license).expect("license digest"),
        });
        std::fs::write(
            root.join(BUNDLED_PYTHON_RECEIPT),
            serde_json::to_vec(&receipt).expect("receipt JSON"),
        )
        .expect("receipt");

        let resolved = find_bundled_python_from(&temp)
            .expect("runtime search")
            .expect("bundled Python");
        assert_eq!(resolved.root, root);
        std::fs::write(&ca_bundle, b"tampered-ca-bundle").expect("tamper CA bundle");
        assert!(find_bundled_python_from(&temp).is_err());

        let _ = std::fs::remove_dir_all(temp);
    }

    #[test]
    fn ignores_development_python_placeholder_without_a_receipt() {
        let temp = env::temp_dir().join(format!(
            "infergrade-bundled-python-placeholder-test-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(temp.join("python-runtime")).expect("placeholder runtime");

        assert!(find_bundled_python_from(&temp)
            .expect("placeholder search")
            .is_none());

        let _ = std::fs::remove_dir_all(temp);
    }

    #[test]
    fn desktop_self_test_reports_invocable_runner_core() {
        let payload = desktop_self_test().expect("desktop self-test");

        assert!(payload.contains("\"runner_core\":\"bundled_or_repo\""));
        assert!(payload.contains("\"invocation\":\"ok\""));
    }

    #[test]
    fn desktop_readiness_reports_environment_truth_and_optional_containers() {
        let payload = desktop_readiness();

        assert!(payload.contains("\"native_benchmark_suite\""));
        assert!(payload.contains("\"first_run\""));
        assert!(
            payload.contains("First-run can run locally with a selected GGUF model")
                || payload.contains("Select or install a native llama.cpp runtime first")
        );
        assert!(!payload.contains("first-run benchmark executor is still in progress"));
        assert!(payload.contains("\"docker\""));
        assert!(payload.contains("\"podman\""));
    }

    #[test]
    fn native_suite_status_distinguishes_runtime_from_executor_readiness() {
        assert_eq!(native_suite_status("ready").0, "ready");
        assert_eq!(native_suite_status("ready").2, "ready");
        assert_eq!(native_suite_status("blocked").0, "setup_needed");
        assert_eq!(native_suite_status("blocked").2, "blocked");
    }
}
