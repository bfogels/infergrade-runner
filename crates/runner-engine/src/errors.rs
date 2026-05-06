use std::error::Error;
use std::fmt;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RunnerError {
    code: String,
    message: String,
}

impl RunnerError {
    pub fn new(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }

    pub fn code(&self) -> &str {
        &self.code
    }

    pub fn message(&self) -> &str {
        &self.message
    }
}

impl fmt::Display for RunnerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {}", self.code, self.message)
    }
}

impl Error for RunnerError {}

impl From<String> for RunnerError {
    fn from(message: String) -> Self {
        Self::new("runner_error", message)
    }
}

impl From<&str> for RunnerError {
    fn from(message: &str) -> Self {
        Self::new("runner_error", message)
    }
}
