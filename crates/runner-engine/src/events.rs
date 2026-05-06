use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum RunnerEvent {
    PairingStarted,
    PairingSucceeded {
        runner_id: String,
    },
    PairingFailed {
        code: String,
        message: String,
    },
    ReadinessStarted,
    RuntimeDetected {
        runtime: RuntimeInfo,
    },
    ContainerRuntimeDetected {
        provider: String,
        available: bool,
    },
    BenchmarkStarted {
        benchmark_id: String,
    },
    BenchmarkProgress {
        benchmark_id: String,
        message: String,
        progress_percent: Option<f32>,
    },
    BenchmarkCompleted {
        benchmark_id: String,
    },
    UploadStarted,
    UploadSucceeded {
        bundle_id: String,
    },
    Error {
        code: String,
        message: String,
    },
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct RuntimeInfo {
    pub runtime: String,
    pub accelerator: String,
    pub available: bool,
    pub version: Option<String>,
}
