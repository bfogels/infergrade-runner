//! Read-only local discovery. Names are hints, never artifact identity proof.
use serde_json::{json, Value};
use std::{
    collections::{HashSet, VecDeque},
    env, fs,
    io::Read,
    path::{Path, PathBuf},
    sync::Mutex,
};
static SETTINGS_LOCK: Mutex<()> = Mutex::new(());
const MAX_ENTRIES: usize = 20_000;
const MAX_FILES: usize = 500;
const MAX_FOLDERS: usize = 16;
fn settings_path() -> Result<PathBuf, String> {
    Ok(super::runner_config_dir()?.join("model-folders.json"))
}
fn load_folders(path: &Path) -> Result<Vec<String>, String> {
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return Ok(vec![]),
        Err(e) => return Err(format!("Could not read model folders: {e}")),
    };
    let value: Value = serde_json::from_str(&text)
        .map_err(|_| "Model folder settings are invalid.".to_string())?;
    let folders = value
        .as_array()
        .ok_or("Model folder settings are invalid.")?;
    if folders.len() > MAX_FOLDERS {
        return Err("Too many saved model folders.".into());
    }
    folders
        .iter()
        .map(|v| {
            v.as_str()
                .filter(|s| s.len() <= 4096)
                .map(String::from)
                .ok_or("Model folder settings are invalid.".into())
        })
        .collect()
}
fn save_folder(path: &Path, folder: &str, remove: bool) -> Result<(), String> {
    let mut folders = load_folders(path)?;
    if remove {
        let selected = fs::canonicalize(folder)
            .ok()
            .map(|p| p.to_string_lossy().into_owned())
            .unwrap_or_else(|| folder.to_string());
        folders.retain(|f| f != folder && f != &selected);
    } else {
        let canonical =
            fs::canonicalize(folder).map_err(|_| "Choose an existing model folder.".to_string())?;
        if !canonical.is_dir() || canonical.parent().is_none() {
            return Err("Choose a model folder, rather than a filesystem root.".into());
        }
        let selected = canonical.to_string_lossy().into_owned();
        if !folders.contains(&selected) {
            if folders.len() >= MAX_FOLDERS {
                return Err("Remove a folder before adding another (limit 16).".into());
            }
            folders.push(selected);
        }
    }
    let parent = path.parent().ok_or("Invalid settings path.")?;
    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    let temp = path.with_extension("json.tmp");
    let mut options = fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&temp).map_err(|e| e.to_string())?;
    use std::io::Write;
    file.write_all(
        serde_json::to_string(&folders)
            .map_err(|e| e.to_string())?
            .as_bytes(),
    )
    .map_err(|e| e.to_string())?;
    file.sync_all().map_err(|e| e.to_string())?;
    // Windows cannot replace a destination with rename. Serialized access keeps
    // this small local setting coherent; no profile or credentials are changed.
    #[cfg(windows)]
    if path.exists() {
        fs::remove_file(path).map_err(|e| e.to_string())?;
    }
    fs::rename(temp, path).map_err(|e| e.to_string())
}
fn roots(home: &Path, folders: &[String]) -> Vec<(PathBuf, &'static str)> {
    let mut result = vec![
        (home.join(".lmstudio/models"), "LM Studio"),
        (home.join(".cache/lm-studio/models"), "LM Studio"),
        (home.join(".cache/huggingface/hub"), "Hugging Face cache"),
        (home.join(".ollama/models/blobs"), "Ollama"),
    ];
    if let Some(cache) = env::var_os("HF_HUB_CACHE") {
        result.push((PathBuf::from(cache), "Hugging Face cache"));
    }
    if let Some(cache) = env::var_os("HF_HOME") {
        result.push((PathBuf::from(cache).join("hub"), "Hugging Face cache"));
    }
    if let Some(cache) = env::var_os("OLLAMA_MODELS") {
        result.push((PathBuf::from(cache).join("blobs"), "Ollama"));
    }
    result.extend(folders.iter().map(|f| (PathBuf::from(f), "Your folder")));
    result
}
fn scan(roots: &[(PathBuf, &str)]) -> Value {
    let mut rows = vec![];
    let mut seen_files = HashSet::new();
    let mut seen_dirs = HashSet::new();
    let mut visited = 0;
    let mut incomplete = false;
    let mut inaccessible = 0;
    'roots: for (root, source) in roots {
        if !root.exists() {
            continue;
        }
        let Ok(root) = fs::canonicalize(root) else {
            inaccessible += 1;
            continue;
        };
        let mut queue = VecDeque::from([(root.clone(), 0usize)]);
        while let Some((dir, depth)) = queue.pop_front() {
            if !seen_dirs.insert(dir.clone()) {
                continue;
            }
            let entries = match fs::read_dir(&dir) {
                Ok(v) => v,
                Err(_) => {
                    inaccessible += 1;
                    continue;
                }
            };
            for entry in entries {
                visited += 1;
                if visited > MAX_ENTRIES || rows.len() >= MAX_FILES {
                    incomplete = true;
                    break 'roots;
                }
                let entry = match entry {
                    Ok(e) => e,
                    Err(_) => {
                        inaccessible += 1;
                        continue;
                    }
                };
                let path = entry.path();
                let Ok(kind) = entry.file_type() else {
                    inaccessible += 1;
                    continue;
                };
                if kind.is_dir() {
                    if depth < 8 {
                        queue.push_back((path, depth + 1));
                    } else {
                        incomplete = true;
                    }
                    continue;
                }
                // HF snapshot symlinks are allowed only within the same selected
                // root. Directory symlinks are never traversed.
                let Ok(canonical) = fs::canonicalize(&path) else {
                    continue;
                };
                if !canonical.starts_with(&root)
                    || !canonical.is_file()
                    || !seen_files.insert(canonical.clone())
                {
                    continue;
                }
                let mut header = [0u8; 4];
                let Ok(mut file) = fs::File::open(&canonical) else {
                    inaccessible += 1;
                    continue;
                };
                if file.read_exact(&mut header).is_err() || &header != b"GGUF" {
                    continue;
                }
                let Ok(metadata) = file.metadata() else {
                    continue;
                };
                rows.push(json!({"name":path.file_name().unwrap_or_default().to_string_lossy(),"path":canonical.to_string_lossy(),"source":source,"size_bytes":metadata.len(),"identity_status":"unverified","read_only":true}));
            }
        }
    }
    rows.sort_by(|a, b| a["name"].as_str().cmp(&b["name"].as_str()));
    json!({"files":rows,"scan_complete":!incomplete && inaccessible==0,"scan_limit_reached":incomplete,"unreadable_locations":inaccessible,"visited_entries":visited.min(MAX_ENTRIES),"identity_notice":"GGUF header detected. Publisher, quantization, compatibility and exact artifact identity are unverified."})
}
pub fn validate_local_gguf(path: &str) -> Result<(), String> {
    let mut file = fs::File::open(path)
        .map_err(|_| "The selected local model is no longer readable.".to_string())?;
    if !file
        .metadata()
        .map_err(|_| "Could not inspect the selected model.".to_string())?
        .is_file()
    {
        return Err("Choose a local GGUF file.".into());
    }
    let mut header = [0u8; 4];
    if file.read_exact(&mut header).is_err() || &header != b"GGUF" {
        return Err("The selected file does not have a GGUF header. Refresh local files and select a model again.".into());
    }
    Ok(())
}
fn status() -> Result<Value, String> {
    let folders = {
        let _guard = SETTINGS_LOCK
            .lock()
            .map_err(|_| "Model folder settings are busy.")?;
        load_folders(&settings_path()?)?
    };
    let home = env::var_os("HOME")
        .or_else(|| env::var_os("USERPROFILE"))
        .ok_or("Could not resolve home directory.")?;
    let mut value = scan(&roots(Path::new(&home), &folders));
    value["folders"] = json!(folders);
    Ok(value)
}
#[tauri::command]
pub async fn desktop_discovered_models() -> Result<Value, String> {
    tauri::async_runtime::spawn_blocking(status)
        .await
        .map_err(|_| "Model discovery stopped unexpectedly.".to_string())?
}
#[tauri::command]
pub async fn set_desktop_model_folder(folder: String, remove: bool) -> Result<Value, String> {
    if folder.len() > 4096 || !Path::new(&folder).is_absolute() {
        return Err("Choose an absolute local folder path.".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = SETTINGS_LOCK
            .lock()
            .map_err(|_| "Model folder settings are busy.")?;
        save_folder(&settings_path()?, &folder, remove)
    })
    .await
    .map_err(|_| "Could not save model folder.".to_string())??;
    desktop_discovered_models().await
}
#[cfg(test)]
mod tests {
    use super::*;
    fn root() -> PathBuf {
        let path = env::temp_dir().join(format!(
            "ig-discovery-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&path).unwrap();
        path
    }
    #[test]
    fn header_only_read_only_deduplicated_and_depth_bounded() {
        let dir = root();
        fs::write(dir.join("model.gguf"), b"GGUFprivate bytes").unwrap();
        fs::write(dir.join("pretend.gguf"), b"nope").unwrap();
        fs::write(dir.join("sha256-blob"), b"GGUFollama").unwrap();
        let result = scan(&[(dir.clone(), "Your folder"), (dir.clone(), "Duplicate")]);
        assert_eq!(result["files"].as_array().unwrap().len(), 2);
        assert_eq!(result["files"][0]["identity_status"], "unverified");
        assert_eq!(
            fs::read(dir.join("model.gguf")).unwrap(),
            b"GGUFprivate bytes"
        );
        let mut deep = dir.clone();
        for _ in 0..10 {
            deep = deep.join("nested");
            fs::create_dir_all(&deep).unwrap();
        }
        fs::write(deep.join("deep.gguf"), b"GGUF").unwrap();
        assert_eq!(scan(&[(dir.clone(), "Folder")])["scan_limit_reached"], true);
        fs::remove_dir_all(dir).unwrap();
    }
    #[cfg(unix)]
    #[test]
    fn symlinks_outside_root_and_directory_loops_are_not_scanned() {
        let dir = root();
        let outside = root();
        fs::write(outside.join("private.gguf"), b"GGUF").unwrap();
        fs::write(dir.join("real.gguf"), b"GGUF").unwrap();
        std::os::unix::fs::symlink(outside.join("private.gguf"), dir.join("escape.gguf")).unwrap();
        std::os::unix::fs::symlink(dir.join("real.gguf"), dir.join("alias.gguf")).unwrap();
        std::os::unix::fs::symlink(&dir, dir.join("loop")).unwrap();
        let rows = scan(&[(dir.clone(), "Folder")]);
        assert_eq!(rows["files"].as_array().unwrap().len(), 1);
        fs::remove_dir_all(dir).unwrap();
        fs::remove_dir_all(outside).unwrap();
    }
    #[test]
    fn custom_folders_persist_remove_without_touching_models() {
        let dir = root();
        let folder = root();
        fs::write(folder.join("keep.gguf"), b"GGUF").unwrap();
        let settings = dir.join("model-folders.json");
        save_folder(&settings, folder.to_str().unwrap(), false).unwrap();
        save_folder(&settings, folder.to_str().unwrap(), false).unwrap();
        assert_eq!(load_folders(&settings).unwrap().len(), 1);
        save_folder(&settings, folder.to_str().unwrap(), true).unwrap();
        assert!(load_folders(&settings).unwrap().is_empty());
        assert!(folder.join("keep.gguf").exists());
        let blob = folder.join("sha256-model");
        fs::write(&blob, b"GGUF").unwrap();
        assert!(validate_local_gguf(blob.to_str().unwrap()).is_ok());
        fs::write(&blob, b"changed").unwrap();
        assert!(validate_local_gguf(blob.to_str().unwrap()).is_err());
        assert!(save_folder(&settings, "/", false).is_err());
        fs::remove_dir_all(dir).unwrap();
        fs::remove_dir_all(folder).unwrap();
    }
}
