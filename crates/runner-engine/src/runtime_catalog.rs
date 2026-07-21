//! Rollback-protected, role-separated metadata for downloadable runtimes.
//!
//! This is deliberately smaller than a general TUF client: InferGrade accepts
//! one pinned root and the root/timestamp/snapshot/targets roles it authorizes.
//! It implements the security properties the runtime resolver needs: threshold
//! Ed25519 signatures, expiry, rollback/freeze protection, exact metadata and
//! target length/digests, revocation, platform bounds, and publisher namespaces.

use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;
use url::Url;

pub const RUNTIME_CATALOG_SPEC_VERSION: &str = "infergrade_runtime_catalog_v1";
type RuntimeCatalogGenerationBytes = (Vec<u8>, Vec<u8>, Vec<u8>, Vec<u8>);

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct CatalogVersions {
    pub root: u64,
    pub timestamp: u64,
    pub snapshot: u64,
    pub targets: u64,
}

#[derive(Debug, Clone)]
pub struct RuntimeCatalogFiles<'a> {
    pub root: &'a [u8],
    pub timestamp: &'a [u8],
    pub snapshot: &'a [u8],
    pub targets: &'a [u8],
}

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeCatalog {
    pub(crate) versions: CatalogVersions,
    pub(crate) expires_unix: u64,
    pub(crate) signing_environment: String,
    pub(crate) targets_sha256: String,
    pub(crate) targets: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, Serialize)]
pub struct RuntimeCatalogActivation {
    pub catalog: RuntimeCatalog,
    pub generation_dir: PathBuf,
    pub source: &'static str,
}

impl RuntimeCatalog {
    pub fn install_target(
        &self,
        name: &str,
        system: &str,
        arch: &str,
        explicit_consent_build_id: &str,
    ) -> Result<&Value, String> {
        let target = self
            .targets
            .get(name)
            .ok_or_else(|| format!("runtime catalog target `{name}` was not found"))?;
        let custom = target
            .get("custom")
            .and_then(Value::as_object)
            .ok_or_else(|| "runtime catalog target is missing custom metadata".to_string())?;
        if custom.get("revoked").and_then(Value::as_bool) == Some(true)
            || custom.get("maturity").and_then(Value::as_str) == Some("revoked")
        {
            return Err(format!("runtime catalog target `{name}` is revoked"));
        }
        let target_system = required_string(custom, "system")?;
        let target_arch = required_string(custom, "arch")?;
        if target_system != system || target_arch != arch {
            return Err(format!(
                "runtime catalog target `{name}` is for {target_system}/{target_arch}, not {system}/{arch}"
            ));
        }
        let build_id = required_digest(custom, "runtime_build_id")?;
        if explicit_consent_build_id != build_id {
            return Err(format!(
                "explicit consent for runtime build {build_id} is required before download"
            ));
        }
        Ok(target)
    }
}

pub fn verify_runtime_catalog(
    files: RuntimeCatalogFiles<'_>,
    trusted_root: Option<&[u8]>,
    previous: Option<&CatalogVersions>,
    now_unix: u64,
) -> Result<RuntimeCatalog, String> {
    let root: Value = parse_bounded_json("root", files.root, 256 * 1024)?;
    if let Some(pinned) = trusted_root {
        let pinned_value: Value = parse_bounded_json("pinned root", pinned, 256 * 1024)?;
        let pinned_version = metadata_version(&pinned_value, "root")?;
        let root_version = metadata_version(&root, "root")?;
        if root_version < pinned_version {
            return Err("runtime catalog root rollback detected".to_string());
        }
        verify_role(&pinned_value, "root", &root)?;
        if root_version > pinned_version {
            if root_version != pinned_version.saturating_add(1) {
                return Err(
                    "runtime catalog root rotations must be applied one version at a time"
                        .to_string(),
                );
            }
            verify_role(&root, "root", &root)?;
        }
    } else {
        verify_role(&root, "root", &root)?;
    }
    verify_not_expired(&root, now_unix)?;

    let timestamp: Value = parse_bounded_json("timestamp", files.timestamp, 256 * 1024)?;
    let snapshot: Value = parse_bounded_json("snapshot", files.snapshot, 512 * 1024)?;
    let targets: Value = parse_bounded_json("targets", files.targets, 2 * 1024 * 1024)?;
    verify_role(&root, "timestamp", &timestamp)?;
    verify_role(&root, "snapshot", &snapshot)?;
    verify_role(&root, "targets", &targets)?;
    for metadata in [&timestamp, &snapshot, &targets] {
        verify_not_expired(metadata, now_unix)?;
    }

    verify_meta_reference(&timestamp, "snapshot.json", files.snapshot, &snapshot)?;
    verify_meta_reference(&snapshot, "targets.json", files.targets, &targets)?;

    let versions = CatalogVersions {
        root: metadata_version(&root, "root")?,
        timestamp: metadata_version(&timestamp, "timestamp")?,
        snapshot: metadata_version(&snapshot, "snapshot")?,
        targets: metadata_version(&targets, "targets")?,
    };
    if let Some(previous) = previous {
        for (role, current, old) in [
            ("root", versions.root, previous.root),
            ("timestamp", versions.timestamp, previous.timestamp),
            ("snapshot", versions.snapshot, previous.snapshot),
            ("targets", versions.targets, previous.targets),
        ] {
            if current < old {
                return Err(format!("runtime catalog {role} rollback detected"));
            }
        }
    }

    let target_map = targets
        .pointer("/signed/targets")
        .and_then(Value::as_object)
        .ok_or_else(|| "targets metadata is missing signed.targets".to_string())?;
    let signing_environment = targets
        .pointer("/signed/signing_environment")
        .and_then(Value::as_str)
        .filter(|value| matches!(*value, "review_candidate" | "production"))
        .ok_or_else(|| "targets metadata has an invalid signing_environment".to_string())?;
    let publisher_policies = root
        .pointer("/signed/publisher_policies")
        .and_then(Value::as_object)
        .ok_or_else(|| "root metadata is missing publisher_policies".to_string())?;
    let mut verified_targets = BTreeMap::new();
    for (name, target) in target_map {
        verify_target(name, target, publisher_policies)?;
        verified_targets.insert(name.clone(), target.clone());
    }
    Ok(RuntimeCatalog {
        versions,
        expires_unix: metadata_expiry(&targets)?,
        signing_environment: signing_environment.to_string(),
        targets_sha256: sha256_hex(files.targets),
        targets: verified_targets,
    })
}

