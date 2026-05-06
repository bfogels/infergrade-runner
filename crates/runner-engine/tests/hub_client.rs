use infergrade_runner_engine::{
    build_hub_json_request, build_run_bundle_upload_request, build_run_completion_request,
    hub_api_url, HubMethod,
};
use serde_json::json;

#[test]
fn hub_api_url_normalizes_and_joins_paths() {
    assert_eq!(
        hub_api_url("api.infergrade.com", "/v1/runner-pairings/redeem").expect("hosted shorthand"),
        "https://api.infergrade.com/v1/runner-pairings/redeem"
    );
    assert_eq!(
        hub_api_url("localhost:8000/", "v1/runners/register").expect("local shorthand"),
        "http://localhost:8000/v1/runners/register"
    );
}

#[test]
fn hub_json_request_keeps_bearer_token_out_of_debug_and_preview() {
    let request = build_hub_json_request(
        HubMethod::Post,
        "api.infergrade.com",
        "/v1/runners/register",
        Some(json!({"runner_id": "runner-local"})),
        Some("qbhr_secret_token"),
    )
    .expect("request");

    assert_eq!(request.method, HubMethod::Post);
    assert_eq!(
        request.url,
        "https://api.infergrade.com/v1/runners/register"
    );
    assert_eq!(
        request.authorization_header().as_deref(),
        Some("Bearer qbhr_secret_token")
    );

    let debug = format!("{request:?}");
    let preview = request.sanitized_preview().to_string();
    assert!(!debug.contains("qbhr_secret_token"));
    assert!(!preview.contains("qbhr_secret_token"));
    assert_eq!(request.sanitized_preview()["has_authorization"], true);
}

#[test]
fn hub_json_request_rejects_invalid_url_with_stable_error_code() {
    let error = hub_api_url("http://api.infergrade.com", "/v1/runners/register")
        .expect_err("cleartext hosted rejected");

    assert_eq!(error.code(), "hub_url_invalid");
    assert!(error.message().contains("HTTPS"));
}

#[test]
fn run_bundle_upload_request_uses_run_scoped_route_and_redacts_token() {
    let payload = json!({
        "manifest": {"bundle_id": "nfr_bundle_1"},
        "results": [{"bundle_id": "nfr_bundle_1", "result_id": "nfr_result_1"}],
        "summary": {"uploaded": false, "native_first_run": true},
    });
    let request = build_run_bundle_upload_request(
        "api.infergrade.com",
        "run_cfg_abc_123",
        payload,
        Some("rtok_secret_for_run"),
    )
    .expect("upload request");

    assert_eq!(request.method, HubMethod::Post);
    assert_eq!(
        request.url,
        "https://api.infergrade.com/v1/runs/run_cfg_abc_123/bundle"
    );
    assert_eq!(
        request.authorization_header().as_deref(),
        Some("Bearer rtok_secret_for_run")
    );
    assert_eq!(request.sanitized_preview()["has_authorization"], true);
    assert_eq!(
        request.sanitized_preview()["payload"]["summary"]["uploaded"],
        false
    );
    let debug = format!("{request:?}");
    let preview = request.sanitized_preview().to_string();
    assert!(!debug.contains("rtok_secret_for_run"));
    assert!(!preview.contains("rtok_secret_for_run"));
}

#[test]
fn run_bundle_upload_request_rejects_path_injection_and_bad_payloads() {
    let payload = json!({"manifest": {}, "results": []});
    let bad_id = build_run_bundle_upload_request(
        "api.infergrade.com",
        "../run-secret",
        payload.clone(),
        Some("rtok_secret_for_run"),
    )
    .expect_err("path injection rejected");
    assert_eq!(bad_id.code(), "hub_path_id_invalid");

    let bad_payload = build_run_bundle_upload_request(
        "api.infergrade.com",
        "run_cfg_abc_123",
        json!({"manifest": {}}),
        Some("rtok_secret_for_run"),
    )
    .expect_err("results array required");
    assert_eq!(bad_payload.code(), "hub_bundle_payload_invalid");
}

#[test]
fn run_completion_request_uses_same_secret_safe_request_boundary() {
    let request = build_run_completion_request(
        "localhost:8000",
        "run_cfg_abc_123",
        "worker-local",
        "nfr_bundle_1",
        Some(json!({"stored": true, "bundle_id": "nfr_bundle_1"})),
        Some("rtok_secret_for_run"),
    )
    .expect("completion request");

    assert_eq!(request.method, HubMethod::Post);
    assert_eq!(
        request.url,
        "http://localhost:8000/v1/runs/run_cfg_abc_123/complete"
    );
    assert_eq!(request.sanitized_preview()["has_authorization"], true);
    assert_eq!(
        request.sanitized_preview()["payload"]["bundle_id"],
        "nfr_bundle_1"
    );
    assert!(!format!("{request:?}").contains("rtok_secret_for_run"));
    assert!(!request
        .sanitized_preview()
        .to_string()
        .contains("rtok_secret_for_run"));
}
