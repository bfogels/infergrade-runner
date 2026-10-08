//! Device secret stays in native memory; renderer receives only the short code.
use super::*;
use std::sync::OnceLock;
use std::time::Instant;

const ISSUE_PATH: &str = "/api/runner/device-codes";
const POLL_PATH: &str = "/api/runner/device-codes/token";

#[derive(Clone)]
struct PendingPairing {
    generation: u64,
    api_url: String,
    device_code: String,
    deadline: Instant,
    next_poll: Instant,
    interval: Duration,
    in_flight: bool,
}

#[derive(Default)]
struct PairingState {
    generation: u64,
    pending: Option<PendingPairing>,
}

static DEVICE_PAIRING: Mutex<PairingState> = Mutex::new(PairingState {
    generation: 0,
    pending: None,
});

pub(super) fn invalidate() -> u64 {
    if let Ok(mut state) = DEVICE_PAIRING.lock() {
        state.generation = state.generation.wrapping_add(1);
        state.pending = None;
        return state.generation;
    }
    u64::MAX
}

pub(super) fn is_current(generation: u64) -> bool {
    DEVICE_PAIRING
        .lock()
        .is_ok_and(|state| state.generation == generation)
}

fn issued_fields(body: &Value) -> Result<(String, String, String, u64, u64), String> {
    let device = body["device_code"].as_str().unwrap_or("");
    let code = body["user_code"].as_str().unwrap_or("");
    let uri = body["verification_uri"].as_str().unwrap_or("");
    let expires = body["expires_in"].as_u64().unwrap_or(0);
    let interval = body["interval"].as_u64().unwrap_or(0);
    let code_valid = code.len() == 9
        && code.as_bytes()[4] == b'-'
        && code.bytes().enumerate().all(|(index, value)| {
            index == 4 || value.is_ascii_uppercase() || (b'2'..=b'9').contains(&value)
        });
    let url = Url::parse(uri).map_err(|_| "Hub returned an invalid connection URL.")?;
    if !(32..=256).contains(&device.len())
        || !device.is_ascii()
        || !code_valid
        || !(1..=600).contains(&expires)
        || !(1..=60).contains(&interval)
        || url.scheme() != "https"
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
        || uri.contains(device)
    {
        return Err("Hub returned an invalid device connection response.".into());
    }
    Ok((device.into(), code.into(), uri.into(), expires, interval))
}

fn device_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .connect_timeout(Duration::from_secs(10))
            .timeout(Duration::from_secs(20))
            // Never forward a device secret to a redirect destination. Polling at
            // five seconds must also not race the Hub's five-second idle timeout.
            .redirect(reqwest::redirect::Policy::none())
            .pool_idle_timeout(Duration::from_secs(4))
            .build()
            .expect("valid device authorization HTTP client")
    })
}

async fn post(api_url: &str, path: &str, payload: Value) -> Result<(u16, Value), String> {
    let request =
        build_hub_json_request(HubMethod::Post, api_url, path, Some(payload.clone()), None)
            .map_err(|_| "The Hub connection URL is invalid.".to_string())?;
    let response = device_client()
        .post(request.url)
        .json(&payload)
        .timeout(Duration::from_secs(20))
        .send()
        .await
        .map_err(|_| "Could not reach Hub. Check your connection and try again.".to_string())?;
    let status = response.status().as_u16();
    if response.content_length().is_some_and(|bytes| bytes > 65536) {
        return Err("Hub returned an invalid connection response.".into());
    }
    let bytes = response
        .bytes()
        .await
        .map_err(|_| "Could not read the Hub connection response.".to_string())?;
    if bytes.len() > 65536 {
        return Err("Hub returned an invalid connection response.".into());
    }
    let body = serde_json::from_slice(&bytes)
        .map_err(|_| "Hub returned an invalid connection response.".to_string())?;
    Ok((status, body))
}

