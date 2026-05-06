use crate::errors::RunnerError;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fmt;
use std::sync::Mutex;

#[derive(Clone, Deserialize, PartialEq, Serialize)]
pub struct RunnerProfile {
    pub api_url: String,
    #[serde(default, skip_serializing)]
    pub access_token: Option<String>,
    pub runner_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub label: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub preferred_execution_mode: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub paired_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub expires_at: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user: Option<Value>,
}

impl RunnerProfile {
    fn has_access_token(&self) -> bool {
        self.access_token
            .as_ref()
            .map(|token| !token.trim().is_empty())
            .unwrap_or(false)
    }

    pub fn sanitized(&self) -> SanitizedRunnerProfile {
        SanitizedRunnerProfile {
            api_url: self.api_url.clone(),
            runner_id: self.runner_id.clone(),
            label: self.label.clone().unwrap_or_default(),
            preferred_execution_mode: self.preferred_execution_mode.clone().unwrap_or_default(),
            paired_at: self.paired_at.clone().unwrap_or_default(),
            expires_at: self.expires_at.clone().unwrap_or_default(),
            user: self.user.clone().unwrap_or(Value::Null),
            has_access_token: self.has_access_token(),
        }
    }
}

impl fmt::Debug for RunnerProfile {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RunnerProfile")
            .field("api_url", &self.api_url)
            .field("has_access_token", &self.has_access_token())
            .field("runner_id", &self.runner_id)
            .field("label", &self.label)
            .field("preferred_execution_mode", &self.preferred_execution_mode)
            .field("paired_at", &self.paired_at)
            .field("expires_at", &self.expires_at)
            .field("user", &self.user)
            .finish()
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct SanitizedRunnerProfile {
    pub api_url: String,
    pub runner_id: String,
    pub label: String,
    pub preferred_execution_mode: String,
    pub paired_at: String,
    pub expires_at: String,
    pub user: Value,
    pub has_access_token: bool,
}

pub trait ProfileStore {
    fn save_profile(&self, profile: &RunnerProfile) -> Result<(), RunnerError>;
    fn load_profile(&self) -> Result<Option<RunnerProfile>, RunnerError>;
    fn clear_profile(&self) -> Result<(), RunnerError>;
}

#[derive(Default)]
pub struct MemoryProfileStore {
    profile: Mutex<Option<RunnerProfile>>,
}

impl ProfileStore for MemoryProfileStore {
    fn save_profile(&self, profile: &RunnerProfile) -> Result<(), RunnerError> {
        *self.profile.lock().map_err(|_| {
            RunnerError::new("profile_store_unavailable", "profile store lock failed")
        })? = Some(profile.clone());
        Ok(())
    }

    fn load_profile(&self) -> Result<Option<RunnerProfile>, RunnerError> {
        Ok(self
            .profile
            .lock()
            .map_err(|_| {
                RunnerError::new("profile_store_unavailable", "profile store lock failed")
            })?
            .clone())
    }

    fn clear_profile(&self) -> Result<(), RunnerError> {
        *self.profile.lock().map_err(|_| {
            RunnerError::new("profile_store_unavailable", "profile store lock failed")
        })? = None;
        Ok(())
    }
}