/// Verify a complete metadata generation before atomically making it active.
/// A failed refresh cannot disturb the previous last-known-good generation.
pub fn activate_runtime_catalog(
    cache_root: &Path,
    files: RuntimeCatalogFiles<'_>,
    pinned_root: &[u8],
    now_unix: u64,
) -> Result<RuntimeCatalogActivation, String> {
    let previous = load_active_versions(cache_root)?;
    let metadata_hashes = BTreeMap::from([
        ("root", sha256_hex(files.root)),
        ("timestamp", sha256_hex(files.timestamp)),
        ("snapshot", sha256_hex(files.snapshot)),
        ("targets", sha256_hex(files.targets)),
    ]);
    let catalog = verify_runtime_catalog(
        files.clone(),
        Some(pinned_root),
        previous.as_ref(),
        now_unix,
    )?;
    if let (Some(previous), Some(previous_hashes)) =
        (previous.as_ref(), load_active_metadata_hashes(cache_root)?)
    {
        for (role, current_version, previous_version) in [
            ("root", catalog.versions.root, previous.root),
            ("timestamp", catalog.versions.timestamp, previous.timestamp),
            ("snapshot", catalog.versions.snapshot, previous.snapshot),
            ("targets", catalog.versions.targets, previous.targets),
        ] {
            if current_version == previous_version
                && previous_hashes.contains_key(role)
                && metadata_hashes.get(role) != previous_hashes.get(role)
            {
                return Err(format!(
                    "runtime catalog {role} changed without a version increment"
                ));
            }
        }
    }
    let generation_digest = sha256_hex(
        [files.root, files.timestamp, files.snapshot, files.targets]
            .concat()
            .as_slice(),
    );
    let generation_name = format!(
        "{}-{}",
        catalog.versions.timestamp,
        &generation_digest[..16]
    );
    let generations = cache_root.join("generations");
    let generation = generations.join(&generation_name);
    fs::create_dir_all(&generations)
        .map_err(|error| format!("could not create runtime catalog cache: {error}"))?;
    if !generation.exists() {
        let staging =
            generations.join(format!(".staging-{generation_name}-{}", std::process::id()));
        if staging.exists() {
            fs::remove_dir_all(&staging)
                .map_err(|error| format!("could not clear runtime catalog staging: {error}"))?;
        }
        fs::create_dir(&staging)
            .map_err(|error| format!("could not create runtime catalog staging: {error}"))?;
        for (name, bytes) in [
            ("root.json", files.root),
            ("timestamp.json", files.timestamp),
            ("snapshot.json", files.snapshot),
            ("targets.json", files.targets),
        ] {
            fs::write(staging.join(name), bytes)
                .map_err(|error| format!("could not cache runtime catalog {name}: {error}"))?;
        }
        fs::write(
            staging.join("versions.json"),
            serde_json::to_vec_pretty(&catalog.versions)
                .map_err(|error| format!("could not serialize catalog versions: {error}"))?,
        )
        .map_err(|error| format!("could not cache runtime catalog versions: {error}"))?;
        fs::rename(&staging, &generation)
            .map_err(|error| format!("could not activate runtime catalog generation: {error}"))?;
    }
    fs::create_dir_all(cache_root)
        .map_err(|error| format!("could not create runtime catalog cache root: {error}"))?;
    let pointer = cache_root.join("active.json");
    let temporary = cache_root.join(format!("active.json.tmp-{}", std::process::id()));
    fs::write(
        &temporary,
        serde_json::to_vec_pretty(&serde_json::json!({
            "generation": generation_name,
            "versions": catalog.versions,
            "targets_sha256": catalog.targets_sha256,
            "metadata_sha256": metadata_hashes,
        }))
        .map_err(|error| format!("could not serialize runtime catalog pointer: {error}"))?,
    )
    .map_err(|error| format!("could not write runtime catalog pointer: {error}"))?;
    fs::rename(&temporary, &pointer)
        .map_err(|error| format!("could not activate runtime catalog pointer: {error}"))?;
    Ok(RuntimeCatalogActivation {
        catalog,
        generation_dir: generation,
        source: "verified_refresh",
    })
}

