//! OS-owned login registration. Reads never create registrations.
use serde::Serialize;
use std::{
    path::{Path, PathBuf},
    sync::Mutex,
};
fn nonce() -> u128 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("Clock before epoch")
        .as_nanos()
}
const ID: &str = "com.infergrade.runner";
static OPERATION: Mutex<()> = Mutex::new(());
#[derive(Serialize)]
pub(crate) struct Status {
    schema_version: &'static str,
    available: bool,
    enabled: bool,
    warning: Option<String>,
}
fn status(enabled: bool) -> Status {
    Status {
        schema_version: "infergrade.startup.v1",
        available: true,
        enabled,
        warning: None,
    }
}
fn executable(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    if cfg!(debug_assertions) {
        return Err("Open at login is available in the installed release app.".into());
    }
    #[cfg(target_os = "linux")]
    let path = app
        .env()
        .appimage
        .clone()
        .unwrap_or(std::env::current_exe().map_err(|_| "Cannot locate the installed app")?);
    #[cfg(not(target_os = "linux"))]
    let path = {
        let _ = app;
        std::env::current_exe().map_err(|_| "Cannot locate the installed app")?
    };
    let path = path
        .canonicalize()
        .map_err(|_| "Cannot resolve the installed app")?;
    let text = path
        .to_str()
        .ok_or("The installed app path must be UTF-8")?;
    if !path.is_absolute()
        || text.len() > 4096
        || text.chars().any(char::is_control)
        || temporary_location(
            &path,
            &std::env::temp_dir()
                .canonicalize()
                .map_err(|_| "Cannot resolve the temporary directory")?,
        )
        || !path.is_file()
    {
        return Err("Install Runner in a permanent location before enabling Open at login.".into());
    }
    #[cfg(target_os = "macos")]
    if !text.contains(".app/Contents/MacOS/") {
        return Err("Install the Runner app before enabling Open at login.".into());
    }
    #[cfg(target_os = "macos")]
    {
        if readonly_volume(&path)? {
            return Err(
                "Install Runner on a writable permanent volume before enabling Open at login."
                    .into(),
            );
        }
    }
    Ok(path)
}
#[cfg(target_os = "macos")]
fn readonly_volume(path: &Path) -> Result<bool, String> {
    use std::os::unix::ffi::OsStrExt;
    let path =
        std::ffi::CString::new(path.as_os_str().as_bytes()).map_err(|_| "Unsupported app path")?;
    let mut info = std::mem::MaybeUninit::<libc::statfs>::uninit();
    // statfs initializes the complete buffer on success; the C string lives through the call.
    let result = unsafe { libc::statfs(path.as_ptr(), info.as_mut_ptr()) };
    if result != 0 {
        return Err("Cannot confirm the app installation volume".into());
    }
    Ok(unsafe { info.assume_init() }.f_flags & libc::MNT_RDONLY as u32 != 0)
}
fn temporary_location(path: &Path, canonical_temp: &Path) -> bool {
    path.starts_with(canonical_temp)
        || path
            .components()
            .any(|component| component.as_os_str() == "AppTranslocation")
}
#[tauri::command]
pub(crate) async fn desktop_startup_status(app: tauri::AppHandle) -> Result<Status, String> {
    operate(app, None).await
}
#[tauri::command]
pub(crate) async fn set_desktop_startup(
    app: tauri::AppHandle,
    enabled: bool,
) -> Result<Status, String> {
    operate(app, Some(enabled)).await
}
async fn operate(app: tauri::AppHandle, change: Option<bool>) -> Result<Status, String> {
    let guard = crate::background::WorkGuard::begin()?;
    tauri::async_runtime::spawn_blocking(move || {
        let _guard = guard;
        let _operation = OPERATION
            .lock()
            .map_err(|_| "Login settings are unavailable")?;
        let path = match executable(&app) {
            Ok(path) => path,
            Err(warning) if change.is_none() => {
                return Ok(Status {
                    schema_version: "infergrade.startup.v1",
                    available: false,
                    enabled: false,
                    warning: Some(warning),
                })
            }
            Err(error) => return Err(error),
        };
        platform(&path, change)
    })
    .await
    .map_err(|_| "Could not finish reading login settings".to_string())?
}
#[cfg(unix)]
fn read_entry(path: &Path) -> Result<Option<Vec<u8>>, String> {
    use std::{io::Read, os::unix::fs::OpenOptionsExt};
    let mut file = match std::fs::OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK)
        .open(path)
    {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("Cannot safely read the login entry".into()),
    };
    let metadata = file
        .metadata()
        .map_err(|_| "Cannot inspect the login entry")?;
    if !metadata.is_file() || metadata.len() > 32768 {
        return Err("The login entry is not a supported regular file".into());
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(32769)
        .read_to_end(&mut bytes)
        .map_err(|_| "Cannot read the login entry")?;
    if bytes.len() > 32768 {
        return Err("The login entry is too large".into());
    }
    Ok(Some(bytes))
}
#[cfg(unix)]
fn write_entry(path: &Path, bytes: &[u8]) -> Result<(), String> {
    use std::{io::Write, os::unix::fs::OpenOptionsExt};
    let parent = path.parent().ok_or("Missing login entry directory")?;
    std::fs::create_dir_all(parent).map_err(|_| "Cannot create the login entry directory")?;
    let scratch = parent.join(format!(
        ".infergrade-login-{}-{}",
        std::process::id(),
        nonce()
    ));
    let result = (|| {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&scratch)
            .map_err(|_| "Cannot save the login entry")?;
        file.write_all(bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| "Cannot save the login entry")?;
        std::fs::rename(&scratch, path).map_err(|_| "Cannot replace the login entry")?;
        std::fs::File::open(parent)
            .and_then(|file| file.sync_all())
            .map_err(|_| "Cannot sync the login entry")
    })();
    let _ = std::fs::remove_file(scratch);
    Ok(result?)
}
#[cfg(unix)]
fn file_registration(path: &Path, expected: &[u8], change: Option<bool>) -> Result<Status, String> {
    let current = read_entry(path)?;
    // Refuse to overwrite/remove a differently configured entry, including an old installation.
    if current.as_deref().is_some_and(|bytes| bytes != expected) {
        return Err("An existing login entry differs from this installation. Remove that entry in your OS login settings before changing this setting.".into());
    }
    if let Some(enabled) = change {
        if enabled {
            write_entry(path, expected)?;
        } else if current.is_some() {
            std::fs::remove_file(path).map_err(|_| "Cannot remove the login entry")?;
        }
    }
    Ok(status(read_entry(path)?.as_deref() == Some(expected)))
}
#[cfg(target_os = "macos")]
fn mac_entry(exe: &Path) -> Result<Vec<u8>, String> {
    let mut dict = plist::Dictionary::new();
    dict.insert("Label".into(), ID.into());
    dict.insert(
        "ProgramArguments".into(),
        plist::Value::Array(vec![exe.to_str().ok_or("Unsupported app path")?.into()]),
    );
    dict.insert("RunAtLoad".into(), true.into());
    let mut bytes = Vec::new();
    plist::Value::Dictionary(dict)
        .to_writer_xml(&mut bytes)
        .map_err(|_| "Cannot serialize the login entry")?;
    Ok(bytes)
}
#[cfg(target_os = "macos")]
fn platform(exe: &Path, change: Option<bool>) -> Result<Status, String> {
    let root = std::env::var_os("HOME").ok_or("Cannot locate your login settings")?;
    file_registration(
        &PathBuf::from(root)
            .join("Library/LaunchAgents")
            .join(format!("{ID}.plist")),
        &mac_entry(exe)?,
        change,
    )
}
#[cfg(target_os = "linux")]
fn linux_entry(exe: &Path) -> Result<Vec<u8>, String> {
    let text = exe.to_str().ok_or("Unsupported app path")?;
    // Desktop-entry field expansion inside quotes is undefined; fail closed for these paths.
    if text.contains(['%', '=']) || text.chars().any(char::is_control) {
        return Err("Open at login requires an installation path without percent signs, equals signs or control characters.".into());
    }
    let mut quoted = String::new();
    for ch in text.chars() {
        match ch {
            '\\' => quoted.push_str("\\\\\\\\"),
            '"' => quoted.push_str("\\\\\""),
            '$' => quoted.push_str("\\\\$"),
            '`' => quoted.push_str("\\\\`"),
            _ => quoted.push(ch),
        }
    }
    Ok(format!("[Desktop Entry]\nType=Application\nName=InferGrade Runner\nExec=\"{quoted}\"\nTerminal=false\nStartupNotify=false\nX-InferGrade-Startup-Version=1\n").into_bytes())
}
#[cfg(target_os = "linux")]
fn platform(exe: &Path, change: Option<bool>) -> Result<Status, String> {
    let root = match std::env::var_os("XDG_CONFIG_HOME") {
        Some(root) if Path::new(&root).is_absolute() => PathBuf::from(root),
        _ => PathBuf::from(std::env::var_os("HOME").ok_or("Cannot locate your login settings")?)
            .join(".config"),
    };
    file_registration(
        &root.join("autostart").join(format!("{ID}.desktop")),
        &linux_entry(exe)?,
        change,
    )
}
#[cfg(windows)]
fn windows_registration(
    root: &winreg::RegKey,
    subkey: &str,
    exe: &Path,
    change: Option<bool>,
) -> Result<Status, String> {
    use winreg::enums::{KEY_READ, KEY_WRITE};
    let text = exe.to_str().ok_or("Unsupported app path")?;
    if text.contains('"') || text.chars().any(char::is_control) {
        return Err("Unsupported app path".into());
    }
    let expected = format!("\"{text}\"");
    if expected.encode_utf16().count() > 260 {
        return Err("Windows Open at login requires an installed app command of at most 260 characters. Install Runner in a shorter path.".into());
    }
    let read = || -> Result<Option<String>, String> {
        let key = match root.open_subkey_with_flags(subkey, KEY_READ) {
            Ok(key) => key,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(_) => return Err("Cannot read login settings".into()),
        };
        match key.get_value(ID) {
            Ok(value) => Ok(Some(value)),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(_) => Err("Cannot read the Runner login entry".into()),
        }
    };
    let current = read()?;
    if current.as_ref().is_some_and(|value| value != &expected) {
        return Err("An existing login entry differs from this installation. Remove that entry in Windows Startup settings before changing this setting.".into());
    }
    if let Some(enabled) = change {
        if enabled {
            let (key, _) = root
                .create_subkey_with_flags(subkey, KEY_READ | KEY_WRITE)
                .map_err(|_| "Cannot open login settings")?;
            key.set_value(ID, &expected)
                .map_err(|_| "Cannot save login settings")?;
        } else if current.is_some() {
            root.open_subkey_with_flags(subkey, KEY_WRITE)
                .map_err(|_| "Cannot open login settings")?
                .delete_value(ID)
                .map_err(|_| "Cannot remove login settings")?;
        }
    }
    Ok(status(read()?.as_ref() == Some(&expected)))
}
#[cfg(windows)]
fn platform(exe: &Path, change: Option<bool>) -> Result<Status, String> {
    let root = winreg::RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
    let mut result = windows_registration(
        &root,
        "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
        exe,
        change,
    )?;
    if result.enabled {
        let approval = match root.open_subkey(
            "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run",
        ) {
            Ok(key) => match key.get_raw_value(ID) {
                Ok(value) => Some(value),
                Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
                Err(_) => return Err("Cannot confirm Windows Startup approval".into()),
            },
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(_) => return Err("Cannot confirm Windows Startup approval".into()),
        };
        if let Some(value) = approval {
            if !approval_enabled(&value)? {
                result.enabled = false;
                result.warning = Some("Windows has disabled this login entry. Enable InferGrade Runner in Windows Startup settings.".into());
            }
        }
    }
    Ok(result)
}
#[cfg(windows)]
fn approval_enabled(value: &winreg::RegValue) -> Result<bool, String> {
    if value.vtype != winreg::enums::REG_BINARY
        || value.bytes.len() != 12
        || value.bytes[1..4] != [0, 0, 0]
    {
        return Err("Cannot confirm Windows Startup approval".into());
    }
    match value.bytes[0] { 2 => Ok(true), 3 => Ok(false), _ => Err("Cannot confirm Windows Startup approval. Check InferGrade Runner in Windows Startup settings.".into()) }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn temporary_and_translocated_paths_are_not_permanent_installations() {
        assert!(temporary_location(
            Path::new("/private/var/folders/me/tmp/Runner.app/Contents/MacOS/runner"),
            Path::new("/private/var/folders/me/tmp")
        ));
        assert!(temporary_location(
            Path::new(
                "/private/var/folders/me/AppTranslocation/ABC/d/Runner.app/Contents/MacOS/runner"
            ),
            Path::new("/tmp")
        ));
        assert!(!temporary_location(
            Path::new("/Applications/Runner.app/Contents/MacOS/runner"),
            Path::new("/tmp")
        ));
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn actual_volume_status_is_read_without_mutating_login_settings() {
        readonly_volume(&std::env::current_exe().unwrap()).unwrap();
    }
    #[cfg(unix)]
    #[test]
    fn isolated_registration_readback_and_foreign_entry_refusal() {
        let directory = std::env::temp_dir().join(format!("infergrade-startup-{}", nonce()));
        std::fs::create_dir_all(&directory).unwrap();
        let entry = directory.join("entry");
        assert!(!file_registration(&entry, b"owned", None).unwrap().enabled);
        assert!(!entry.exists());
        assert!(
            file_registration(&entry, b"owned", Some(true))
                .unwrap()
                .enabled
        );
        assert!(file_registration(&entry, b"other", Some(false)).is_err());
        assert_eq!(std::fs::read(&entry).unwrap(), b"owned");
        assert!(
            !file_registration(&entry, b"owned", Some(false))
                .unwrap()
                .enabled
        );
        std::os::unix::fs::symlink(directory.join("missing"), &entry).unwrap();
        assert!(file_registration(&entry, b"owned", Some(true)).is_err());
        std::fs::remove_dir_all(directory).unwrap();
    }
    #[cfg(target_os = "macos")]
    #[test]
    fn plist_roundtrip_preserves_spaces_and_xml_characters() {
        let exe = Path::new("/Applications/Runner & Friends.app/Contents/MacOS/infergrade");
        let parsed =
            plist::Value::from_reader(std::io::Cursor::new(mac_entry(exe).unwrap())).unwrap();
        let dict = parsed.as_dictionary().unwrap();
        assert_eq!(dict["Label"].as_string(), Some(ID));
        assert_eq!(
            dict["ProgramArguments"].as_array().unwrap()[0].as_string(),
            exe.to_str()
        );
        assert_eq!(dict["RunAtLoad"].as_boolean(), Some(true));
    }
    #[cfg(target_os = "linux")]
    #[test]
    fn desktop_entry_quotes_spaces_and_rejects_field_expansion() {
        let text =
            String::from_utf8(linux_entry(Path::new("/home/me/Runner App.AppImage")).unwrap())
                .unwrap();
        assert!(text.contains("Exec=\"/home/me/Runner App.AppImage\"\n"));
        assert!(linux_entry(Path::new("/home/me/Runner%U.AppImage")).is_err());
    }
    #[cfg(target_os = "linux")]
    #[test]
    fn gio_launches_exact_quoted_executable_with_reserved_characters() {
        use std::os::unix::fs::PermissionsExt;
        let directory = std::env::temp_dir().join(format!("infergrade-startup-gio-{}", nonce()));
        std::fs::create_dir_all(&directory).unwrap();
        let exe = directory.join(r#"Runner $cash `tick` \ "quote".sh"#);
        let marker = directory.join("launched");
        std::fs::write(
            &exe,
            format!("#!/bin/sh\nprintf ok > '{}'\n", marker.display()),
        )
        .unwrap();
        std::fs::set_permissions(&exe, std::fs::Permissions::from_mode(0o700)).unwrap();
        let entry = directory.join("com.infergrade.runner.desktop");
        std::fs::write(&entry, linux_entry(&exe).unwrap()).unwrap();
        let result = std::process::Command::new("gio")
            .arg("launch")
            .arg(&entry)
            .output()
            .expect("gio is required for actual desktop-entry parsing");
        assert!(
            result.status.success(),
            "gio launch failed: {}",
            String::from_utf8_lossy(&result.stderr)
        );
        for _ in 0..50 {
            if marker.exists() {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
        assert_eq!(std::fs::read(&marker).unwrap(), b"ok");
        std::fs::remove_dir_all(directory).unwrap();
    }
    #[cfg(windows)]
    #[test]
    fn malformed_or_unknown_startup_approval_is_not_enabled() {
        let mut value = winreg::RegValue {
            vtype: winreg::enums::REG_BINARY,
            bytes: vec![0; 12],
        };
        value.bytes[0] = 2;
        assert!(approval_enabled(&value).unwrap());
        value.bytes[0] = 3;
        assert!(!approval_enabled(&value).unwrap());
        value.bytes[0] = 8;
        assert!(approval_enabled(&value).is_err());
        value.bytes.clear();
        assert!(approval_enabled(&value).is_err());
    }
    #[cfg(windows)]
    #[test]
    fn isolated_registry_roundtrip_quotes_executable_and_preserves_foreign_value() {
        let root = winreg::RegKey::predef(winreg::enums::HKEY_CURRENT_USER);
        let key = format!("Software\\InferGradeStartupAcceptance\\{}", nonce());
        let exe = Path::new("C:\\Users\\Me\\Runner App\\infergrade.exe");
        let long = format!("C:\\{}\\infergrade.exe", "a".repeat(260));
        assert!(windows_registration(&root, &key, Path::new(&long), Some(true)).is_err());
        assert!(root.open_subkey(&key).is_err());
        assert!(
            !windows_registration(&root, &key, exe, None)
                .unwrap()
                .enabled
        );
        assert!(
            windows_registration(&root, &key, exe, Some(true))
                .unwrap()
                .enabled
        );
        let actual: String = root.open_subkey(&key).unwrap().get_value(ID).unwrap();
        assert_eq!(actual, "\"C:\\Users\\Me\\Runner App\\infergrade.exe\"");
        assert!(
            windows_registration(&root, &key, Path::new("C:\\other.exe"), Some(false)).is_err()
        );
        assert!(
            !windows_registration(&root, &key, exe, Some(false))
                .unwrap()
                .enabled
        );
        root.delete_subkey_all(&key).unwrap();
    }
}
