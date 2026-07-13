from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RunRequest:
    model: str
    backend: str
    tier: str
    capability_suite_ids: List[str] = field(default_factory=list)
    benchmark_group_ids: List[str] = field(default_factory=list)
    benchmark_check_ids: List[str] = field(default_factory=list)
    benchmark_shortcut_id: Optional[str] = None
    quant_artifact: Optional[str] = None
    quant_artifact_sha256: Optional[str] = None
    quant_artifact_filename: Optional[str] = None
    quant_artifact_revision: Optional[str] = None
    quant_artifact_download_size_bytes: Optional[int] = None
    quant_artifact_resolved_path: Optional[str] = None
    quant_artifact_cache_dir: Optional[str] = None
    backend_image: Optional[str] = None
    llama_cpp_cli_path: Optional[str] = None
    llama_cpp_server_path: Optional[str] = None
    llama_cpp_perplexity_path: Optional[str] = None
    runtime_selector: Dict[str, Any] = field(default_factory=dict)
    ontology_hints: Dict[str, Any] = field(default_factory=dict)
    use_case: Optional[str] = None
    deployment_profiles: List[str] = field(default_factory=list)
    deployment_warmup_runs: Optional[int] = None
    deployment_measured_runs: Optional[int] = None
    execution_mode: str = "local_container"
    output_dir: Optional[str] = None
    resume: bool = False
    upload: bool = False
    backend_flags: List[str] = field(default_factory=list)
    generation_preset: Optional[str] = None
    cloud_provider: Optional[str] = None
    cloud_instance_type: Optional[str] = None
    cost_source: Optional[str] = None
    hourly_rate_usd: Optional[float] = None
    capability: str = "auto"
    submitter: Optional[str] = None
    evidence_source: Optional[str] = None
    notes: Optional[str] = None
    run_config_id: Optional[str] = None
    run_config_name: Optional[str] = None
    run_config_source: Optional[str] = None
    simulate: bool = True


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    verification_level: str = "experimental"
    comparison_grade: str = "informational_only"
    canonical_analysis_eligibility: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "verification_level": self.verification_level,
            "comparison_grade": self.comparison_grade,
            "canonical_analysis_eligibility": self.canonical_analysis_eligibility,
        }


@dataclass
class DeploymentExecution:
    profile_id: str
    metrics: Dict[str, Any]
    status: str
    artifacts: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CapabilityExecution:
    use_case: Optional[str]
    suite_id: Optional[str]
    suite_ids: List[str]
    benchmark_tier: Optional[str]
    benchmark_group_ids: List[str]
    benchmark_check_ids: List[str]
    components: List[str]
    score: Optional[float]
    score_method: Optional[str]
    component_scores: Dict[str, float]
    confidence: Optional[float]
    status: str
    benchmark_results: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    score_details: Dict[str, Any] = field(default_factory=dict)
    task_performance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FidelityExecution:
    state: str
    reason_codes: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    context: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Any] = field(default_factory=dict)
