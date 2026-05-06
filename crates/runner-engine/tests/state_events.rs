use infergrade_runner_engine::{
    MemoryProfileStore, MemoryTokenStore, ProfileStore, RunnerError, RunnerEvent, RunnerProfile,
    TokenStore,
};

#[test]
fn typed_runner_profile_sanitizes_token_before_ui_use() {
    let profile = RunnerProfile {
        api_url: "https://api.infergrade.com/".to_string(),
        access_token: Some("qbhr_secret".to_string()),
        runner_id: "runner_123".to_string(),
        label: Some("Test Runner".to_string()),
        preferred_execution_mode: Some("local_native".to_string()),
        paired_at: Some("2026-05-06T00:00:00Z".to_string()),
        expires_at: None,
        user: None,
    };

    let sanitized = profile.sanitized();

    assert_eq!(sanitized.runner_id, "runner_123");
    assert_eq!(sanitized.has_access_token, true);
    assert!(!serde_json::to_string(&sanitized)
        .unwrap()
        .contains("qbhr_secret"));
}

#[test]
fn token_and_profile_store_traits_define_frontend_storage_boundary() {
    let tokens = MemoryTokenStore::default();
    let profiles = MemoryProfileStore::default();
    let profile = RunnerProfile {
        api_url: "https://api.infergrade.com/".to_string(),
        access_token: None,
        runner_id: "runner_123".to_string(),
        label: None,
        preferred_execution_mode: Some("local_native".to_string()),
        paired_at: None,
        expires_at: None,
        user: None,
    };

    tokens.save_runner_token("qbhr_secret").unwrap();
    profiles.save_profile(&profile).unwrap();

    assert_eq!(
        tokens.load_runner_token().unwrap(),
        Some("qbhr_secret".to_string())
    );
    assert_eq!(
        profiles.load_profile().unwrap().unwrap().runner_id,
        "runner_123"
    );

    tokens.clear_runner_token().unwrap();
    profiles.clear_profile().unwrap();

    assert_eq!(tokens.load_runner_token().unwrap(), None);
    assert!(profiles.load_profile().unwrap().is_none());
}

#[test]
fn runner_events_are_typed_and_safe_for_cli_or_desktop_rendering() {
    let event = RunnerEvent::PairingSucceeded {
        runner_id: "runner_123".to_string(),
    };
    let payload = serde_json::to_value(event).unwrap();

    assert_eq!(payload["type"], "pairing_succeeded");
    assert_eq!(payload["runner_id"], "runner_123");
    assert!(!payload.to_string().contains("qbhr_"));
}

#[test]
fn runner_error_has_stable_code_and_message() {
    let error = RunnerError::new("profile_missing", "Pair this machine before starting.");

    assert_eq!(error.code(), "profile_missing");
    assert_eq!(
        error.to_string(),
        "profile_missing: Pair this machine before starting."
    );
}
