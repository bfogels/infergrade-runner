//! On-demand result choices for this exact paired machine; Hub owns chart qualification.
use infergrade_runner_engine::{
    build_hub_json_request, execute_hub_json_request, normalize_api_url, profile_string,
    runner_id_from_profile, validate_hub_path_id, HubMethod,
};
use serde_json::{json, Value};
fn validate_target(watch: &Value, run_id: &str, runner_id: &str) -> Result<(), String> {
    let run = &watch["run"];
    let target = if run.get("target_runner_id").is_some_and(|v| !v.is_null()) {
        run["target_runner_id"].as_str()
    } else {
        run.pointer("/worker/runner_id").and_then(Value::as_str)
    };
    if run["run_id"].as_str() != Some(run_id)
        || target != Some(runner_id)
        || run["status"] != "completed"
    {
        return Err("This completed job is not assigned to the connected Runner".into());
    }
    Ok(())
}
fn project(body: &Value, run_id: &str) -> Result<Value, String> {
    if body["schema_version"] != "hub.run_results.v1" || body["run_id"].as_str() != Some(run_id) {
        return Err("Hub returned results for another job".into());
    }
    let rows = body["results"]
        .as_array()
        .ok_or("Hub returned invalid result choices")?;
    if rows.len() > 32 {
        return Err("Hub returned too many result choices".into());
    }
    let mut results = vec![];
    let mut seen = std::collections::HashSet::new();
    for row in rows {
        let id = row["result_id"]
            .as_str()
            .ok_or("Hub returned an invalid result identity")?;
        validate_hub_path_id(id, "result_id")
            .map_err(|_| "Hub returned an invalid result identity")?;
        if !seen.insert(id) {
            return Err("Hub returned duplicate result choices".into());
        }
        let title = row["checkpoint_name"]
            .as_str()
            .unwrap_or("Benchmark result")
            .chars()
            .filter(|c| !c.is_control())
            .take(180)
            .collect::<String>();
        let mut safe =
            json!({"result_id":id,"title":title,"kind":"report","reason":"navigation_unavailable"});
        safe["deployment_profile"] = json!(row["deployment_profile_id"]
            .as_str()
            .unwrap_or("Profile not reported")
            .chars()
            .filter(|c| !c.is_control())
            .take(120)
            .collect::<String>());
        if let Some(nav) = row.get("navigation") {
            let kind = nav["kind"].as_str().unwrap_or("");
            if nav["policy"] != "chart_point_navigation_v1"
                || nav["result_id"].as_str() != Some(id)
                || !matches!(kind, "compare_full" | "compare_context" | "report")
            {
                return Err("Hub returned an invalid result destination".into());
            }
            safe["kind"] = json!(kind);
            safe["reason"] = json!(nav["reason"]
                .as_str()
                .unwrap_or("unknown")
                .chars()
                .filter(|c| c.is_ascii_lowercase() || *c == '_')
                .take(80)
                .collect::<String>());
            if kind != "report" {
                let qualified = nav["qualified_count"]
                    .as_u64()
                    .ok_or("Hub returned invalid timing coverage")?;
                let attempted = nav["attempted_count"]
                    .as_u64()
                    .ok_or("Hub returned invalid timing coverage")?;
                let score = nav["score"]
                    .as_f64()
                    .filter(|v| v.is_finite() && *v >= 0.0 && *v <= 1.0)
                    .ok_or("Hub returned an invalid score")?;
                let seconds = nav["seconds_per_task"]
                    .as_f64()
                    .filter(|v| v.is_finite() && *v > 0.0)
                    .ok_or("Hub returned invalid timing")?;
                if qualified == 0
                    || qualified > attempted
                    || attempted > 1000000
                    || (kind == "compare_full" && qualified != attempted)
                    || (kind == "compare_context" && qualified >= attempted)
                {
                    return Err("Hub returned inconsistent timing coverage".into());
                }
                safe["qualified_count"] = json!(qualified);
                safe["attempted_count"] = json!(attempted);
                safe["score"] = json!(score);
                safe["seconds_per_task"] = json!(seconds);
            }
        }
        results.push(safe);
    }
    Ok(json!({"run_id":run_id,"results":results}))
}
async fn fetch(api: &str, token: &str, path: &str) -> Result<Value, String> {
    let request = build_hub_json_request(HubMethod::Get, api, path, None, Some(token))
        .map_err(|_| "Could not prepare result request")?;
    execute_hub_json_request(&request)
        .await
        .map(|r| r.body)
        .map_err(|_| "Could not load results. Check the Hub connection and try again.".into())
}
#[tauri::command]
pub async fn desktop_run_results(run_id: String) -> Result<Value, String> {
    validate_hub_path_id(&run_id, "run_id").map_err(|_| "Invalid Hub job identity")?;
    let (api, runner, token) = {
        let _guard = super::PAIRING_STATE_LOCK.read().await;
        let profile = super::load_runner_profile()?.ok_or("Connect this Runner to view results")?;
        let api = normalize_api_url(
            &profile_string(Some(&profile), "api_url").ok_or("Pairing is missing the Hub URL")?,
        )?;
        let runner = runner_id_from_profile(Some(&profile));
        validate_hub_path_id(&runner, "runner_id")
            .map_err(|_| "Pairing has an invalid machine identity")?;
        let token =
            super::load_runner_token_value()?.ok_or("Connect this Runner to view results")?;
        (api, runner, token)
    };
    let watch = fetch(&api, &token, &format!("/v1/runs/{run_id}/watch")).await?;
    validate_target(&watch, &run_id, &runner)?;
    let body = fetch(&api, &token, &format!("/v1/runs/{run_id}/results")).await?;
    let mut result = project(&body, &run_id)?;
    let _guard = super::PAIRING_STATE_LOCK.read().await;
    let current =
        super::load_runner_profile()?.ok_or("Runner connection changed. Refresh results")?;
    if runner_id_from_profile(Some(&current)) != runner
        || profile_string(Some(&current), "api_url")
            .and_then(|v| normalize_api_url(&v).ok())
            .as_deref()
            != Some(api.as_str())
        || super::load_runner_token_value()?.as_deref() != Some(token.as_str())
    {
        return Err("Runner connection changed. Refresh results".into());
    }
    result["api_url"] = json!(api);
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn explicit_target_is_authoritative_and_completed_job_is_required() {
        let mut watch = json!({"run":{"run_id":"run_one","status":"completed","target_runner_id":"runner_one","worker":{"runner_id":"runner_two"}}});
        assert!(validate_target(&watch, "run_one", "runner_one").is_ok());
        assert!(validate_target(&watch, "run_one", "runner_two").is_err());
        assert!(validate_target(&watch, "run_other", "runner_one").is_err());
        watch["run"]["status"] = json!("running");
        assert!(validate_target(&watch, "run_one", "runner_one").is_err());
        watch["run"]["status"] = json!("completed");
        watch["run"]["target_runner_id"] = Value::Null;
        assert!(validate_target(&watch, "run_one", "runner_two").is_ok());
    }
    fn body() -> Value {
        json!({"schema_version":"hub.run_results.v1","run_id":"run_one","results":[{"result_id":"qb_one","checkpoint_name":"Qwen","deployment_profile_id":"interactive_chat_v1","private_prompt":"must-never-render","navigation":{"policy":"chart_point_navigation_v1","kind":"compare_context","reason":"partial_natural_timing","result_id":"qb_one","qualified_count":88,"attempted_count":124,"score":0.348167,"seconds_per_task":1.39571}}]})
    }
    #[test]
    fn result_choices_are_closed_bounded_and_bound_to_each_exact_source() {
        let original = body();
        let safe = project(&original, "run_one").unwrap();
        assert_eq!(safe["results"][0]["kind"], "compare_context");
        assert!(!safe.to_string().contains("must-never-render"));
        assert!(project(&original, "run_other").is_err());
        let mut foreign = original.clone();
        foreign["results"][0]["navigation"]["result_id"] = json!("foreign");
        assert!(project(&foreign, "run_one").is_err());
        let mut large = original.clone();
        large["results"] = json!(vec![original["results"][0].clone(); 33]);
        assert!(project(&large, "run_one").is_err());
        let mut invalid = original.clone();
        invalid["results"][0]["navigation"]["score"] = json!(true);
        assert!(project(&invalid, "run_one").is_err());
        let mut inconsistent = original.clone();
        inconsistent["results"][0]["navigation"]["kind"] = json!("compare_full");
        assert!(project(&inconsistent, "run_one").is_err());
        let mut legacy = original;
        legacy["results"][0]
            .as_object_mut()
            .unwrap()
            .remove("navigation");
        assert_eq!(
            project(&legacy, "run_one").unwrap()["results"][0]["kind"],
            "report"
        );
    }
    #[tokio::test]
    #[ignore = "requires isolated actual-result Hub and protected protocol profile"]
    async fn actual_private_hub_result_navigation_protocol() {
        let path = std::env::var("INFERGRADE_RESULTS_PROTOCOL_PROFILE")
            .expect("protected isolated profile");
        let profile: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        let api = profile["api_url"].as_str().unwrap();
        assert!(matches!(
            url::Url::parse(api).unwrap().host_str(),
            Some("127.0.0.1") | Some("localhost")
        ));
        let runner = profile["runner_id"].as_str().unwrap();
        let token = profile["access_token"].as_str().unwrap();
        let run = "run_benchmark_qwen_qwen3_5_0_8b_07b69856_e0a18fd4";
        let watch = fetch(api, token, &format!("/v1/runs/{run}/watch"))
            .await
            .unwrap();
        validate_target(&watch, run, runner).unwrap();
        let body = fetch(api, token, &format!("/v1/runs/{run}/results"))
            .await
            .unwrap();
        let mut safe = project(&body, run).unwrap();
        safe["api_url"] = json!(api);
        assert_eq!(safe["results"].as_array().unwrap().len(), 1);
        assert_eq!(safe["results"][0]["kind"], "compare_context");
        assert_eq!(
            safe["results"][0]["result_id"],
            "qb_20261008_022753_9416d9a3_interactive_chat_v1"
        );
        assert_eq!(safe["results"][0]["qualified_count"], 88);
        assert!(!safe.to_string().contains(token));
        let mut options = std::fs::OpenOptions::new();
        options.create(true).truncate(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        use std::io::Write;
        let output = std::path::Path::new(&path)
            .with_file_name("infergrade-redesign-result-navigation-native-receipt.json");
        options
            .open(output)
            .unwrap()
            .write_all(safe.to_string().as_bytes())
            .unwrap();
    }
}
