from typing import Callable, Dict, List, Optional

from infergrade.benchmark_catalog import capability_benchmark_ids_for_request, selection_metadata_for_request
from infergrade.capabilities import execute_capability_suite
from infergrade.models import CapabilityExecution, DeploymentExecution, FidelityExecution, RunRequest
from infergrade.utils import stable_hash, utcnow_iso


class BaseAdapter(object):
    backend_name = "base"

    def default_backend_flags(self) -> List[str]:
        return []

    def runtime_metadata(self, request: RunRequest) -> Dict[str, object]:
        return {}

    def resolve_version(self, simulate: bool = True, request: RunRequest = None) -> str:
        if simulate:
            return "simulated-%s" % self.backend_name.replace(".", "-")
        raise NotImplementedError("Real backend execution is not implemented yet.")

    def preflight_model(self, request: RunRequest) -> None:
        """Fail before benchmark execution when a runtime cannot load the model.

        Backends that can cheaply and definitively probe model compatibility may
        override this hook. The default remains a no-op so existing adapters do
        not gain an implied compatibility claim.
        """
        return None

    def run_deployment_profile(
        self,
        request: RunRequest,
        profile_id: str,
        progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> DeploymentExecution:
        if not request.simulate:
            raise NotImplementedError("Real backend execution is not implemented yet.")
        metrics = self._simulate_metrics(request, profile_id)
        metrics["warmup_runs"] = (
            request.deployment_warmup_runs
            if request.deployment_warmup_runs is not None
            else (1 if request.tier == "canary" else 2)
        )
        metrics["measured_runs"] = (
            request.deployment_measured_runs
            if request.deployment_measured_runs is not None
            else (1 if request.tier == "canary" else 5)
        )
        return DeploymentExecution(
            profile_id=profile_id,
            metrics=metrics,
            status="simulated",
            artifacts={},
        )

    def run_capability(
        self,
        request: RunRequest,
        progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> CapabilityExecution:
        if request.capability == "none" or not request.use_case:
            return CapabilityExecution(
                use_case=request.use_case,
                suite_id=None,
                suite_ids=[],
                benchmark_tier=request.tier,
                benchmark_group_ids=[],
                benchmark_check_ids=[],
                components=[],
                score=None,
                score_method=None,
                component_scores={},
                confidence=None,
                status="skipped",
                benchmark_results={},
                artifacts={},
            )
        selection = selection_metadata_for_request(request)
        capability_benchmark_ids = capability_benchmark_ids_for_request(request)
        suite_ids = list(selection.get("capability_suite_ids") or [])
        primary_suite_id = suite_ids[0] if suite_ids else None
        if not request.simulate:
            try:
                return execute_capability_suite(self, request, progress_callback=progress_callback)
            except Exception as exc:
                return CapabilityExecution(
                    use_case=request.use_case,
                    suite_id=primary_suite_id,
                    suite_ids=suite_ids,
                    benchmark_tier=request.tier,
                    benchmark_group_ids=list(selection.get("benchmark_group_ids") or []),
                    benchmark_check_ids=capability_benchmark_ids,
                    components=[item.get("display_name") for item in list(selection.get("benchmark_checks") or []) if item.get("evidence_kind") == "capability"],
                    score=None,
                    score_method=None,
                    component_scores={},
                    confidence=0.0,
                    status="failed",
                    benchmark_results={"error": {"message": str(exc)}},
                    artifacts={},
                )
        raw = self._simulate_capability(request, capability_benchmark_ids)
        return CapabilityExecution(
            use_case=request.use_case,
            suite_id=primary_suite_id,
            suite_ids=suite_ids,
            benchmark_tier=request.tier,
            benchmark_group_ids=list(selection.get("benchmark_group_ids") or []),
            benchmark_check_ids=capability_benchmark_ids,
            components=[item.get("display_name") for item in list(selection.get("benchmark_checks") or []) if item.get("evidence_kind") == "capability"],
            score=raw["capability_score"],
            score_method="weighted_normalized_sum_v1",
            component_scores=raw["component_scores"],
            confidence=raw["capability_confidence"],
            status="simulated",
            benchmark_results={},
            artifacts={},
        )

    def generate_text(
        self,
        request: RunRequest,
        prompt: str,
        max_tokens: int,
    ) -> Dict[str, object]:
        if not request.simulate:
            raise NotImplementedError("Real text generation is not implemented for backend %s." % self.backend_name)
        seed = stable_hash(
            {
                "backend": self.backend_name,
                "model": request.model,
                "prompt": prompt[:160],
                "max_tokens": max_tokens,
            },
            length=16,
        )
        text = "Simulated response %s" % seed[:8]
        return {
            "text": text,
            "status": "completed",
            "error": None,
        }

    def run_fidelity(self, request: RunRequest) -> FidelityExecution:
        if request.simulate:
            return FidelityExecution(
                state="not_yet_measured",
                reason_codes=["simulated_run_skips_fidelity"],
            )
        return FidelityExecution(
            state="not_yet_measured",
            reason_codes=["backend_fidelity_not_implemented"],
        )

    def _simulate_metrics(self, request: RunRequest, profile_id: str) -> Dict[str, float]:
        seed = stable_hash(
            {
                "model": request.model,
                "backend": request.backend,
                "profile": profile_id,
                "tier": request.tier,
                "quant": request.quant_artifact,
            },
            length=16,
        )
        number = int(seed[:8], 16)

        def scale(start, end, divisor, precision=2):
            raw = start + (number % divisor) / float(divisor) * (end - start)
            return round(raw, precision)

        if profile_id == "interactive_chat_v1":
            return {
                "ttft_p50_ms": scale(180, 420, 997),
                "ttft_p95_ms": scale(220, 520, 991),
                "latency_p50_ms": scale(900, 1800, 983),
                "latency_p95_ms": scale(1100, 2200, 977),
                "decode_tokens_per_second_p50": scale(30, 110, 971),
                "decode_tokens_per_second_p95": scale(25, 100, 967),
                "request_throughput_per_minute": scale(18, 70, 953),
                "peak_vram_mb": scale(5000, 18000, 947),
                "load_time_ms": scale(1500, 9000, 941),
                "oom_or_failure_rate": 0.0,
                "deployment_confidence": 0.65,
                "generated_at": utcnow_iso(),
            }
        if profile_id == "batch_generation_v1":
            return {
                "ttft_p50_ms": scale(250, 750, 937),
                "ttft_p95_ms": scale(350, 900, 929),
                "latency_p50_ms": scale(1300, 2800, 919),
                "latency_p95_ms": scale(1600, 3200, 911),
                "decode_tokens_per_second_p50": scale(60, 260, 907),
                "decode_tokens_per_second_p95": scale(55, 220, 887),
                "request_throughput_per_minute": scale(40, 180, 883),
                "peak_vram_mb": scale(6000, 20000, 877),
                "load_time_ms": scale(2000, 10000, 863),
                "oom_or_failure_rate": 0.0,
                "deployment_confidence": 0.6,
                "generated_at": utcnow_iso(),
            }
        return {
            "ttft_p50_ms": scale(350, 1200, 859),
            "ttft_p95_ms": scale(450, 1400, 853),
            "latency_p50_ms": scale(1800, 4200, 839),
            "latency_p95_ms": scale(2200, 4800, 829),
            "decode_tokens_per_second_p50": scale(18, 70, 827),
            "decode_tokens_per_second_p95": scale(15, 60, 821),
            "request_throughput_per_minute": scale(10, 40, 811),
            "peak_vram_mb": scale(9000, 23000, 809),
            "load_time_ms": scale(2500, 11000, 797),
            "oom_or_failure_rate": 0.01,
            "deployment_confidence": 0.55,
            "generated_at": utcnow_iso(),
        }

    def _simulate_capability(self, request: RunRequest, components: List[str]) -> Dict[str, object]:
        seed = stable_hash(
            {
                "model": request.model,
                "backend": request.backend,
                "tier": request.tier,
                "use_case": request.use_case,
            },
            length=16,
        )
        number = int(seed[:8], 16)
        base = 0.45 + (number % 400) / 1000.0
        component_scores = {}
        for index, component in enumerate(components):
            component_scores[component] = round(min(0.95, base + (index * 0.03)), 3)
        score = round(sum(component_scores.values()) / float(len(component_scores)), 3) if component_scores else None
        return {
            "capability_score": score,
            "component_scores": component_scores,
            "capability_confidence": round(0.55 + (number % 200) / 1000.0, 3),
        }
