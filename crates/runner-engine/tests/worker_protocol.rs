use infergrade_runner_engine::{
    claim_run_job_payload, desktop_environment, runner_heartbeat_payload, runner_register_payload,
    ClaimRunJobRequest, RunnerHeartbeatRequest, RunnerProtocolPingInput,
    RunnerProtocolPreviewInput, RunnerRegisterRequest,
};
use serde_json::{json, Value};

#[test]
fn typed_register_request_matches_existing_payload_shape() {
    let typed =
        RunnerRegisterRequest::new("runner_123", "local_native", Some("host-a".to_string()));
    let legacy = runner_register_payload("runner_123", "local_native", Some("host-a".to_string()));
    let serialized = serde_json::to_value(&typed).expect("register json");
    let expected = json!({
        "runner_id": "runner_123",
        "execution_modes": ["local_native"],
        "status": "starting",
        "label": "runner_123",
        "runner_kind": "local_listener",
        "hostname": "host-a",
        "provider_id": Value::Null,
        "instance_type_id": Value::Null,
        "capabilities": {
            "run_token_supported": true,
            "auto_upload": true,
        },
        "version": env!("CARGO_PKG_VERSION"),
        "environment": desktop_environment(),
        "contract": {},
        "diagnostics": {},
    });

    assert_eq!(serialized, expected);
    assert_eq!(serialized, legacy);
    assert_eq!(typed.runner_id, "runner_123");
    assert_eq!(typed.execution_modes, vec!["local_native".to_string()]);
    assert_eq!(typed.runner_kind, "local_listener");
}

#[test]
fn typed_heartbeat_request_matches_existing_payload_shape() {
    let typed = RunnerHeartbeatRequest::new(
        "listening",
        None,
        Some("host-a".to_string()),
        Some("Runner is listening for jobs."),
    );
    let legacy = runner_heartbeat_payload(
        "listening",
        None,
        Some("host-a".to_string()),
        Some("Runner is listening for jobs."),
    );
    let serialized = serde_json::to_value(&typed).expect("heartbeat json");
    let expected = json!({
        "status": "listening",
        "current_run_id": Value::Null,
        "hostname": "host-a",
        "provider_id": Value::Null,
        "instance_type_id": Value::Null,
        "metadata": {"message": "Runner is listening for jobs."},
        "environment": desktop_environment(),
        "contract": {},
        "diagnostics": {},
    });

    assert_eq!(serialized, expected);
    assert_eq!(serialized, legacy);
    assert_eq!(
        serialized["metadata"]["message"],
        "Runner is listening for jobs."
    );
    assert_eq!(serialized["current_run_id"], Value::Null);
}

#[test]
fn typed_claim_request_matches_existing_payload_shape_and_stays_secret_free() {
    let typed = ClaimRunJobRequest::new(
        "runner_123",
        "local_native",
        Some("run_1"),
        None,
        Some("host-a".to_string()),
    );
    let legacy = claim_run_job_payload(
        "runner_123",
        "local_native",
        Some("run_1"),
        None,
        Some("host-a".to_string()),
    );
    let serialized = serde_json::to_value(&typed).expect("claim json");
    let expected = json!({
        "worker_id": "runner_123",
        "execution_mode": "local_native",
        "run_id": "run_1",
        "run_config_id": Value::Null,
        "provider_id": Value::Null,
        "instance_type_id": Value::Null,
        "hostname": "host-a",
    });

    assert_eq!(serialized, expected);
    assert_eq!(serialized, legacy);
    let combined = json!({"claim": serialized}).to_string();
    assert!(!combined.contains("qbhr_"));
    assert!(!combined.contains("Authorization"));
}

#[test]
fn worker_protocol_preview_uses_typed_protocol_and_stays_secret_free() {
    let preview = RunnerProtocolPreviewInput {
        api_url: "api.infergrade.com".to_string(),
        runner_id: "runner_123".to_string(),
        execution_mode: "local_native".to_string(),
        hostname: Some("host-a".to_string()),
    }
    .build()
    .expect("preview");
    let serialized = serde_json::to_value(&preview).expect("preview json");

    assert_eq!(serialized["api_url"], "https://api.infergrade.com/");
    assert_eq!(serialized["runner_id"], "runner_123");
    assert_eq!(serialized["execution_mode"], "local_native");
    assert_eq!(serialized["endpoints"]["register"], "/v1/runners/register");
    assert_eq!(
        serialized["endpoints"]["heartbeat"],
        "/v1/runners/runner_123/heartbeat"
    );
    assert_eq!(serialized["endpoints"]["claim"], "/v1/runs/claim");
    assert_eq!(serialized["register"]["runner_id"], "runner_123");
    assert_eq!(
        serialized["register"]["execution_modes"],
        json!(["local_native"])
    );
    assert_eq!(serialized["heartbeat"]["status"], "listening");
    assert_eq!(serialized["claim"]["worker_id"], "runner_123");
    assert_eq!(
        serialized["secret_boundary"],
        "payload preview excludes bearer tokens; Rust attaches authorization only when sending requests"
    );

    let combined = serialized.to_string();
    assert!(!combined.contains("qbhr_"));
    assert!(!combined.contains("Authorization"));
}

