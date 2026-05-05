use keyring::{Entry, Error as KeyringError};

const KEYRING_SERVICE: &str = "com.infergrade.runner";
const KEYRING_USER: &str = "hub-runner-token";

fn runner_token_entry() -> Result<Entry, String> {
    Entry::new(KEYRING_SERVICE, KEYRING_USER)
        .map_err(|error| format!("could not open OS credential store: {error}"))
}

fn is_user_canceled(error: &KeyringError) -> bool {
    let message = error.to_string().to_lowercase();
    message.contains("cancel") || message.contains("user interaction")
}

#[tauri::command]
fn save_runner_token(token: String) -> Result<(), String> {
    let token = token.trim();
    if token.is_empty() {
        return Err("runner token cannot be empty".to_string());
    }

    let entry = runner_token_entry()?;
    match entry.set_password(token) {
        Ok(()) => Ok(()),
        Err(first_error) if is_user_canceled(&first_error) => Err(format!("credential storage was canceled: {first_error}")),
        Err(first_error) => {
            let _ = entry.delete_credential();
            entry
                .set_password(token)
                .map_err(|second_error| format!("could not replace runner token after {first_error}: {second_error}"))
        }
    }
}

#[tauri::command]
fn load_runner_token() -> Result<Option<String>, String> {
    match runner_token_entry()?.get_password() {
        Ok(token) => Ok(Some(token)),
        Err(KeyringError::NoEntry) => Ok(None),
        Err(error) if is_user_canceled(&error) => Ok(None),
        Err(error) => Err(format!("could not load runner token: {error}")),
    }
}

#[tauri::command]
fn clear_runner_token() -> Result<(), String> {
    match runner_token_entry()?.delete_credential() {
        Ok(()) | Err(KeyringError::NoEntry) => Ok(()),
        Err(error) if is_user_canceled(&error) => Ok(()),
        Err(error) => Err(format!("could not clear runner token: {error}")),
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            save_runner_token,
            load_runner_token,
            clear_runner_token
        ])
        .run(tauri::generate_context!())
        .expect("error while running InferGrade desktop runner");
}
