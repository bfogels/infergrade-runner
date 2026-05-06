use infergrade_runner_engine::{
    claim_run_job_payload, runner_heartbeat_payload, runner_register_payload, ClaimRunJobRequest,
    RunnerHeartbeatRequest, RunnerRegisterRequest,
};
use serde_json::{json, Value};

#[test]
fn typed_register_request_matches_existing_payload_shape() {
    let typed =
        RunnerRegisterRequest::new("runner_123", "local_native", Some("host-a".to_string()));
    let legacy = runner_register_payload("runner_123", "local_native", Some("host-a".to_string()));
    let serialized = serde_json::to_value(&typed).expect("register json");

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

    assert_eq!(serialized, legacy);
    let combined = json!({"claim": serialized}).to_string();
    assert!(!combined.contains("qbhr_"));
    assert!(!combined.contains("Authorization"));
}