#[tauri::command]
pub(super) async fn begin_runner_device_pairing(
    api_url: String,
    label: Option<String>,
) -> Result<Value, String> {
    let api_url = normalize_api_url(&api_url)?;
    let generation = {
        let _guard = PAIRING_STATE_LOCK.write().await;
        if runner_token_available()? {
            return Err("This machine is already connected. Disconnect it before connecting another account.".into());
        }
        let mut state = DEVICE_PAIRING
            .lock()
            .map_err(|_| "Connection state is unavailable.")?;
        state.generation = state.generation.wrapping_add(1);
        state.pending = None;
        state.generation
    };
    let name = hostname().unwrap_or_else(|| "This computer".into());
    let label = label
        .unwrap_or_default()
        .trim()
        .chars()
        .take(120)
        .collect::<String>();
    let (status, body) = post(&api_url, ISSUE_PATH, json!({
        "hostname": name, "label": label, "preferred_execution_mode": preferred_execution_mode(),
        "environment": desktop_environment(),
    })).await?;
    if status != 200 && status != 201 {
        return Err(if status == 404 || status == 501 {
            "This Hub does not support browser connection yet. Use the one-time-code option below."
                .into()
        } else {
            "Hub could not start this connection. Try again shortly.".into()
        });
    }
    let (device, code, uri, expires, interval) = issued_fields(&body)?;
    let _guard = PAIRING_STATE_LOCK.write().await;
    let mut state = DEVICE_PAIRING
        .lock()
        .map_err(|_| "Connection state is unavailable.")?;
    if state.generation != generation {
        return Err("This connection was canceled.".into());
    }
    let now = Instant::now();
    state.pending = Some(PendingPairing {
        generation,
        api_url,
        device_code: device,
        deadline: now + Duration::from_secs(expires),
        next_poll: now + Duration::from_secs(interval),
        interval: Duration::from_secs(interval),
        in_flight: false,
    });
    Ok(
        json!({"session_id": generation.to_string(), "user_code": code, "verification_uri": uri,
              "expires_in": expires, "interval": interval}),
    )
}

#[tauri::command]
pub(super) async fn cancel_runner_device_pairing() -> Result<(), String> {
    let _guard = PAIRING_STATE_LOCK.write().await;
    invalidate();
    Ok(())
}