/// Load the last-known-good generation. Expired metadata remains on disk so
/// already-installed immutable builds and active locks keep working, but this
/// function refuses it for a new install or selection decision.
pub fn load_active_runtime_catalog(
    cache_root: &Path,
    pinned_root: &[u8],
    now_unix: u64,
) -> Result<RuntimeCatalogActivation, String> {
    let pointer: Value = serde_json::from_slice(
        &fs::read(cache_root.join("active.json"))
            .map_err(|_| "no last-known-good runtime catalog is cached".to_string())?,
    )
    .map_err(|error| format!("runtime catalog cache pointer is invalid: {error}"))?;
    let generation_name = pointer
        .get("generation")
        .and_then(Value::as_str)
        .filter(|name| !name.contains('/') && !name.contains(".."))
        .ok_or_else(|| "runtime catalog cache pointer is unsafe".to_string())?;
    let generation = cache_root.join("generations").join(generation_name);
    let root = read_bounded_file(&generation.join("root.json"), 256 * 1024)?;
    let timestamp = read_bounded_file(&generation.join("timestamp.json"), 256 * 1024)?;
    let snapshot = read_bounded_file(&generation.join("snapshot.json"), 512 * 1024)?;
    let targets = read_bounded_file(&generation.join("targets.json"), 2 * 1024 * 1024)?;
    let previous = load_active_versions(cache_root)?;
    let catalog = verify_runtime_catalog(
        RuntimeCatalogFiles { root: &root, timestamp: &timestamp, snapshot: &snapshot, targets: &targets },
        Some(pinned_root),
        previous.as_ref(),
        now_unix,
    )
    .map_err(|error| format!("cached runtime catalog is unavailable for new decisions: {error}. Installed immutable runtimes remain usable offline"))?;
    Ok(RuntimeCatalogActivation {
        catalog,
        generation_dir: generation,
        source: "last_known_good",
    })
}

/// Refresh all role metadata over HTTPS. Network or server failure falls back
/// to an unexpired verified cache; cryptographic failure never activates new
/// bytes and is reported even when an old generation remains usable.
pub fn refresh_runtime_catalog_from_url(
    base_url: &str,
    cache_root: &Path,
    pinned_root: &[u8],
    now_unix: u64,
) -> Result<RuntimeCatalogActivation, String> {
    let parsed = Url::parse(base_url)
        .map_err(|_| "runtime catalog URL must be a valid HTTPS URL".to_string())?;
    if parsed.scheme() != "https" {
        return Err("runtime catalog URL must use HTTPS".to_string());
    }
    let client = reqwest::blocking::Client::builder()
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|error| format!("could not initialize runtime catalog client: {error}"))?;
    let fetch = || -> Result<RuntimeCatalogGenerationBytes, String> {
        Ok((
            fetch_metadata(&client, &parsed, "root.json", 256 * 1024)?,
            fetch_metadata(&client, &parsed, "timestamp.json", 256 * 1024)?,
            fetch_metadata(&client, &parsed, "snapshot.json", 512 * 1024)?,
            fetch_metadata(&client, &parsed, "targets.json", 2 * 1024 * 1024)?,
        ))
    };
    match fetch() {
        Ok((root, timestamp, snapshot, targets)) => activate_runtime_catalog(
            cache_root,
            RuntimeCatalogFiles {
                root: &root,
                timestamp: &timestamp,
                snapshot: &snapshot,
                targets: &targets,
            },
            pinned_root,
            now_unix,
        ),
        Err(network_error) => load_active_runtime_catalog(cache_root, pinned_root, now_unix)
            .map_err(|cache_error| {
                format!(
                    "runtime catalog refresh failed ({network_error}); cache fallback failed ({cache_error})"
                )
            }),
    }
}

