//! Server-authoritative machine names scoped to the saved paired machine.
use infergrade_runner_engine::{
    build_hub_json_request, execute_hub_json_request, normalize_api_url, profile_string,
    runner_id_from_profile, validate_hub_path_id, HubMethod,
};
use serde_json::{json, Value};
fn valid_label(label: &str) -> bool {
    !label.trim().is_empty() && label.chars().count() <= 120 && !label.chars().any(char::is_control)
}
fn project(body: &Value, runner_id: &str) -> Result<Value, String> {
    let label = body
        .pointer("/runner/label")
        .and_then(Value::as_str)
        .ok_or("Hub returned an invalid machine name")?;
    if body["schema_version"] != "hub.machine_name.v1"
        || body.pointer("/runner/runner_id").and_then(Value::as_str) != Some(runner_id)
        || !valid_label(label)
    {
        return Err("Hub returned an invalid machine name".into());
    }
    Ok(json!({"runner_id": runner_id, "label": label}))
}
async fn request_name(label: Option<String>) -> Result<Value, String> {
    if label.as_deref().is_some_and(|name| !valid_label(name)) {
        return Err("Machine name must be 1–120 characters without control characters".into());
    }
    let (api, runner_id, token) = {
        let _guard = super::PAIRING_STATE_LOCK.read().await;
        let profile =
            super::load_runner_profile()?.ok_or("Connect this Runner before changing its name")?;
        let api = normalize_api_url(
            &profile_string(Some(&profile), "api_url")
                .ok_or("Pairing is missing the Hub API URL")?,
        )?;
        let runner_id = runner_id_from_profile(Some(&profile));
        validate_hub_path_id(&runner_id, "runner_id")
            .map_err(|_| "Pairing has an invalid machine identity")?;
        let token = super::load_runner_token_value()?
            .ok_or("Connect this Runner before changing its name")?;
        (api, runner_id, token)
    };
    let request = build_hub_json_request(
        if label.is_some() {
            HubMethod::Put
        } else {
            HubMethod::Get
        },
        &api,
        &format!("/v1/runners/{runner_id}/name"),
        label.map(|value| json!({"label": value.trim()})),
        Some(&token),
    )
    .map_err(|_| "Could not prepare the machine name request")?;
    let response = execute_hub_json_request(&request).await.map_err(|_| "Could not read or save the machine name. Check the Hub connection and update Hub if needed.")?;
    let _guard = super::PAIRING_STATE_LOCK.read().await;
    let current = super::load_runner_profile()?
        .ok_or("Runner connection changed. Refresh the machine name")?;
    if runner_id_from_profile(Some(&current)) != runner_id
        || profile_string(Some(&current), "api_url")
            .and_then(|value| normalize_api_url(&value).ok())
            .as_deref()
            != Some(api.as_str())
        || super::load_runner_token_value()?.as_deref() != Some(token.as_str())
    {
        return Err("Runner connection changed. Refresh the machine name".into());
    }
    project(&response.body, &runner_id)
}
#[tauri::command]
pub async fn desktop_machine_name() -> Result<Value, String> {
    request_name(None).await
}
#[tauri::command]
pub async fn set_desktop_machine_name(label: String) -> Result<Value, String> {
    request_name(Some(label)).await
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn name_projection_requires_exact_machine_and_discards_unknown_data() {
        let body = json!({"schema_version":"hub.machine_name.v1", "runner":{"runner_id":"runner_one", "label":"Study Mac", "access_token":"must-not-leave-native"}, "unknown":"private"});
        assert_eq!(
            project(&body, "runner_one").unwrap(),
            json!({"runner_id":"runner_one", "label":"Study Mac"})
        );
        assert!(project(&body, "runner_two").is_err());
        for label in ["", "Bad\nName", &"x".repeat(121)] {
            assert!(!valid_label(label));
        }
    }
}
