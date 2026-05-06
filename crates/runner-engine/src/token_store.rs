use crate::errors::RunnerError;
use std::sync::Mutex;

pub trait TokenStore {
    fn save_runner_token(&self, token: &str) -> Result<(), RunnerError>;
    fn load_runner_token(&self) -> Result<Option<String>, RunnerError>;
    fn clear_runner_token(&self) -> Result<bool, RunnerError>;
}

#[derive(Default)]
pub struct MemoryTokenStore {
    token: Mutex<Option<String>>,
}

impl TokenStore for MemoryTokenStore {
    fn save_runner_token(&self, token: &str) -> Result<(), RunnerError> {
        let token = token.trim();
        if token.is_empty() {
            return Err(RunnerError::new(
                "token_empty",
                "runner token cannot be empty",
            ));
        }
        *self.token.lock().map_err(|_| {
            RunnerError::new("token_store_unavailable", "token store lock failed")
        })? = Some(token.to_string());
        Ok(())
    }

    fn load_runner_token(&self) -> Result<Option<String>, RunnerError> {
        Ok(self
            .token
            .lock()
            .map_err(|_| RunnerError::new("token_store_unavailable", "token store lock failed"))?
            .clone())
    }

    fn clear_runner_token(&self) -> Result<bool, RunnerError> {
        let mut token = self
            .token
            .lock()
            .map_err(|_| RunnerError::new("token_store_unavailable", "token store lock failed"))?;
        let removed = token.is_some();
        *token = None;
        Ok(removed)
    }
}