fn fetch_metadata(
    client: &reqwest::blocking::Client,
    base: &Url,
    name: &str,
    max: usize,
) -> Result<Vec<u8>, String> {
    let url = base
        .join(name)
        .map_err(|_| format!("could not resolve runtime catalog {name} URL"))?;
    if url.scheme() != "https" || url.host_str() != base.host_str() {
        return Err("runtime catalog metadata cannot cross origin".to_string());
    }
    let mut response = client
        .get(url)
        .send()
        .map_err(|error| format!("could not download runtime catalog {name}: {error}"))?;
    if !response.status().is_success() {
        return Err(format!(
            "runtime catalog {name} download failed with HTTP {}",
            response.status()
        ));
    }
    if response
        .content_length()
        .is_some_and(|length| length == 0 || length > max as u64)
    {
        return Err(format!("runtime catalog {name} exceeds its size bound"));
    }
    let mut bytes = Vec::new();
    let mut buffer = [0_u8; 32 * 1024];
    use std::io::Read;
    loop {
        let count = response
            .read(&mut buffer)
            .map_err(|error| format!("could not read runtime catalog {name}: {error}"))?;
        if count == 0 {
            break;
        }
        if bytes.len().saturating_add(count) > max {
            return Err(format!("runtime catalog {name} exceeds its size bound"));
        }
        bytes.extend_from_slice(&buffer[..count]);
    }
    if bytes.is_empty() {
        return Err(format!("runtime catalog {name} is empty"));
    }
    Ok(bytes)
}

fn load_active_versions(cache_root: &Path) -> Result<Option<CatalogVersions>, String> {
    let pointer_path = cache_root.join("active.json");
    let bytes = match fs::read(&pointer_path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("could not read runtime catalog pointer: {error}")),
    };
    let pointer: Value = serde_json::from_slice(&bytes)
        .map_err(|error| format!("runtime catalog pointer is invalid: {error}"))?;
    serde_json::from_value(pointer.get("versions").cloned().unwrap_or(Value::Null))
        .map(Some)
        .map_err(|error| format!("runtime catalog versions are invalid: {error}"))
}

fn load_active_metadata_hashes(
    cache_root: &Path,
) -> Result<Option<BTreeMap<String, String>>, String> {
    let bytes = match fs::read(cache_root.join("active.json")) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(format!("could not read runtime catalog pointer: {error}")),
    };
    let pointer: Value = serde_json::from_slice(&bytes)
        .map_err(|error| format!("runtime catalog pointer is invalid: {error}"))?;
    let Some(hashes) = pointer.get("metadata_sha256") else {
        return Ok(pointer
            .get("targets_sha256")
            .and_then(Value::as_str)
            .map(|digest| BTreeMap::from([("targets".to_string(), digest.to_string())])));
    };
    serde_json::from_value(hashes.clone())
        .map(Some)
        .map_err(|error| format!("runtime catalog metadata digests are invalid: {error}"))
}

fn read_bounded_file(path: &Path, max: usize) -> Result<Vec<u8>, String> {
    let metadata = fs::metadata(path)
        .map_err(|error| format!("could not inspect cached runtime catalog metadata: {error}"))?;
    if metadata.len() == 0 || metadata.len() > max as u64 {
        return Err("cached runtime catalog metadata exceeds its size bound".to_string());
    }
    fs::read(path)
        .map_err(|error| format!("could not read cached runtime catalog metadata: {error}"))
}

fn parse_bounded_json(label: &str, bytes: &[u8], max: usize) -> Result<Value, String> {
    if bytes.is_empty() || bytes.len() > max {
        return Err(format!(
            "runtime catalog {label} metadata exceeds its size bound"
        ));
    }
    serde_json::from_slice(bytes)
        .map_err(|error| format!("runtime catalog {label} metadata is invalid JSON: {error}"))
}

fn signed_bytes(envelope: &Value) -> Result<Vec<u8>, String> {
    let signed = envelope
        .get("signed")
        .ok_or_else(|| "runtime catalog metadata is missing signed".to_string())?;
    let canonical = canonical_json(signed);
    serde_json::to_vec(&canonical)
        .map_err(|error| format!("could not canonicalize runtime catalog metadata: {error}"))
}

fn canonical_json(value: &Value) -> Value {
    match value {
        Value::Object(object) => {
            let mut sorted = BTreeMap::new();
            for (key, value) in object {
                sorted.insert(key, canonical_json(value));
            }
            let mut result = Map::new();
            for (key, value) in sorted {
                result.insert(key.clone(), value);
            }
            Value::Object(result)
        }
        Value::Array(items) => Value::Array(items.iter().map(canonical_json).collect()),
        _ => value.clone(),
    }
}

