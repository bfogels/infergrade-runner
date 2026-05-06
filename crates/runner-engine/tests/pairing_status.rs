use infergrade_runner_engine::{
    pairing_status_payload, reset_pairing_state, MemoryProfileStore, MemoryTokenStore,
    ProfileStore, RunnerProfile, TokenStore,
};

fn profile() -> RunnerProfile {
    RunnerProfile {
        api_url: "https://api.infergrade.com/".to_string(),
        access_token: None,
        runner_id: "runner_123".to_string(),
        label: Some("Test Runner".to_string()),
        preferred_execution_mode: Some("local_native".to_string()),
        paired_at: None,
        expires_at: None,
        user: None,
    }
}

#[test]
fn pairing_status_requires_profile_and_token() {
    let path = "/tmp/infergrade/runner_profile.json";

    let missing = pairing_status_payload(None, false, path).expect("status");
    assert_eq!(missing["paired"], false);
    assert_eq!(missing["profile"]["status"], "missing");
    assert_eq!(missing["token"]["status"], "missing");

    let stale_profile = pairing_status_payload(Some(profile()), false, path).expect("status");
    assert_eq!(stale_profile["paired"], false);
    assert_eq!(stale_profile["profile"]["status"], "present");
    assert_eq!(stale_profile["token"]["status"], "missing");

    let ready = pairing_status_payload(Some(profile()), true, path).expect("status");
    assert_eq!(ready["paired"], true);
    assert_eq!(ready["profile"]["profile"]["runner_id"], "runner_123");
    assert!(!ready.to_string().contains("qbhr_"));

    let mut legacy_profile = profile();
    legacy_profile.access_token = Some("qbhr_legacy_secret".to_string());
    let legacy_ready = pairing_status_payload(Some(legacy_profile), true, path).expect("status");
    assert_eq!(legacy_ready["paired"], true);
    assert_eq!(legacy_ready["profile"]["profile"]["has_access_token"], true);
    assert!(!legacy_ready.to_string().contains("qbhr_legacy_secret"));
}

#[test]
fn reset_pairing_clears_profile_and_token_through_store_traits() {
    let profiles = MemoryProfileStore::default();
    let tokens = MemoryTokenStore::default();
    profiles.save_profile(&profile()).unwrap();
    tokens.save_runner_token("qbhr_secret").unwrap();

    let result = reset_pairing_state(&profiles, &tokens, "/tmp/infergrade/runner_profile.json")
        .expect("reset");

    assert_eq!(result["reset"], true);
    assert_eq!(result["token_cleared"], true);
    assert_eq!(
        result["profile"]["profile_path"],
        "/tmp/infergrade/runner_profile.json"
    );
    assert!(profiles.load_profile().unwrap().is_none());
    assert!(tokens.load_runner_token().unwrap().is_none());
    assert!(!result.to_string().contains("qbhr_secret"));

    let second = reset_pairing_state(&profiles, &tokens, "/tmp/infergrade/runner_profile.json")
        .expect("idempotent reset");
    assert_eq!(second["reset"], true);
    assert_eq!(second["token_cleared"], false);
    assert_eq!(second["profile"]["removed"], false);
}
