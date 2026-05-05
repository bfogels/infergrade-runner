use std::env;
use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus, Stdio};

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
            path.join("..").join("..").join("Resources").join("runner-core"),
        ] {
            if bundled_runner_core_src(&candidate).join("infergrade").is_dir() {
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

    if let Some(value) = env::var_os("INFERGRADE_RUNNER_REPO") {
        let path = PathBuf::from(value);
        if runner_core_src(&path).join("infergrade").is_dir() {
            return Some(path);
        }
    }

    let executable = env::current_exe().ok()?;
    let executable_dir = executable.parent()?;
    find_bundled_runner_core_from(executable_dir).or_else(|| find_repo_root_from(executable_dir))
}

fn pythonpath_with_runner(repo_root: &Path, existing: Option<OsString>) -> Result<OsString, String> {
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

fn run_command(program: &str, args: &[OsString], pythonpath: Option<OsString>) -> std::io::Result<ExitStatus> {
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

fn repo_python_args(args: &[OsString]) -> Vec<OsString> {
    let mut python_args = vec![OsString::from("-m"), OsString::from("infergrade")];
    python_args.extend(args.iter().cloned());
    python_args
}

fn command_exists(program: &str) -> bool {
    let args = vec![OsString::from("--version")];
    matches!(run_command(program, &args, None), Ok(status) if status.success())
}

fn desktop_self_test() -> Result<String, String> {
    if let Some(repo_root) = fallback_repo_root() {
        let pythonpath = pythonpath_with_runner(&repo_root, env::var_os("PYTHONPATH"))?;
        let first_path = env::split_paths(&pythonpath)
            .next()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "unknown".to_string());
        return Ok(format!(
            "{{\"status\":\"ok\",\"runner_core\":\"bundled_or_repo\",\"path\":\"{}\"}}",
            first_path.replace('\\', "\\\\").replace('"', "\\\"")
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
        let temp = env::temp_dir().join(format!(
            "infergrade-sidecar-test-{}",
            std::process::id()
        ));
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
}