fn verify_role(root: &Value, role: &str, envelope: &Value) -> Result<(), String> {
    let signed_type = envelope
        .pointer("/signed/_type")
        .and_then(Value::as_str)
        .unwrap_or("");
    if signed_type != role {
        return Err(format!(
            "runtime catalog expected {role} metadata, got `{signed_type}`"
        ));
    }
    if envelope
        .pointer("/signed/spec_version")
        .and_then(Value::as_str)
        != Some(RUNTIME_CATALOG_SPEC_VERSION)
    {
        return Err(format!(
            "runtime catalog {role} uses an unsupported spec version"
        ));
    }
    let role_policy = root
        .pointer(&format!("/signed/roles/{role}"))
        .and_then(Value::as_object)
        .ok_or_else(|| format!("root metadata does not authorize the {role} role"))?;
    let threshold = role_policy
        .get("threshold")
        .and_then(Value::as_u64)
        .filter(|value| *value > 0)
        .ok_or_else(|| format!("root metadata has an invalid {role} threshold"))?;
    let allowed: BTreeSet<&str> = role_policy
        .get("keyids")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("root metadata has no {role} keys"))?
        .iter()
        .filter_map(Value::as_str)
        .collect();
    let signatures = envelope
        .get("signatures")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("runtime catalog {role} metadata has no signatures"))?;
    let message = signed_bytes(envelope)?;
    let mut valid = BTreeSet::new();
    for signature in signatures {
        let keyid = signature.get("keyid").and_then(Value::as_str).unwrap_or("");
        if !allowed.contains(keyid) || valid.contains(keyid) {
            continue;
        }
        let public = root
            .pointer(&format!("/signed/keys/{keyid}/public_key_hex"))
            .and_then(Value::as_str)
            .ok_or_else(|| format!("root metadata is missing public key `{keyid}`"))?;
        let public: [u8; 32] = decode_hex(public)?
            .try_into()
            .map_err(|_| format!("runtime catalog key `{keyid}` is not 32 bytes"))?;
        let verifying_key = VerifyingKey::from_bytes(&public)
            .map_err(|_| format!("runtime catalog key `{keyid}` is invalid"))?;
        let signature_bytes: [u8; 64] = decode_hex(
            signature
                .get("sig_hex")
                .and_then(Value::as_str)
                .unwrap_or(""),
        )?
        .try_into()
        .map_err(|_| "runtime catalog signature is not 64 bytes".to_string())?;
        let signature = Signature::from_bytes(&signature_bytes);
        if verifying_key.verify(&message, &signature).is_ok() {
            valid.insert(keyid);
        }
    }
    if valid.len() < threshold as usize {
        return Err(format!(
            "runtime catalog {role} signature threshold was not met"
        ));
    }
    Ok(())
}

fn verify_meta_reference(
    envelope: &Value,
    name: &str,
    referenced_bytes: &[u8],
    referenced: &Value,
) -> Result<(), String> {
    let metadata = envelope
        .pointer(&format!("/signed/meta/{name}"))
        .and_then(Value::as_object)
        .ok_or_else(|| format!("runtime catalog metadata is missing {name} reference"))?;
    let expected_length = metadata
        .get("length")
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("runtime catalog {name} reference is missing length"))?;
    if expected_length != referenced_bytes.len() as u64 {
        return Err(format!("runtime catalog {name} length mismatch"));
    }
    let expected_sha = required_digest(metadata, "sha256")?;
    if expected_sha != sha256_hex(referenced_bytes) {
        return Err(format!("runtime catalog {name} digest mismatch"));
    }
    let expected_version = metadata
        .get("version")
        .and_then(Value::as_u64)
        .ok_or_else(|| format!("runtime catalog {name} reference is missing version"))?;
    if expected_version
        != metadata_version(
            referenced,
            referenced
                .pointer("/signed/_type")
                .and_then(Value::as_str)
                .unwrap_or(""),
        )?
    {
        return Err(format!("runtime catalog {name} version mismatch"));
    }
    Ok(())
}

