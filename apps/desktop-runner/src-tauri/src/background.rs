//! Native admission and exit guards: a hidden window must never be an orphaned job.
use serde_json::{json, Value};
use std::fs;
use std::io::Write;
use std::path::Path;
use std::sync::{Mutex, OnceLock};
use tauri::{AppHandle, Emitter, Manager};

#[derive(Debug, PartialEq)]
enum CloseAction {
    Hide,
    Block,
    Close,
}

#[derive(Default)]
struct Lifecycle {
    active: usize,
    maintenance: bool,
    exiting: bool,
    keep_running: bool,
    tray_available: bool,
    warning: Option<String>,
}
impl Lifecycle {
    fn admit(&mut self) -> Result<(), String> {
        if self.maintenance {
            return Err("Cache cleanup is active. Try again after it finishes.".into());
        }
        if self.exiting {
            return Err("Runner is quitting. Reopen it before starting work.".into());
        }
        self.active += 1;
        Ok(())
    }
    fn request_exit(&mut self) -> bool {
        if self.active > 0 {
            return false;
        }
        self.exiting = true;
        true
    }
    fn close_action(&mut self) -> CloseAction {
        if self.can_hide() {
            return CloseAction::Hide;
        }
        if self.request_exit() {
            CloseAction::Close
        } else {
            CloseAction::Block
        }
    }
    fn can_hide(&self) -> bool {
        self.keep_running && self.tray_available
    }
}
fn lifecycle() -> &'static Mutex<Lifecycle> {
    static STATE: OnceLock<Mutex<Lifecycle>> = OnceLock::new();
    STATE.get_or_init(|| Mutex::new(Lifecycle::default()))
}
pub(crate) struct WorkGuard {
    _lease: crate::cache_lease::ReadLease,
}
impl WorkGuard {
    pub(crate) fn begin() -> Result<Self, String> {
        let lease = crate::cache_lease::ReadLease::acquire(&crate::desktop_artifact_cache_dir()?)?;
        lifecycle()
            .lock()
            .map_err(|_| "Runner lifecycle is unavailable".to_string())?
            .admit()?;
        Ok(Self { _lease: lease })
    }
}
impl Drop for WorkGuard {
    fn drop(&mut self) {
        if let Ok(mut state) = lifecycle().lock() {
            state.active = state.active.saturating_sub(1);
        }
    }
}
pub(crate) struct MaintenanceGuard;
impl MaintenanceGuard {
    pub(crate) fn begin() -> Result<Self, String> {
        let mut state = lifecycle()
            .lock()
            .map_err(|_| "Runner lifecycle is unavailable")?;
        if state.active > 0 || state.exiting {
            return Err(
                "Finish active work and stop listening before clearing cache space.".into(),
            );
        }
        state.maintenance = true;
        state.active = 1;
        Ok(Self)
    }
}
impl Drop for MaintenanceGuard {
    fn drop(&mut self) {
        if let Ok(mut state) = lifecycle().lock() {
            state.maintenance = false;
            state.active = state.active.saturating_sub(1);
        }
    }
}
fn preference_path() -> Result<std::path::PathBuf, String> {
    Ok(crate::runner_config_dir()?.join("desktop-background.json"))
}
fn read_preference(path: &Path) -> Result<bool, String> {
    match fs::metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(false),
        Ok(meta) if meta.is_file() && meta.len() <= 4096 => {}
        _ => return Err("Could not read background preference. Close-to-tray is disabled.".into()),
    }
    let value: Value = serde_json::from_slice(
        &fs::read(path).map_err(|_| "Could not read background preference.")?,
    )
    .map_err(|_| "Could not read background preference. Close-to-tray is disabled.")?;
    value
        .get("keep_running")
        .and_then(Value::as_bool)
        .ok_or_else(|| "Invalid background preference. Close-to-tray is disabled.".into())
}
fn write_preference(path: &Path, enabled: bool) -> Result<(), String> {
    fs::create_dir_all(
        path.parent()
            .ok_or("Background preference directory is unavailable.")?,
    )
    .map_err(|_| "Could not create background preference directory.")?;
    let temporary = path.with_extension(format!("{}.tmp", std::process::id()));
    let mut options = fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let result = (|| -> std::io::Result<()> {
        let mut file = options.open(&temporary)?;
        file.write_all(serde_json::to_string(&json!({"schema_version":"infergrade.desktop_background.v1","keep_running":enabled}))?.as_bytes())?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temporary, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result.map_err(|_| "Could not save background preference. The setting was not changed.".into())
}
#[tauri::command]
pub(crate) fn desktop_background_status() -> Result<Value, String> {
    let state = lifecycle()
        .lock()
        .map_err(|_| "Runner lifecycle is unavailable".to_string())?;
    Ok(
        json!({"keep_running":state.keep_running,"tray_available":state.tray_available,"warning":state.warning}),
    )
}
#[tauri::command]
pub(crate) fn set_desktop_keep_running(enabled: bool) -> Result<Value, String> {
    let mut state = lifecycle()
        .lock()
        .map_err(|_| "Runner lifecycle is unavailable".to_string())?;
    if enabled && !state.tray_available {
        return Err(
            "The system tray is unavailable. Keep this window open while Runner works.".into(),
        );
    }
    if state.exiting {
        return Err("Runner is quitting.".into());
    }
    write_preference(&preference_path()?, enabled)?;
    state.keep_running = enabled;
    state.warning = None;
    drop(state);
    desktop_background_status()
}
pub(crate) fn show_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}
fn blocked_exit(app: &AppHandle) {
    show_window(app);
    let _=app.emit("infergrade-background-exit-blocked",json!({"message":"Runner is working. Stop listening or wait for the local check to finish before quitting."}));
}
pub(crate) fn initialize(app: &AppHandle) {
    use tauri::{
        menu::{Menu, MenuItem},
        tray::TrayIconBuilder,
    };
    let tray_result = (|| -> tauri::Result<()> {
        let show = MenuItem::with_id(app, "show-runner", "Show Runner", true, None::<&str>)?;
        let quit = MenuItem::with_id(app, "quit-runner", "Quit Runner", true, None::<&str>)?;
        let menu = Menu::with_items(app, &[&show, &quit])?;
        let mut tray = TrayIconBuilder::with_id("infergrade-runner")
            .tooltip("InferGrade Runner")
            .menu(&menu)
            .show_menu_on_left_click(true)
            .on_menu_event(|app, event| match event.id.as_ref() {
                "show-runner" => show_window(app),
                "quit-runner" => app.exit(0),
                _ => {}
            });
        if let Some(icon) = app.default_window_icon() {
            tray = tray.icon(icon.clone());
        }
        tray.build(app)?;
        Ok(())
    })();
    if let Ok(mut state) = lifecycle().lock() {
        state.tray_available = tray_result.is_ok();
        match preference_path().and_then(|p| read_preference(&p)) {
            Ok(enabled) => state.keep_running = enabled,
            Err(message) => state.warning = Some(message),
        }
        if !state.tray_available {
            state.keep_running = false;
            state.warning = Some(
                "The system tray is unavailable. Keep this window open while Runner works.".into(),
            );
        }
    }
}
pub(crate) fn window_event(window: &tauri::Window, event: &tauri::WindowEvent) {
    if let tauri::WindowEvent::CloseRequested { api, .. } = event {
        let action = lifecycle()
            .lock()
            .map(|mut state| state.close_action())
            .unwrap_or(CloseAction::Block);
        match action {
            CloseAction::Hide => {
                api.prevent_close();
                if window.hide().is_err() {
                    show_window(window.app_handle());
                }
            }
            CloseAction::Block => {
                api.prevent_close();
                blocked_exit(window.app_handle());
            }
            CloseAction::Close => {}
        }
    }
}
pub(crate) fn run_event(app: &AppHandle, event: tauri::RunEvent) {
    if let tauri::RunEvent::ExitRequested { api, .. } = event {
        let allowed = lifecycle()
            .lock()
            .map(|mut s| s.request_exit())
            .unwrap_or(false);
        if !allowed {
            api.prevent_exit();
            blocked_exit(app);
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn active_work_refuses_exit_without_losing_admission() {
        let mut state = Lifecycle::default();
        state.admit().unwrap();
        assert!(!state.request_exit());
        assert!(!state.exiting);
        state.active -= 1;
        assert!(state.request_exit());
        assert!(state.admit().is_err());
    }
    #[test]
    fn idle_window_close_fences_admission_before_destroying_the_window() {
        let mut state = Lifecycle::default();
        assert_eq!(state.close_action(), CloseAction::Close);
        assert!(state.admit().is_err());
        let mut busy = Lifecycle::default();
        busy.admit().unwrap();
        assert_eq!(busy.close_action(), CloseAction::Block);
        assert!(!busy.exiting);
    }
    #[test]
    fn closing_only_hides_with_both_preference_and_actual_tray() {
        let mut state = Lifecycle::default();
        assert!(!state.can_hide());
        state.keep_running = true;
        assert!(!state.can_hide());
        state.tray_available = true;
        assert!(state.can_hide());
    }
    #[test]
    fn preference_roundtrip_defaults_off_and_rejects_corruption() {
        let dir =
            std::env::temp_dir().join(format!("infergrade-background-test-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let path = dir.join("settings.json");
        assert!(!read_preference(&path).unwrap());
        write_preference(&path, true).unwrap();
        assert!(read_preference(&path).unwrap());
        write_preference(&path, false).unwrap();
        assert!(!read_preference(&path).unwrap());
        fs::write(&path, b"bad").unwrap();
        assert!(read_preference(&path).is_err());
        let _ = fs::remove_dir_all(dir);
    }
}
