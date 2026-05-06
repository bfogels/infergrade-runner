use crate::{ProfileStore, RunnerError, RunnerProfile, TokenStore};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PairingInput {
    pub pair_code: String,
    pub label: Option<String>,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct PairingRedeemRequest {
    pub pair_code: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hostname: Option<String>,
    pub preferred_execution_mode: String,
    pub environment: Value,
}

#[derive(Clone, Debug, PartialEq)]
pub struct PairingCompletion {
    pub profile: RunnerProfile,
    pub ui_response: Value,
}

pub fn build_pairing_redeem_request(
    input: PairingInput,
    hostname: Option<String>,
    preferred_execution_mode: &str,
    environment: Value,
) -> Result<PairingRedeemRequest, RunnerError> {
    let pair_code = input.pair_code.trim().to_string();
    if pair_code.is_empty() {
        return Err(RunnerError::new(
            "pair_code_missing",
            "Paste the one-time pairing code from the Hub first.",
        ));
    }
    let label = input
        .label
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty());
    Ok(PairingRedeemRequest {
        pair_code,
        label,
        hostname,
        preferred_execution_mode: preferred_execution_mode.to_string(),
        environment,
    })
}

pub fn complete_pairing_response<P, T>(
    mut body: Value,
    profile_store: &P,
    token_store: &T,
    profile_path: impl Into<String>,
) -> Result<PairingCompletion, RunnerError>
where
    P: ProfileStore,
    T: TokenStore,
{
    let profile_value = body.get("runner_profile").cloned().ok_or_else(|| {
        RunnerError::new(
            "pairing_profile_missing",
            "Hub pairing response did not include a runner profile.",
        )
    })?;
    let profile = serde_json::from_value::<RunnerProfile>(profile_value).map_err(|error| {
        RunnerError::new(
            "pairing_profile_invalid",
            format!("Hub pairing response included an invalid runner profile: {error}"),
        )
    })?;
    let access_token = profile
        .access_token
        .as_deref()
        .map(str::trim)
        .filter(|token| !token.is_empty())
        .ok_or_else(|| {
            RunnerError::new(
                "pairing_token_missing",
                "Hub pairing response did not include a runner token.",
            )
        })?;

    profile_store.save_profile(&profile)?;
    token_store.save_runner_token(access_token)?;

    body["runner_profile"] = serde_json::to_value(profile.sanitized()).map_err(|error| {
        RunnerError::new(
            "pairing_profile_sanitize_failed",
            format!("Could not sanitize runner profile: {error}"),
        )
    })?;
    body["profile_path"] = Value::String(profile_path.into());
    body["next_action"] = Value::String("start_runner".to_string());
    body["commands"] = json!({ "start": "infergrade start" });

    Ok(PairingCompletion {
        profile,
        ui_response: body,
    })
}