fn verify_target(
    name: &str,
    target: &Value,
    publisher_policies: &Map<String, Value>,
) -> Result<(), String> {
    if name.starts_with('/') || name.contains("..") || name.contains('\\') {
        return Err(format!("runtime catalog target name `{name}` is unsafe"));
    }
    let length = target.get("length").and_then(Value::as_u64).unwrap_or(0);
    if length == 0 || length > 256 * 1024 * 1024 {
        return Err(format!(
            "runtime catalog target `{name}` has an invalid length"
        ));
    }
    required_digest(
        target
            .as_object()
            .ok_or_else(|| "runtime target must be an object".to_string())?,
        "sha256",
    )?;
    let custom = target
        .get("custom")
        .and_then(Value::as_object)
        .ok_or_else(|| format!("runtime catalog target `{name}` is missing custom metadata"))?;
    for field in [
        "runtime_build_id",
        "build_manifest_files_sha256",
        "content_manifest_sha256",
        "rollback_runtime_build_id",
    ] {
        required_digest(custom, field)?;
    }
    for field in [
        "runtime_id",
        "runtime_family",
        "runtime_interface",
        "rollback_runtime_id",
        "archive_url",
        "system",
        "arch",
        "origin",
        "maturity",
        "support_tier",
        "compatibility_status",
        "provenance_strength",
        "publisher",
    ] {
        required_string(custom, field)?;
    }
    let archive_url = Url::parse(required_string(custom, "archive_url")?)
        .map_err(|_| format!("runtime catalog target `{name}` has an invalid archive URL"))?;
    if archive_url.scheme() != "https"
        || archive_url.host_str().is_none()
        || !archive_url.username().is_empty()
        || archive_url.password().is_some()
    {
        return Err(format!(
            "runtime catalog target `{name}` archive URL must be credential-free HTTPS"
        ));
    }
    let expected_binaries = custom
        .get("expected_binaries")
        .and_then(Value::as_array)
        .filter(|values| !values.is_empty() && values.len() <= 16)
        .ok_or_else(|| format!("runtime catalog target `{name}` has invalid expected binaries"))?;
    for binary in expected_binaries {
        let binary = binary.as_str().unwrap_or("");
        if binary.is_empty() || binary.len() > 128 || binary.contains('/') || binary.contains('\\')
        {
            return Err(format!(
                "runtime catalog target `{name}` has an unsafe expected binary"
            ));
        }
    }
    let binary_names = custom
        .get("binary_names")
        .and_then(Value::as_object)
        .ok_or_else(|| format!("runtime catalog target `{name}` has no binary_names"))?;
    for role in ["cli", "server"] {
        let binary = required_string(binary_names, role)?;
        if binary.len() > 128 || binary.contains('/') || binary.contains('\\') {
            return Err(format!(
                "runtime catalog target `{name}` has an unsafe {role} binary name"
            ));
        }
    }
    let publisher = required_string(custom, "publisher")?;
    let policy = publisher_policies
        .get(publisher)
        .and_then(Value::as_object)
        .ok_or_else(|| {
            format!("runtime catalog target `{name}` has unauthorized publisher `{publisher}`")
        })?;
    let prefix = required_string(policy, "target_prefix")?;
    if !name.starts_with(prefix) {
        return Err(format!(
            "publisher `{publisher}` cannot publish target `{name}`"
        ));
    }
    let allowed_origins = policy
        .get("allowed_origins")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("publisher `{publisher}` has no allowed origins"))?;
    let origin = required_string(custom, "origin")?;
    if !allowed_origins
        .iter()
        .any(|value| value.as_str() == Some(origin))
    {
        return Err(format!(
            "publisher `{publisher}` cannot assert origin `{origin}`"
        ));
    }
    let assertions = custom
        .get("validation_assertions")
        .and_then(Value::as_array)
        .filter(|values| !values.is_empty())
        .ok_or_else(|| {
            format!("runtime catalog target `{name}` has no exact validation assertions")
        })?;
    for assertion in assertions {
        let assertion = assertion.as_object().ok_or_else(|| {
            format!("runtime catalog target `{name}` has a malformed validation assertion")
        })?;
        required_digest(assertion, "model_artifact_sha256")?;
        for field in [
            "assertion_id",
            "model_id",
            "model_revision",
            "quantization_label",
            "bundle_id",
            "benchmark_depth",
            "result_status",
        ] {
            required_string(assertion, field)?;
        }
        if assertion
            .get("published")
            .and_then(Value::as_bool)
            .is_none()
        {
            return Err(format!(
                "runtime catalog target `{name}` validation assertion is missing `published`"
            ));
        }
    }
    Ok(())
}

fn metadata_version(envelope: &Value, role: &str) -> Result<u64, String> {
    envelope
        .pointer("/signed/version")
        .and_then(Value::as_u64)
        .filter(|value| *value > 0)
        .ok_or_else(|| format!("runtime catalog {role} metadata has an invalid version"))
}

fn metadata_expiry(envelope: &Value) -> Result<u64, String> {
    envelope
        .pointer("/signed/expires_unix")
        .and_then(Value::as_u64)
        .filter(|value| *value > 0)
        .ok_or_else(|| "runtime catalog metadata has an invalid expiry".to_string())
}

fn verify_not_expired(envelope: &Value, now_unix: u64) -> Result<(), String> {
    let role = envelope
        .pointer("/signed/_type")
        .and_then(Value::as_str)
        .unwrap_or("unknown");
    if metadata_expiry(envelope)? <= now_unix {
        return Err(format!("runtime catalog {role} metadata is expired"));
    }
    Ok(())
}

fn required_string<'a>(object: &'a Map<String, Value>, key: &str) -> Result<&'a str, String> {
    object
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|v| !v.is_empty())
        .ok_or_else(|| format!("runtime catalog field `{key}` is required"))
}

