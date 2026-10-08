//! Hugging Face credentials stay in the OS store and child environment.
use keyring::{Entry, Error};
use serde_json::{json, Value};
use std::env;
use std::time::Duration;
static LOCK: std::sync::Mutex<u64> = std::sync::Mutex::new(0);
const USER: &str = "hugging-face-token";
fn entry() -> Result<Entry, String> {
    let configured = env::var("INFERGRADE_ACCEPTANCE_KEYRING_SERVICE").ok();
    Entry::new(
        super::acceptance_keyring_service(configured.as_deref()),
        USER,
    )
    .map_err(|_| "Could not open the OS credential store.".into())
}
fn valid(token: &str) -> bool {
    token.starts_with("hf_")
        && (20..=256).contains(&token.len())
        && token
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_')
}
pub(crate) fn inherited_token() -> Option<String> {
    ["HF_TOKEN", "HUGGING_FACE_HUB_TOKEN", "HUGGINGFACE_TOKEN"]
        .iter()
        .find_map(|name| {
            env::var(name)
                .ok()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        })
}
pub(crate) fn saved_token() -> Result<Option<String>, String> {
    let _guard = LOCK.lock().map_err(|_| "Credential store is busy.")?;
    match entry()?.get_password() {
        Ok(token) if valid(&token) => Ok(Some(token)),
        Ok(_) => Err("Stored Hugging Face credential is invalid. Replace it in Settings.".into()),
        Err(Error::NoEntry) => Ok(None),
        Err(_) => Err("Could not read the OS credential store.".into()),
    }
}
fn resolve_listener_token(
    inherited: bool,
    load: impl FnOnce() -> Result<Option<String>, String>,
) -> (Option<String>, bool) {
    if inherited {
        return (None, false);
    }
    match load() {
        Ok(Some(token)) if valid(&token) => (Some(token), false),
        Ok(None) => (None, false),
        _ => (None, true),
    }
}
pub(crate) fn listener_token() -> (Option<String>, bool) {
    resolve_listener_token(inherited_token().is_some(), saved_token)
}
#[tauri::command]
pub fn desktop_hf_credential_status() -> Result<Value, String> {
    let saved = saved_token()?.is_some();
    Ok(json!({"saved":saved,"environment_override":inherited_token().is_some()}))
}
#[tauri::command]
pub async fn save_desktop_hf_credential(token: String) -> Result<Value, String> {
    let token = token.trim();
    if !valid(token) {
        return Err("Enter a Hugging Face user access token beginning with hf_.".into());
    }
    let generation = {
        let mut guard = LOCK.lock().map_err(|_| "Credential store is busy.")?;
        *guard += 1;
        *guard
    };
    // Never forward this credential through a redirect or to the InferGrade API.
    let client = reqwest::Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(10))
        .timeout(Duration::from_secs(20))
        .build()
        .map_err(|_| "Could not prepare Hugging Face sign-in.")?;
    let response = client
        .get("https://huggingface.co/api/whoami-v2")
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| "Could not contact Hugging Face. Check the connection and try again.")?;
    if !response.status().is_success() {
        return Err(if matches!(response.status().as_u16(), 401 | 403) {
            "Hugging Face did not accept this token. Check its permissions.".into()
        } else {
            "Hugging Face sign-in is unavailable. Try again later.".into()
        });
    }
    // The response contains account details; discard it instead of exposing it.
    let guard = LOCK.lock().map_err(|_| "Credential store is busy.")?;
    if *guard != generation {
        return Err("Credential settings changed. Try again.".into());
    }
    entry()?
        .set_password(token)
        .map_err(|_| "Could not save the token in the OS credential store.")?;
    Ok(json!({"saved":true,"environment_override":inherited_token().is_some()}))
}
#[tauri::command]
pub fn clear_desktop_hf_credential() -> Result<Value, String> {
    let mut guard = LOCK.lock().map_err(|_| "Credential store is busy.")?;
    *guard += 1;
    match entry()?.delete_credential() {
        Ok(()) | Err(Error::NoEntry) => (),
        Err(_) => return Err("Could not remove the saved Hugging Face credential.".into()),
    }
    Ok(json!({"saved":false,"environment_override":inherited_token().is_some()}))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn token_validation_rejects_headers_and_unbounded_inputs() {
        assert!(valid(&format!("hf_{}", "a".repeat(30))));
        for token in [
            "short".to_string(),
            format!("hf_{}", "a".repeat(300)),
            format!("hf_{}\r\nAuthorization: other", "a".repeat(30)),
        ] {
            assert!(!valid(&token));
        }
    }
    #[test]
    fn optional_store_failure_does_not_block_public_listener_or_env_priority() {
        assert_eq!(resolve_listener_token(false, || Ok(None)), (None, false));
        assert_eq!(
            resolve_listener_token(false, || Err("locked OS store".into())),
            (None, true)
        );
        assert_eq!(
            resolve_listener_token(false, || Ok(Some("malformed".into()))),
            (None, true)
        );
        assert_eq!(
            resolve_listener_token(true, || panic!("environment must take precedence")),
            (None, false)
        );
        let token = format!("hf_{}", "a".repeat(30));
        assert_eq!(
            resolve_listener_token(false, || Ok(Some(token.clone()))),
            (Some(token), false)
        );
    }
}
