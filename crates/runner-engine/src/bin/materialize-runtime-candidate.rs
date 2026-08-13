use infergrade_runner_engine::{
    install_managed_llama_cpp_runtime_from_manifest_entry,
    validate_runtime_candidate_materialization, ManagedRuntimeInstallOptions,
};
use serde_json::Value;
use std::env;
use std::fs;
use std::path::PathBuf;

const USAGE: &str =
    "Usage: cargo run -p infergrade_runner_engine --bin materialize-runtime-candidate -- \\
  --manifest-entry <candidate.json> --archive <runtime.tar.gz> \\
  --runtime-cache-dir <new-or-empty-dir> --consent-archive-sha256 <sha256>";

#[derive(Debug, PartialEq)]
struct Args {
    manifest_entry: PathBuf,
    archive: PathBuf,
    runtime_cache_dir: PathBuf,
    consent_archive_sha256: String,
}

fn parse_args(values: impl IntoIterator<Item = String>) -> Result<Option<Args>, String> {
    let mut values = values.into_iter();
    let mut manifest_entry = None;
    let mut archive = None;
    let mut runtime_cache_dir = None;
    let mut consent_archive_sha256 = None;

    while let Some(flag) = values.next() {
        if matches!(flag.as_str(), "-h" | "--help") {
            return Ok(None);
        }
        let value = values
            .next()
            .ok_or_else(|| format!("missing value for {flag}"))?;
        let destination = match flag.as_str() {
            "--manifest-entry" => &mut manifest_entry,
            "--archive" => &mut archive,
            "--runtime-cache-dir" => &mut runtime_cache_dir,
            "--consent-archive-sha256" => &mut consent_archive_sha256,
            _ => return Err(format!("unknown argument: {flag}")),
        };
        if destination.replace(value).is_some() {
            return Err(format!("duplicate argument: {flag}"));
        }
    }

    Ok(Some(Args {
        manifest_entry: PathBuf::from(
            manifest_entry.ok_or_else(|| "--manifest-entry is required".to_string())?,
        ),
        archive: PathBuf::from(archive.ok_or_else(|| "--archive is required".to_string())?),
        runtime_cache_dir: PathBuf::from(
            runtime_cache_dir.ok_or_else(|| "--runtime-cache-dir is required".to_string())?,
        ),
        consent_archive_sha256: consent_archive_sha256
            .ok_or_else(|| "--consent-archive-sha256 is required".to_string())?,
    }))
}

fn run(args: Args) -> Result<Value, String> {
    let entry: Value =
        serde_json::from_slice(&fs::read(&args.manifest_entry).map_err(|error| {
            format!(
                "could not read candidate manifest `{}`: {error}",
                args.manifest_entry.display()
            )
        })?)
        .map_err(|error| format!("candidate manifest is invalid JSON: {error}"))?;
    validate_runtime_candidate_materialization(
        &entry,
        &args.consent_archive_sha256,
        &args.runtime_cache_dir,
    )?;

    let expected_size = entry
        .pointer("/archive/size_bytes")
        .and_then(Value::as_u64)
        .ok_or_else(|| "candidate archive.size_bytes is required".to_string())?;
    let actual_size = fs::metadata(&args.archive)
        .map_err(|error| {
            format!(
                "could not inspect candidate archive `{}`: {error}",
                args.archive.display()
            )
        })?
        .len();
    if actual_size != expected_size {
        return Err(format!(
            "candidate archive length mismatch: expected {expected_size}, got {actual_size}"
        ));
    }
    let archive_bytes = fs::read(&args.archive).map_err(|error| {
        format!(
            "could not read candidate archive `{}`: {error}",
            args.archive.display()
        )
    })?;

    fs::create_dir_all(&args.runtime_cache_dir).map_err(|error| {
        format!(
            "could not create isolated runtime cache `{}`: {error}",
            args.runtime_cache_dir.display()
        )
    })?;
    validate_runtime_candidate_materialization(
        &entry,
        &args.consent_archive_sha256,
        &args.runtime_cache_dir,
    )?;
    env::set_var("INFERGRADE_RUNTIME_CACHE_DIR", &args.runtime_cache_dir);
    install_managed_llama_cpp_runtime_from_manifest_entry(
        entry,
        ManagedRuntimeInstallOptions {
            runtime_id: None,
            archive_bytes: Some(archive_bytes),
        },
    )
}

fn main() {
    let args = match parse_args(env::args().skip(1)) {
        Ok(Some(args)) => args,
        Ok(None) => {
            println!("{USAGE}");
            return;
        }
        Err(error) => {
            eprintln!("{error}\n\n{USAGE}");
            std::process::exit(2);
        }
    };
    match run(args) {
        Ok(result) => println!(
            "{}",
            serde_json::to_string_pretty(&result).expect("materialization result is JSON")
        ),
        Err(error) => {
            eprintln!("candidate materialization failed: {error}");
            std::process::exit(1);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_args_requires_all_explicit_inputs() {
        let error = parse_args(["--archive".to_string(), "runtime.tar.gz".to_string()])
            .expect_err("missing manifest must fail");
        assert!(error.contains("--manifest-entry is required"));
    }

    #[test]
    fn parse_args_rejects_unknown_or_duplicate_flags() {
        let unknown = parse_args(["--download".to_string(), "yes".to_string()])
            .expect_err("unknown flag must fail");
        assert!(unknown.contains("unknown argument"));

        let duplicate = parse_args([
            "--archive".to_string(),
            "one.tar.gz".to_string(),
            "--archive".to_string(),
            "two.tar.gz".to_string(),
        ])
        .expect_err("duplicate flag must fail");
        assert!(duplicate.contains("duplicate argument"));
    }
}