fn required_digest(object: &Map<String, Value>, key: &str) -> Result<String, String> {
    let value = required_string(object, key)?.to_ascii_lowercase();
    if value.len() != 64 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(format!(
            "runtime catalog field `{key}` must be a SHA-256 digest"
        ));
    }
    Ok(value)
}

fn sha256_hex(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn decode_hex(value: &str) -> Result<Vec<u8>, String> {
    if value.len() & 1 == 1 || !value.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err("runtime catalog contains invalid hexadecimal data".to_string());
    }
    (0..value.len())
        .step_by(2)
        .map(|index| {
            u8::from_str_radix(&value[index..index + 2], 16)
                .map_err(|_| "runtime catalog contains invalid hexadecimal data".to_string())
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::{Signer, SigningKey};
    use serde_json::json;

    fn sign(signed: Value, keyid: &str, key: &SigningKey) -> Value {
        let unsigned = json!({"signed": signed, "signatures": []});
        let signature = key.sign(&signed_bytes(&unsigned).expect("canonical signed bytes"));
        json!({
            "signed": unsigned["signed"].clone(),
            "signatures": [{"keyid": keyid, "sig_hex": hex(&signature.to_bytes())}]
        })
    }

    fn hex(bytes: &[u8]) -> String {
        bytes.iter().map(|byte| format!("{byte:02x}")).collect()
    }

    fn fixture() -> (Vec<u8>, Vec<u8>, Vec<u8>, Vec<u8>) {
        let key = SigningKey::from_bytes(&[7_u8; 32]);
        let keyid = "catalog-key-1";
        let target = json!({
            "length": 100,
            "sha256": "11".repeat(32),
            "custom": {
                "runtime_build_id": "22".repeat(32),
                "build_manifest_files_sha256": "55".repeat(32),
                "content_manifest_sha256": "33".repeat(32),
                "rollback_runtime_build_id": "44".repeat(32),
                "runtime_id": "llama-cpp-b10069-macos-arm64-metal",
                "runtime_family": "llama.cpp",
                "runtime_interface": "llama_cpp_cli_server_v1",
                "rollback_runtime_id": "llama-cpp-stable",
                "archive_url": "https://example.test/llama-b10069.tar.gz",
                "system": "macos",
                "arch": "aarch64",
                "origin": "upstream_official",
                "maturity": "candidate",
                "support_tier": "candidate",
                "compatibility_status": "exact_artifact_validated",
                "provenance_strength": "independently_signed",
                "publisher": "infergrade",
                "expected_binaries": ["llama-cli", "llama-server"],
                "binary_names": {"cli": "llama-cli", "server": "llama-server"},
                "validation_assertions": [{
                    "assertion_id": "fixture-validation",
                    "model_id": "example/model",
                    "model_revision": "fixture-revision",
                    "model_artifact_sha256": "66".repeat(32),
                    "quantization_label": "Q4_K_M",
                    "bundle_id": "fixture-bundle",
                    "benchmark_depth": "standard",
                    "result_status": "valid",
                    "published": false
                }]
            }
        });
        let targets = sign(
            json!({
                "_type": "targets", "spec_version": RUNTIME_CATALOG_SPEC_VERSION,
                "version": 4, "expires_unix": 2_000_000_000_u64,
                "signing_environment": "review_candidate",
                "targets": {"infergrade/llama-b10069.tar.gz": target}
            }),
            keyid,
            &key,
        );
        let targets_bytes = serde_json::to_vec(&targets).unwrap();
        let snapshot = sign(
            json!({
                "_type": "snapshot", "spec_version": RUNTIME_CATALOG_SPEC_VERSION,
                "version": 3, "expires_unix": 2_000_000_000_u64,
                "meta": {"targets.json": {"version": 4, "length": targets_bytes.len(), "sha256": sha256_hex(&targets_bytes)}}
            }),
            keyid,
            &key,
        );
        let snapshot_bytes = serde_json::to_vec(&snapshot).unwrap();
        let timestamp = sign(
            json!({
                "_type": "timestamp", "spec_version": RUNTIME_CATALOG_SPEC_VERSION,
                "version": 2, "expires_unix": 2_000_000_000_u64,
                "meta": {"snapshot.json": {"version": 3, "length": snapshot_bytes.len(), "sha256": sha256_hex(&snapshot_bytes)}}
            }),
            keyid,
            &key,
        );
        let root = sign(
            json!({
                "_type": "root", "spec_version": RUNTIME_CATALOG_SPEC_VERSION,
                "version": 1, "expires_unix": 2_000_000_000_u64,
                "keys": {keyid: {"keytype": "ed25519", "public_key_hex": hex(key.verifying_key().as_bytes())}},
                "roles": {
                    "root": {"keyids": [keyid], "threshold": 1},
                    "timestamp": {"keyids": [keyid], "threshold": 1},
                    "snapshot": {"keyids": [keyid], "threshold": 1},
                    "targets": {"keyids": [keyid], "threshold": 1}
                },
                "publisher_policies": {"infergrade": {"target_prefix": "infergrade/", "allowed_origins": ["upstream_official"]}}
            }),
            keyid,
            &key,
        );
        (
            serde_json::to_vec(&root).unwrap(),
            serde_json::to_vec(&timestamp).unwrap(),
            snapshot_bytes,
            targets_bytes,
        )
    }

    #[test]
    fn verifies_role_chain_and_install_consent() {
        let (root, timestamp, snapshot, targets) = fixture();
        let catalog = verify_runtime_catalog(
            RuntimeCatalogFiles {
                root: &root,
                timestamp: &timestamp,
                snapshot: &snapshot,
                targets: &targets,
            },
            Some(&root),
            None,
            1_900_000_000,
        )
        .unwrap();
        assert_eq!(catalog.versions.targets, 4);
        assert!(catalog
            .install_target(
                "infergrade/llama-b10069.tar.gz",
                "macos",
                "aarch64",
                &"22".repeat(32)
            )
            .is_ok());
        assert!(catalog
            .install_target(
                "infergrade/llama-b10069.tar.gz",
                "macos",
                "aarch64",
                "wrong"
            )
            .unwrap_err()
            .contains("explicit consent"));
    }

    #[test]
    fn rejects_tamper_expiry_rollback_and_wrong_platform() {
        let (root, timestamp, snapshot, mut targets) = fixture();
        targets.push(b' ');
        assert!(verify_runtime_catalog(
            RuntimeCatalogFiles {
                root: &root,
                timestamp: &timestamp,
                snapshot: &snapshot,
                targets: &targets
            },
            Some(&root),
            None,
            1_900_000_000
        )
        .unwrap_err()
        .contains("length mismatch"));
        let (root, timestamp, snapshot, targets) = fixture();
        assert!(verify_runtime_catalog(
            RuntimeCatalogFiles {
                root: &root,
                timestamp: &timestamp,
                snapshot: &snapshot,
                targets: &targets
            },
            Some(&root),
            None,
            2_100_000_000
        )
        .unwrap_err()
        .contains("expired"));
        let previous = CatalogVersions {
            root: 1,
            timestamp: 9,
            snapshot: 3,
            targets: 4,
        };
        assert!(verify_runtime_catalog(
            RuntimeCatalogFiles {
                root: &root,
                timestamp: &timestamp,
                snapshot: &snapshot,
                targets: &targets
            },
            Some(&root),
            Some(&previous),
            1_900_000_000
        )
        .unwrap_err()
        .contains("rollback"));
        let catalog = verify_runtime_catalog(
            RuntimeCatalogFiles {
                root: &root,
                timestamp: &timestamp,
                snapshot: &snapshot,
                targets: &targets,
            },
            Some(&root),
            None,
            1_900_000_000,
        )
        .unwrap();
        assert!(catalog
            .install_target(
                "infergrade/llama-b10069.tar.gz",
                "linux",
                "x86_64",
                &"22".repeat(32)
            )
            .unwrap_err()
            .contains("not linux/x86_64"));
    }

    #[test]
    fn activation_is_atomic_and_cached_catalog_fails_closed_after_expiry() {
        let (root, timestamp, snapshot, targets) = fixture();
        let cache = std::env::temp_dir().join(format!(
            "infergrade-runtime-catalog-cache-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&cache);
        let activated = activate_runtime_catalog(
            &cache,
            RuntimeCatalogFiles {
                root: &root,
                timestamp: &timestamp,
                snapshot: &snapshot,
                targets: &targets,
            },
            &root,
            1_900_000_000,
        )
        .unwrap();
        assert_eq!(activated.source, "verified_refresh");
        let cached = load_active_runtime_catalog(&cache, &root, 1_900_000_001).unwrap();
        assert_eq!(cached.source, "last_known_good");
        let active_before = fs::read(cache.join("active.json")).unwrap();
        let mut tampered = targets.clone();
        tampered.push(b' ');
        assert!(activate_runtime_catalog(
            &cache,
            RuntimeCatalogFiles {
                root: &root,
                timestamp: &timestamp,
                snapshot: &snapshot,
                targets: &tampered
            },
            &root,
            1_900_000_002,
        )
        .is_err());
        assert_eq!(fs::read(cache.join("active.json")).unwrap(), active_before);
        assert!(load_active_runtime_catalog(&cache, &root, 2_100_000_000)
            .unwrap_err()
            .contains("Installed immutable runtimes remain usable offline"));
        let _ = fs::remove_dir_all(&cache);
    }
}
