//! Authenticated machine history; no model output, credentials or result claims.
use infergrade_runner_engine::{
    build_hub_json_request, execute_hub_json_request, normalize_api_url, profile_string,
    runner_id_from_profile, validate_hub_path_id, HubMethod,
};
use serde_json::{json, Value};
fn text(value: &Value, key: &str, limit: usize) -> Value {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(|s| Value::String(s.chars().filter(|c| !c.is_control()).take(limit).collect()))
        .unwrap_or(Value::Null)
}
fn project(body: &Value, runner_id: &str) -> Result<Value, String> {
    if body["runner_id"].as_str() != Some(runner_id)
        || body["history_scope"] != "recent_machine_jobs"
    {
        return Err("Hub does not yet support machine activity. Update Hub and try again.".into());
    }
    let rows = body["runs"]
        .as_array()
        .ok_or("Hub returned an invalid activity response.")?;
    if rows.len() > 100 {
        return Err("Hub returned an oversized activity response.".into());
    }
    let mut jobs = vec![];
    for row in rows {
        let target = row
            .get("target_runner_id")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .or_else(|| row.pointer("/worker/runner_id").and_then(Value::as_str));
        if target != Some(runner_id) {
            continue;
        }
        let Some(id) = row["run_id"].as_str() else {
            continue;
        };
        if validate_hub_path_id(id, "run_id").is_err() {
            continue;
        }
        let status = row["status"].as_str().unwrap_or("unknown");
        if !matches!(
            status,
            "awaiting_execution"
                | "running"
                | "completed"
                | "failed"
                | "cancelled"
                | "queued"
                | "dispatching"
                | "paused"
        ) {
            continue;
        }
        let progress = row["progress_percent"]
            .as_f64()
            .filter(|n| n.is_finite() && *n >= 0.0 && *n <= 100.0);
        jobs.push(json!({"run_id":id,"status":status,"model":text(row,"model",180),"updated_at":text(row,"updated_at",40),"created_at":text(row,"created_at",40),"current_stage":text(row,"current_stage",80),"progress_percent":progress,"execution_mode":text(row,"execution_mode",40),"publication_state":row.pointer("/ownership/visibility").and_then(Value::as_str),"error_code":row.pointer("/last_error/error_code").and_then(Value::as_str).map(|s|s.chars().filter(|c|c.is_ascii_alphanumeric()||*c=='_').take(100).collect::<String>())}));
    }
    Ok(json!({"runner_id":runner_id,"runs":jobs,"history_scope":"recent_machine_jobs","limit":100}))
}
async fn fetch_activity(api: &str, runner_id: &str, token: &str) -> Result<Value, String> {
    let request = build_hub_json_request(
        HubMethod::Get,
        api,
        &format!("/v1/runs?runner_id={runner_id}&limit=100"),
        None,
        Some(token),
    )
    .map_err(|_| "Could not prepare machine activity request.".to_string())?;
    let response = execute_hub_json_request(&request).await.map_err(|_| {
        "Could not load machine activity. Check the Hub connection and try again.".to_string()
    })?;
    Ok(response.body)
}
#[tauri::command]
pub async fn desktop_machine_activity() -> Result<Value, String> {
    let (api, runner_id, token) = {
        let _guard = super::PAIRING_STATE_LOCK.read().await;
        let profile =
            super::load_runner_profile()?.ok_or("Connect this Runner to view its Hub activity.")?;
        let api = normalize_api_url(
            &profile_string(Some(&profile), "api_url")
                .ok_or("Pairing is missing the Hub API URL.")?,
        )?;
        let runner_id = runner_id_from_profile(Some(&profile));
        validate_hub_path_id(&runner_id, "runner_id").map_err(|e| e.message().to_string())?;
        let token = super::load_runner_token_value()?
            .ok_or("Connect this Runner to view its Hub activity.")?;
        (api, runner_id, token)
    };
    let body = fetch_activity(&api, &runner_id, &token).await?;
    let _guard = super::PAIRING_STATE_LOCK.read().await;
    let current =
        super::load_runner_profile()?.ok_or("Runner connection changed. Refresh activity.")?;
    if runner_id_from_profile(Some(&current)) != runner_id
        || profile_string(Some(&current), "api_url").as_deref() != Some(api.as_str())
        || super::load_runner_token_value()?.as_deref() != Some(token.as_str())
    {
        return Err("Runner connection changed. Refresh activity.".into());
    }
    let mut result = project(&body, &runner_id)?;
    result["api_url"] = json!(api);
    Ok(result)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    #[ignore = "requires isolated local Hub and protected protocol profile"]
    async fn actual_local_hub_machine_activity_protocol() {
        let path = std::env::var("INFERGRADE_ACTIVITY_PROTOCOL_PROFILE")
            .expect("protected protocol profile path");
        let profile: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        let api = profile["api_url"].as_str().unwrap();
        assert!(matches!(
            url::Url::parse(api).unwrap().host_str(),
            Some("127.0.0.1") | Some("localhost")
        ));
        let runner = profile["runner_id"].as_str().unwrap();
        let token = profile["access_token"].as_str().unwrap();
        let body = fetch_activity(api, runner, token).await.unwrap();
        let mut projected = project(&body, runner).unwrap();
        projected["api_url"] = json!(api);
        assert_eq!(projected["runs"].as_array().unwrap().len(), 1);
        assert_eq!(projected["runs"][0]["status"], "running");
        assert_eq!(projected["runs"][0]["progress_percent"], 0.0);
        assert!(!projected.to_string().contains(token));
        let output = std::path::Path::new(&path).with_file_name("native-activity.json");
        let mut options = std::fs::OpenOptions::new();
        options.write(true).create(true).truncate(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        use std::io::Write;
        options
            .open(output)
            .unwrap()
            .write_all(projected.to_string().as_bytes())
            .unwrap();
    }
    #[test]
    fn rejects_unscoped_server_and_filters_other_targets_and_invalid_progress() {
        assert!(project(&json!({"runs":[]}), "runner_mine").is_err());
        let mut body = json!({"runner_id":"runner_mine","history_scope":"recent_machine_jobs","runs":[{"run_id":"run_mine","target_runner_id":"runner_mine","status":"completed","model":"Qwen","progress_percent":-1,"prompt":"private prompt","access_token":"private token","ownership":{"visibility":"private"}},{"run_id":"run_other","target_runner_id":"runner_other","worker":{"runner_id":"runner_mine"},"status":"completed"},{"run_id":"run_legacy","worker":{"runner_id":"runner_mine"},"status":"failed","progress_percent":0}]});
        let value = project(&body, "runner_mine").unwrap();
        assert_eq!(value["runs"].as_array().unwrap().len(), 2);
        assert!(value["runs"][0]["progress_percent"].is_null());
        assert_eq!(value["runs"][1]["progress_percent"], 0.0);
        assert!(!value.to_string().contains("private token"));
        assert!(!value.to_string().contains("private prompt"));
        assert_eq!(value["runs"][0]["publication_state"], "private");
        body["runner_id"] = json!("runner_other");
        assert!(project(&body, "runner_mine").is_err());
    }
    #[test]
    fn oversized_history_is_rejected() {
        assert!(project(&json!({"runner_id":"runner_mine","history_scope":"recent_machine_jobs","runs":vec![json!({});101]}),"runner_mine").is_err());
    }
}