#[tauri::command]
pub(super) async fn poll_runner_device_pairing(session_id: String) -> Result<Value, String> {
    let pending = {
        let mut state = DEVICE_PAIRING
            .lock()
            .map_err(|_| "Connection state is unavailable.")?;
        let Some(pending) = state
            .pending
            .as_mut()
            .filter(|pending| pending.generation.to_string() == session_id)
        else {
            return Ok(json!({"status": "canceled"}));
        };
        if Instant::now() >= pending.deadline {
            state.pending = None;
            return Ok(json!({"status": "expired"}));
        }
        if pending.in_flight || Instant::now() < pending.next_poll {
            return Ok(json!({"status": "pending", "interval": pending.interval.as_secs()}));
        }
        pending.in_flight = true;
        pending.clone()
    };
    let response = post(
        &pending.api_url,
        POLL_PATH,
        json!({"device_code": pending.device_code}),
    )
    .await;
    let _guard = PAIRING_STATE_LOCK.write().await;
    let mut state = DEVICE_PAIRING
        .lock()
        .map_err(|_| "Connection state is unavailable.")?;
    let current = state
        .pending
        .as_mut()
        .filter(|item| item.generation == pending.generation)
        .ok_or("This connection was canceled. Start again.")?;
    current.in_flight = false;
    if Instant::now() >= current.deadline {
        state.pending = None;
        return Ok(json!({"status": "expired"}));
    }
    current.next_poll = Instant::now() + current.interval;
    let (status, body) = response?;
    if status == 200 {
        // Credential persistence is synchronous under the same lock as cancel,
        // reset and legacy pairing. A late response cannot overwrite a new pair.
        state.pending = None;
        let completion = complete_pairing_response(
            body,
            &DesktopProfileStore,
            &DesktopTokenStore,
            runner_profile_path()?.display().to_string(),
        )
        .map_err(|error| error.message().to_string())?;
        return Ok(json!({"status": "paired", "pairing": completion.ui_response}));
    }
    match body["error"].as_str() {
        Some("authorization_pending") => {
            Ok(json!({"status": "pending", "interval": current.interval.as_secs()}))
        }
        Some("slow_down") => {
            current.interval =
                (current.interval + Duration::from_secs(5)).min(Duration::from_secs(60));
            current.next_poll = Instant::now() + current.interval;
            Ok(json!({"status": "pending", "interval": current.interval.as_secs()}))
        }
        Some("access_denied") => {
            state.pending = None;
            Ok(json!({"status": "denied"}))
        }
        Some("expired_token" | "invalid_grant") => {
            state.pending = None;
            Ok(json!({"status": "expired"}))
        }
        _ => {
            Err("Hub could not finish this connection. Check your connection and try again.".into())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    #[ignore = "requires an isolated, loopback Hub with dev auth and no fixture seeding"]
    async fn actual_hub_issue_pending_approve_redeem_protocol() {
        use infergrade_runner_engine::{MemoryProfileStore, MemoryTokenStore};
        let api = env::var("INFERGRADE_DEVICE_PAIRING_PROTOCOL_TEST_API_URL")
            .expect("isolated Hub URL required");
        let url = Url::parse(&api).unwrap();
        assert_eq!(url.scheme(), "http");
        assert_eq!(url.host_str(), Some("127.0.0.1"));
        let (status, body) = post(&api, ISSUE_PATH, json!({"hostname": hostname().unwrap_or_else(|| "Native protocol check".into()),
            "label": "Native HTTP protocol acceptance", "preferred_execution_mode": preferred_execution_mode(),
            "environment": desktop_environment()})).await.unwrap();
        assert_eq!(status, 200);
        let (device, code, _, _, _) = issued_fields(&body).unwrap();
        let (status, pending) = post(&api, POLL_PATH, json!({"device_code": device}))
            .await
            .unwrap();
        assert_eq!(status, 400);
        assert_eq!(pending["error"], "authorization_pending");
        let client = infergrade_runner_engine::shared_hub_client();
        let session = client
            .post(format!("{api}/auth/dev/session"))
            .json(&json!({"handle": "redesign_native_protocol"}))
            .send()
            .await
            .unwrap();
        assert!(session.status().is_success());
        let cookie = session
            .headers()
            .get(reqwest::header::SET_COOKIE)
            .unwrap()
            .to_str()
            .unwrap()
            .split(';')
            .next()
            .unwrap()
            .to_string();
        let approval = client
            .post(format!("{api}/api/runner/device-codes/approve"))
            .header(reqwest::header::COOKIE, cookie)
            .json(&json!({"user_code": code, "approve": true}))
            .send()
            .await
            .unwrap();
        assert!(approval.status().is_success());
        // The protocol interval applies to the actual server too.
        tokio::time::sleep(Duration::from_secs(5)).await;
        let (status, body) = post(&api, POLL_PATH, json!({"device_code": device}))
            .await
            .unwrap();
        assert_eq!(status, 200);
        let tokens = MemoryTokenStore::default();
        let profiles = MemoryProfileStore::default();
        let completion =
            complete_pairing_response(body, &profiles, &tokens, "in-memory-protocol-only").unwrap();
        let token = tokens.load_runner_token().unwrap().unwrap();
        assert!(!completion.ui_response.to_string().contains(&token));
        assert!(profiles.load_profile().unwrap().is_some());
        assert!(completion.ui_response["runner_profile"]
            .get("access_token")
            .is_none());
        let (status, consumed) = post(&api, POLL_PATH, json!({"device_code": device}))
            .await
            .unwrap();
        assert_eq!(status, 400);
        assert_eq!(consumed["error"], "invalid_grant");
    }

    #[test]
    fn cancel_invalidates_old_generation_and_drops_secret() {
        let now = Instant::now();
        let old_generation = {
            let mut state = DEVICE_PAIRING.lock().unwrap();
            state.generation += 1;
            let generation = state.generation;
            state.pending = Some(PendingPairing {
                generation,
                api_url: "https://api.infergrade.com".into(),
                device_code: "native-only-test-secret".into(),
                deadline: now + Duration::from_secs(600),
                next_poll: now,
                interval: Duration::from_secs(5),
                in_flight: true,
            });
            generation
        };
        let next_generation = invalidate();
        assert_ne!(old_generation, next_generation);
        assert!(!is_current(old_generation));
        assert!(DEVICE_PAIRING.lock().unwrap().pending.is_none());
    }

    #[test]
    fn issue_response_requires_short_code_and_https_without_device_secret() {
        let valid = json!({"device_code": "a".repeat(40), "user_code": "ABCD-2345", "verification_uri": "https://infergrade.com/connect?code=ABCD-2345", "expires_in": 600, "interval": 5});
        assert!(issued_fields(&valid).is_ok());
        for (key, value) in [
            ("user_code", json!("secret")),
            ("interval", json!(0)),
            ("expires_in", json!(601)),
            ("verification_uri", json!("http://infergrade.com/connect")),
            (
                "verification_uri",
                json!(format!(
                    "https://infergrade.com/connect?token={}",
                    "a".repeat(40)
                )),
            ),
        ] {
            let mut changed = valid.clone();
            changed[key] = value;
            assert!(issued_fields(&changed).is_err());
        }
    }
}