#[test]
fn worker_protocol_preview_normalizes_api_url_and_rejects_bad_hub_urls() {
    // api_url tolerates surrounding whitespace via normalize_api_url. The
    // identity fields (runner_id, execution_mode) must be already-trimmed:
    // the validator rejects whitespace explicitly so callers see fast.
    let preview = RunnerProtocolPreviewInput {
        api_url: " localhost:8000 ".to_string(),
        runner_id: "runner_123".to_string(),
        execution_mode: "local_native".to_string(),
        hostname: None,
    }
    .build()
    .expect("preview");

    assert_eq!(preview.api_url, "http://localhost:8000/");
    assert_eq!(preview.runner_id, "runner_123");
    assert_eq!(preview.execution_mode, "local_native");

    let whitespace_runner_id = RunnerProtocolPreviewInput {
        api_url: "api.infergrade.com".to_string(),
        runner_id: " runner_123 ".to_string(),
        execution_mode: "local_native".to_string(),
        hostname: None,
    }
    .build()
    .expect_err("whitespace runner_id rejected");
    assert_eq!(whitespace_runner_id.code(), "runner_id_invalid");

    let whitespace_mode = RunnerProtocolPreviewInput {
        api_url: "api.infergrade.com".to_string(),
        runner_id: "runner_123".to_string(),
        execution_mode: " local_native ".to_string(),
        hostname: None,
    }
    .build()
    .expect_err("whitespace execution_mode rejected");
    assert_eq!(whitespace_mode.code(), "execution_mode_invalid");
    assert_eq!(
        preview.endpoints.heartbeat,
        "/v1/runners/runner_123/heartbeat"
    );
    assert_eq!(preview.register.execution_modes, vec!["local_native"]);
    assert_eq!(preview.claim.execution_mode, "local_native");

    let invalid_url = RunnerProtocolPreviewInput {
        api_url: "http://api.infergrade.com".to_string(),
        runner_id: "runner_123".to_string(),
        execution_mode: "local_native".to_string(),
        hostname: None,
    }
    .build()
    .expect_err("cleartext hosted URL rejected");
    assert_eq!(invalid_url.code(), "hub_url_invalid");
    assert!(invalid_url.message().contains("HTTPS"));

    let missing_runner = RunnerProtocolPreviewInput {
        api_url: "api.infergrade.com".to_string(),
        runner_id: "   ".to_string(),
        execution_mode: "local_native".to_string(),
        hostname: None,
    }
    .build()
    .expect_err("runner id required");
    assert_eq!(missing_runner.code(), "runner_id_invalid");

    let missing_mode = RunnerProtocolPreviewInput {
        api_url: "api.infergrade.com".to_string(),
        runner_id: "runner_123".to_string(),
        execution_mode: "   ".to_string(),
        hostname: None,
    }
    .build()
    .expect_err("execution mode required");
    assert_eq!(missing_mode.code(), "execution_mode_invalid");
}

#[test]
fn worker_protocol_ping_plan_uses_typed_register_and_heartbeat_requests() {
    let plan = RunnerProtocolPingInput {
        api_url: "api.infergrade.com".to_string(),
        runner_id: "runner_123".to_string(),
        execution_mode: "local_native".to_string(),
        hostname: Some("host-a".to_string()),
    }
    .build()
    .expect("ping plan");

    assert_eq!(plan.api_url, "https://api.infergrade.com/");
    assert_eq!(plan.runner_id, "runner_123");
    assert_eq!(plan.execution_mode, "local_native");
    assert_eq!(plan.register_endpoint, "/v1/runners/register");
    assert_eq!(plan.heartbeat_endpoint, "/v1/runners/runner_123/heartbeat");
    assert_eq!(plan.register.runner_id, "runner_123");
    assert_eq!(plan.register.execution_modes, vec!["local_native"]);
    assert_eq!(plan.heartbeat.status, "listening");
    assert_eq!(
        plan.heartbeat.metadata["message"],
        "Runner registered and is listening for jobs."
    );

    let serialized = serde_json::to_value(&plan).expect("ping plan json");
    assert!(!serialized.to_string().contains("qbhr_"));
    assert!(!serialized.to_string().contains("Authorization"));
}

#[test]
fn worker_protocol_preview_rejects_unknown_execution_modes() {
    for bad in [
        "",
        "   ",
        "remote-shell",
        "local_native; rm -rf /",
        "LOCAL_NATIVE",
    ] {
        let error = infergrade_runner_engine::RunnerProtocolPreviewInput {
            api_url: "api.infergrade.com".to_string(),
            runner_id: "runner_123".to_string(),
            execution_mode: bad.to_string(),
            hostname: None,
        }
        .build()
        .expect_err("unknown execution_mode rejected");
        assert_eq!(error.code(), "execution_mode_invalid", "input: {bad}");
    }
}

#[test]
fn worker_protocol_preview_rejects_unsafe_runner_ids_for_path_interpolation() {
    let overlong = "x".repeat(200);
    let bad_inputs: Vec<&str> = vec![
        "../admin",
        "runner/with/slash",
        "runner?query=1",
        "runner#frag",
        "runner with space",
        ".",
        "..",
        overlong.as_str(),
    ];
    for bad in &bad_inputs {
        let error = infergrade_runner_engine::RunnerProtocolPreviewInput {
            api_url: "api.infergrade.com".to_string(),
            runner_id: (*bad).to_string(),
            execution_mode: "local_native".to_string(),
            hostname: None,
        }
        .build()
        .expect_err("unsafe runner_id rejected");
        assert_eq!(error.code(), "runner_id_invalid", "input: {bad}");
    }
}
