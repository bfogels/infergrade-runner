use infergrade_runner_engine::{build_hub_json_request, hub_api_url, HubMethod};
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
