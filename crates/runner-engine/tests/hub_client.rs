use infergrade_runner_engine::{
    build_hub_json_request, build_run_bundle_upload_request, build_run_claim_request,
    build_run_completion_request, execute_hub_json_request, hub_api_url, HubMethod,
};
use serde_json::json;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::sync::mpsc;
use std::thread;

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
fn run_claim_request_uses_runner_session_without_leaking_token() {
    let request = build_run_claim_request(
        "api.infergrade.com",
        "run_cfg_abc_123",
        "runner_local_native_1",
        "local_native",
        Some("qbhr_runner_secret"),
    )
    .expect("claim request");

    assert_eq!(request.method, HubMethod::Post);
    assert_eq!(request.url, "https://api.infergrade.com/v1/runs/claim");
    assert_eq!(
        request.authorization_header().as_deref(),
        Some("Bearer qbhr_runner_secret")
    );
    assert_eq!(
        request.sanitized_preview()["payload"]["run_id"],
        "run_cfg_abc_123"
    );
    assert_eq!(
        request.sanitized_preview()["payload"]["worker_id"],
        "runner_local_native_1"
    );
    assert_eq!(
        request.sanitized_preview()["payload"]["execution_mode"],
        "local_native"
    );
    assert!(!format!("{request:?}").contains("qbhr_runner_secret"));
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

    let whitespace_id = build_run_bundle_upload_request(
        "api.infergrade.com",
        " run_cfg_abc_123 ",
        payload.clone(),
        Some("rtok_secret_for_run"),
    )
    .expect_err("whitespace id rejected");
    assert_eq!(whitespace_id.code(), "hub_path_id_invalid");

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

#[tokio::test]
async fn execute_run_bundle_upload_posts_json_to_hub() {
    let (api_url, received) =
        spawn_json_server(200, r#"{"stored":true,"bundle_id":"nfr_bundle_1"}"#);
    let request = build_run_bundle_upload_request(
        &api_url,
        "run_cfg_abc_123",
        json!({
            "manifest": {"bundle_id": "nfr_bundle_1"},
            "results": [{"bundle_id": "nfr_bundle_1", "result_id": "nfr_result_1"}],
        }),
        Some("rtok_secret_for_run"),
    )
    .expect("upload request");

    let response = execute_hub_json_request(&request)
        .await
        .expect("upload response");

    assert_eq!(response.status, 200);
    assert_eq!(response.body["stored"], true);
    assert_eq!(response.body["bundle_id"], "nfr_bundle_1");
    assert!(!format!("{response:?}").contains("nfr_bundle_1"));
    let raw_request = received.recv().expect("server request");
    assert!(raw_request.starts_with("POST /v1/runs/run_cfg_abc_123/bundle HTTP/1.1"));
    assert!(raw_request.contains("authorization: Bearer rtok_secret_for_run"));
    assert!(raw_request.contains("\"manifest\""));
    assert!(raw_request.contains("\"results\""));
}

#[tokio::test]
async fn execute_hub_json_response_debug_does_not_expose_body_tokens() {
    let (api_url, _received) =
        spawn_json_server(200, r#"{"stored":true,"echo":"rtok_secret_for_run"}"#);
    let request = build_run_bundle_upload_request(
        &api_url,
        "run_cfg_abc_123",
        json!({
            "manifest": {"bundle_id": "nfr_bundle_1"},
            "results": [{"bundle_id": "nfr_bundle_1", "result_id": "nfr_result_1"}],
        }),
        Some("rtok_secret_for_run"),
    )
    .expect("upload request");

    let response = execute_hub_json_request(&request)
        .await
        .expect("upload response");

    assert_eq!(response.body["echo"], "rtok_secret_for_run");
    let debug = format!("{response:?}");
    assert!(!debug.contains("rtok_secret_for_run"));
    assert!(!debug.contains("echo"));
}

#[tokio::test]
async fn execute_run_bundle_upload_redacts_token_from_hub_error() {
    let (api_url, _received) = spawn_json_server(
        403,
        r#"{"detail":{"message":"runner token rtok_secret_for_run cannot upload this run"}}"#,
    );
    let request = build_run_bundle_upload_request(
        &api_url,
        "run_cfg_abc_123",
        json!({
            "manifest": {"bundle_id": "nfr_bundle_1"},
            "results": [{"bundle_id": "nfr_bundle_1", "result_id": "nfr_result_1"}],
        }),
        Some("rtok_secret_for_run"),
    )
    .expect("upload request");

    let error = execute_hub_json_request(&request)
        .await
        .expect_err("Hub rejected upload");

    assert_eq!(error.code(), "hub_request_failed");
    assert!(error.message().contains("HTTP 403"));
    assert!(error.message().contains("[redacted]"));
    assert!(!error.message().contains("rtok_secret_for_run"));
}

#[tokio::test]
async fn execute_hub_json_error_redacts_before_truncating() {
    let echoed = format!(
        "{{\"detail\":{{\"message\":\"{}rtok_secret_for_run\"}}}}",
        "x".repeat(295)
    );
    let body: &'static str = Box::leak(echoed.into_boxed_str());
    let (api_url, _received) = spawn_json_server(403, body);
    let request = build_run_bundle_upload_request(
        &api_url,
        "run_cfg_abc_123",
        json!({
            "manifest": {"bundle_id": "nfr_bundle_1"},
            "results": [{"bundle_id": "nfr_bundle_1", "result_id": "nfr_result_1"}],
        }),
        Some("rtok_secret_for_run"),
    )
    .expect("upload request");

    let error = execute_hub_json_request(&request)
        .await
        .expect_err("Hub rejected upload");

    assert!(!error.message().contains("rtok"));
    assert!(!error.message().contains("rtok_secret_for_run"));
}

fn spawn_json_server(status: u16, body: &'static str) -> (String, mpsc::Receiver<String>) {
    let listener = TcpListener::bind("127.0.0.1:0").expect("bind test server");
    let address = listener.local_addr().expect("server address");
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let (mut stream, _) = listener.accept().expect("accept request");
        let request = read_http_request(&mut stream);
        sender.send(request).expect("send request");
        let reason = if status >= 400 { "Forbidden" } else { "OK" };
        let response = format!(
            "HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        stream
            .write_all(response.as_bytes())
            .expect("write response");
    });
    (format!("http://{address}"), receiver)
}

fn read_http_request(stream: &mut impl Read) -> String {
    let mut bytes = Vec::new();
    let mut buffer = [0_u8; 1024];
    let header_end = loop {
        let bytes_read = stream.read(&mut buffer).expect("read request");
        assert!(bytes_read > 0, "connection closed before headers");
        bytes.extend_from_slice(&buffer[..bytes_read]);
        if let Some(index) = bytes.windows(4).position(|window| window == b"\r\n\r\n") {
            break index + 4;
        }
    };
    let headers = String::from_utf8_lossy(&bytes[..header_end]).to_string();
    let content_length = headers
        .lines()
        .find_map(|line| {
            let (name, value) = line.split_once(':')?;
            name.eq_ignore_ascii_case("content-length")
                .then(|| value.trim().parse::<usize>().ok())
                .flatten()
        })
        .unwrap_or(0);
    while bytes.len().saturating_sub(header_end) < content_length {
        let bytes_read = stream.read(&mut buffer).expect("read body");
        assert!(bytes_read > 0, "connection closed before body");
        bytes.extend_from_slice(&buffer[..bytes_read]);
    }
    String::from_utf8_lossy(&bytes).to_string()
}
