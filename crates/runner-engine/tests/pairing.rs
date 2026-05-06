use infergrade_runner_engine::{
    build_pairing_redeem_request, complete_pairing_response, MemoryProfileStore, MemoryTokenStore,
    PairingInput, ProfileStore, TokenStore,
};
use serde_json::{json, Value};

#[test]
fn pairing_request_trims_input_and_keeps_runtime_context_in_engine() {
    let request = build_pairing_redeem_request(
        PairingInput {
            pair_code: "  igrp_abc123  ".to_string(),
            label: Some("  Brian's MacBook  ".to_string()),
        },
        Some("host-a".to_string()),
        "local_native",
        json!({"source": "desktop_rust_supervisor"}),
    )
    .expect("pairing request");

    assert_eq!(request.pair_code, "igrp_abc123");
    assert_eq!(request.label.as_deref(), Some("Brian's MacBook"));
    assert_eq!(request.hostname.as_deref(), Some("host-a"));
    assert_eq!(request.preferred_execution_mode, "local_native");
}

#[test]
fn pairing_request_rejects_missing_pair_code_before_frontend_sends_http() {
    let error = build_pairing_redeem_request(
        PairingInput {
            pair_code: "   ".to_string(),
            label: None,
        },
        None,
        "local_native",
        Value::Null,
    )
    .expect_err("empty pair code rejected");

    assert_eq!(error.code(), "pair_code_missing");
}

#[test]
fn pairing_completion_saves_profile_and_token_without_returning_secret_to_ui() {
    let profiles = MemoryProfileStore::default();
    let tokens = MemoryTokenStore::default();
    let body = json!({
        "runner_profile": {
            "api_url": "https://api.infergrade.com/",
            "access_token": "qbhr_secret",
            "runner_id": "runner_123",
            "label": "Brian's MacBook",
            "preferred_execution_mode": "local_native"
        },
        "extra": "kept"
    });

    let completion = complete_pairing_response(
        body,
        &profiles,
        &tokens,
        "/tmp/infergrade/runner_profile.json",
    )
    .expect("pairing completion");

    assert_eq!(
        tokens.load_runner_token().unwrap(),
        Some("qbhr_secret".to_string())
    );
    assert_eq!(
        profiles.load_profile().unwrap().unwrap().runner_id,
        "runner_123"
    );
    assert_eq!(
        completion.ui_response["runner_profile"]["runner_id"],
        "runner_123"
    );
    assert_eq!(
        completion.ui_response["runner_profile"]["has_access_token"],
        true
    );
    assert_eq!(completion.ui_response["extra"], "kept");
    assert_eq!(completion.ui_response["next_action"], "start_runner");
    assert!(!completion.ui_response.to_string().contains("qbhr_secret"));
}

#[test]
fn pairing_completion_rejects_profile_without_token() {
    let profiles = MemoryProfileStore::default();
    let tokens = MemoryTokenStore::default();
    let body = json!({
        "runner_profile": {
            "api_url": "https://api.infergrade.com/",
            "runner_id": "runner_123"
        }
    });

    let error = complete_pairing_response(body, &profiles, &tokens, "/tmp/profile.json")
        .expect_err("token required");

    assert_eq!(error.code(), "pairing_token_missing");
    assert!(profiles.load_profile().unwrap().is_none());
    assert!(tokens.load_runner_token().unwrap().is_none());
}
