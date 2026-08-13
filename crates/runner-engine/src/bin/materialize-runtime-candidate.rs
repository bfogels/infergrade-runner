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
  --runtime-cache-dir <new-or-empty-dir> --consent-archive-sha256 <sha256> \\
  [--receipt-output <path-free-receipt.json>]";

#[derive(Debug, PartialEq)]
struct Args {
    manifest_entry: PathBuf,
    archive: PathBuf,
    runtime_cache_dir: PathBuf,
    consent_archive_sha256: String,
    receipt_output: Option<PathBuf>,
}

fn parse_args(values: impl IntoIterator<Item = String>) -> Result<Option<Args>, String> {
    let mut values = values.into_iter();
    let mut manifest_entry = None;
    let mut archive = None;
    let mut runtime_cache_dir = None;
    let mut consent_archive_sha256 = None;
    let mut receipt_output = None;

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
            "--receipt-output" => &mut receipt_output,
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
        receipt_output: receipt_output.map(PathBuf::from),
    }))
}

fn path_free_receipt(result: &Value) -> Result<Value, String> {
    let selection = result
        .get("selection")
        .ok_or_else(|| "materialization result is missing selection".to_string())?;
    Ok(serde_json::json!({
        "receipt_version": "infergrade_runtime_candidate_materialization_v1",
        "candidate_only": true,
        "claim_boundary": "Immutable package identity and version smoke only; no model compatibility, signed catalog assertion, support promotion, or publication is implied.",
        "runtime": {
            "runtime_id": selection.get("runtime_id"),
            "channel": selection.get("channel"),
            "source": selection.get("source"),
            "upstream": selection.get("upstream"),
            "selected_at_platform": selection.get("selected_at_platform"),
            "runtime_build_id": selection.pointer("/runtime_build/runtime_build_id"),
            "source_assertion_id": selection.pointer("/runtime_build/source_assertion_id"),
            "content_scope": selection.pointer("/runtime_build/content_scope"),
            "file_count": selection.pointer("/runtime_build/file_count"),
        },
        "archive": selection.get("archive"),
        "catalog_assertion": selection.get("catalog_assertion"),
        "version_smoke": selection.get("version_smoke"),
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
    let receipt_output = args.receipt_output.clone();
    match run(args) {
        Ok(result) => {
            if let Some(path) = receipt_output {
                let receipt = path_free_receipt(&result).unwrap_or_else(|error| {
                    eprintln!("candidate receipt failed: {error}");
                    std::process::exit(1);
                });
                if let Some(parent) = path
                    .parent()
                    .filter(|parent| !parent.as_os_str().is_empty())
                {
                    fs::create_dir_all(parent).unwrap_or_else(|error| {
                        eprintln!("candidate receipt directory failed: {error}");
                        std::process::exit(1);
                    });
                }
                fs::write(
                    &path,
                    format!(
                        "{}\n",
                        serde_json::to_string_pretty(&receipt).expect("candidate receipt is JSON")
                    ),
                )
                .unwrap_or_else(|error| {
                    eprintln!("candidate receipt write failed: {error}");
                    std::process::exit(1);
                });
            }
            println!(
                "{}",
                serde_json::to_string_pretty(&result).expect("materialization result is JSON")
            );
        }
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

    #[test]
    fn path_free_receipt_omits_local_paths() {
        let receipt = path_free_receipt(&serde_json::json!({
            "selection": {
                "runtime_id": "candidate",
                "channel": "upstream_release",
                "source": "managed_download",
                "binaries": {"cli": "/private/runtime/llama-cli"},
                "runtime_build": {
                    "runtime_build_id": "a".repeat(64),
                    "source_assertion_id": "b".repeat(64),
                    "content_scope": "managed_package",
                    "file_count": 4,
                    "manifest_path": "/private/manifest.json"
                },
                "archive": {"sha256": "c".repeat(64)},
                "catalog_assertion": null,
                "version_smoke": {"status": "passed"}
            }
        }))
        .expect("path-free receipt");
        let text = serde_json::to_string(&receipt).expect("receipt JSON");
        assert!(!text.contains("/private/"));
        assert!(!text.contains("binaries"));
        assert_eq!(receipt["candidate_only"], true);
    }
}
