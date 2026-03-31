import os
import re
import shutil
import subprocess
from typing import Dict, List, Optional

from infergrade.adapters.base import BaseAdapter
from infergrade.container_runtime import docker_available, run_command_with_optional_gpu_monitor
from infergrade.images import install_image
from infergrade.models import DeploymentExecution, RunRequest
from infergrade.utils import env_value, stable_hash, utcnow_iso


_LOAD_TIME_RE = re.compile(r"load time\s*=\s*([0-9.]+)\s*ms", re.IGNORECASE)
_PROMPT_EVAL_TIME_RE = re.compile(r"prompt eval time\s*=\s*([0-9.]+)\s*ms", re.IGNORECASE)
_PROMPT_EVAL_TOKENS_RE = re.compile(r"prompt eval time\s*=\s*[0-9.]+\s*ms\s*/\s*([0-9.]+)\s*tokens?", re.IGNORECASE)
_EVAL_TIME_RE = re.compile(r"eval time\s*=\s*([0-9.]+)\s*ms", re.IGNORECASE)
_EVAL_TOKENS_RE = re.compile(r"eval time\s*=\s*[0-9.]+\s*ms\s*/\s*([0-9.]+)\s*runs?", re.IGNORECASE)
_EVAL_TPS_RE = re.compile(r"\(\s*[0-9.]+\s*ms per token,\s*([0-9.]+)\s*tokens per second\)", re.IGNORECASE)
_TOTAL_TIME_RE = re.compile(r"total time\s*=\s*([0-9.]+)\s*ms", re.IGNORECASE)
_SUMMARY_TPS_RE = re.compile(
    r"\[\s*prompt:\s*([0-9.]+)\s*t/s\s*\|\s*generation:\s*([0-9.]+)\s*t/s\s*\]",
    re.IGNORECASE,
)

_DEFAULT_IMAGE = "infergrade-llama-cpp:local"
_DEFAULT_COMMAND = "llama-cli"


class LlamaCppAdapter(BaseAdapter):
    backend_name = "llama.cpp"

    def default_backend_flags(self):
        return ["--n-gpu-layers=99"] if shutil.which("nvidia-smi") is not None else []

    def runtime_metadata(self, request: RunRequest) -> Dict[str, object]:
        return {
            "container_image": self._image_name(request),
            "container_runtime": "docker",
            "container_command": _DEFAULT_COMMAND,
        }

    def resolve_version(self, simulate: bool = True, request: RunRequest = None) -> str:
        if simulate:
            return "simulated-%s" % self.backend_name.replace(".", "-")
        self._ensure_docker()
        install_image(self._image_name(request))
        command = ["docker", "run", "--rm", "--entrypoint", _DEFAULT_COMMAND, self._image_name(request), "--version"]
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode != 0:
            message = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                "Failed to resolve llama.cpp version via Docker image %s: %s"
                % (self._image_name(request), message or "unknown error")
            )
        output = (completed.stdout or completed.stderr or "").strip()
        return output.splitlines()[0] if output else self._image_name(request)

    def run_deployment_profile(self, request: RunRequest, profile_id: str) -> DeploymentExecution:
        if request.simulate:
            return super().run_deployment_profile(request, profile_id)
        if request.execution_mode not in ("local_container", "cloud_container"):
            raise NotImplementedError("Real llama.cpp execution currently supports local_container and cloud_container modes.")
        model_path = self._require_local_gguf_artifact(request)
        profile_spec = self._profile_spec(profile_id, request.use_case)
        warmup_runs = 1 if request.tier == "canary" else 2
        measured_runs = 1 if request.tier == "canary" else 5
        measurements = []
        raw_runs = []
        failures = []

        for iteration in range(warmup_runs + measured_runs):
            is_warmup = iteration < warmup_runs
            execution = self._run_container_benchmark(
                request=request,
                model_path=model_path,
                profile_id=profile_id,
                profile_spec=profile_spec,
                is_warmup=is_warmup,
                iteration=iteration,
            )
            raw_runs.append(execution)
            if execution["status"] != "completed":
                failures.append(execution)
                continue
            if not is_warmup:
                measurements.append(execution["metrics"])

        if not measurements:
            last_failure = failures[-1] if failures else None
            raise RuntimeError(
                "llama.cpp benchmark failed for profile %s. %s"
                % (
                    profile_id,
                    last_failure.get("error") if last_failure else "No successful measurements were recorded.",
                )
            )

        metrics = {
            "ttft_p50_ms": _percentile([item["ttft_ms"] for item in measurements], 0.50),
            "ttft_p95_ms": _percentile([item["ttft_ms"] for item in measurements], 0.95),
            "latency_p50_ms": _percentile([item["latency_ms"] for item in measurements], 0.50),
            "latency_p95_ms": _percentile([item["latency_ms"] for item in measurements], 0.95),
            "decode_tokens_per_second_p50": _percentile([item["decode_tokens_per_second"] for item in measurements], 0.50),
            "decode_tokens_per_second_p95": _percentile([item["decode_tokens_per_second"] for item in measurements], 0.95),
            "request_throughput_per_minute": round(60000.0 / max(_percentile([item["latency_ms"] for item in measurements], 0.50), 1.0), 2),
            "peak_vram_mb": _max_or_none([item["peak_vram_mb"] for item in measurements]),
            "load_time_ms": _percentile([item["load_time_ms"] for item in measurements], 0.50),
            "oom_or_failure_rate": round(len(failures) / float(warmup_runs + measured_runs), 4),
            "deployment_confidence": _deployment_confidence(profile_id, len(measurements), measured_runs, len(failures)),
            "generated_at": utcnow_iso(),
        }
        return DeploymentExecution(
            profile_id=profile_id,
            metrics=metrics,
            status="completed" if not failures else "completed_with_failures",
            artifacts={
                "container_image": self._image_name(request),
                "model_path": model_path,
                "profile_spec": profile_spec,
                "runs": raw_runs,
            },
        )

    def generate_text(
        self,
        request: RunRequest,
        prompt: str,
        max_tokens: int,
    ) -> Dict[str, object]:
        if request.simulate:
            return super().generate_text(request, prompt, max_tokens)
        if request.execution_mode not in ("local_container", "cloud_container"):
            raise NotImplementedError("Real llama.cpp generation currently supports local_container and cloud_container modes.")
        install_image(self._image_name(request))
        model_path = self._require_local_gguf_artifact(request)
        model_dir = os.path.dirname(model_path)
        model_filename = os.path.basename(model_path)
        container_model_path = "/models/%s" % model_filename
        command = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            _DEFAULT_COMMAND,
            "-v",
            "%s:/models:ro" % model_dir,
        ]
        if shutil.which("nvidia-smi") is not None:
            command.extend(["--gpus", "all"])
        command.append(self._image_name(request))
        command.extend(
            self._build_llama_cli_command(
                model_path=container_model_path,
                prompt=prompt,
                max_tokens=max_tokens,
                ctx_size=max(4096, min(16384, len(prompt) * 2)),
                request=request,
            )
        )
        completed = subprocess.run(command, capture_output=True, text=True)
        raw_log = "%s\n%s" % (completed.stdout, completed.stderr)
        if completed.returncode != 0:
            raise RuntimeError((raw_log or "llama.cpp generation failed").strip())
        parsed = _parse_llama_timings(raw_log)
        return {
            "text": (completed.stdout or "").strip(),
            "status": "completed",
            "error": None,
            "latency_ms": parsed.get("total_time_ms"),
            "load_time_ms": parsed.get("load_time_ms"),
        }

    def _ensure_docker(self) -> None:
        if not docker_available():
            raise RuntimeError("Docker is required for real llama.cpp container runs.")

    def _image_name(self, request: RunRequest = None) -> str:
        if request and request.backend_image:
            return request.backend_image
        return env_value("INFERGRADE_LLAMA_CPP_IMAGE", "QUANTBENCH_LLAMA_CPP_IMAGE", _DEFAULT_IMAGE)

    def _require_local_gguf_artifact(self, request: RunRequest) -> str:
        artifact = request.quant_artifact_resolved_path or request.quant_artifact
        if not artifact:
            raise ValueError("Real llama.cpp runs currently require --quant-artifact pointing to a local GGUF file.")
        if artifact.startswith("hf://"):
            raise ValueError("Real llama.cpp runs currently require a local GGUF file path, not an hf:// reference.")
        if not os.path.isfile(artifact):
            raise ValueError("Quant artifact does not exist: %s" % artifact)
        if not artifact.lower().endswith(".gguf"):
            raise ValueError("llama.cpp expects a GGUF artifact for real runs: %s" % artifact)
        return os.path.abspath(artifact)

    def _run_container_benchmark(
        self,
        request: RunRequest,
        model_path: str,
        profile_id: str,
        profile_spec: Dict[str, object],
        is_warmup: bool,
        iteration: int,
    ) -> Dict[str, object]:
        self._ensure_docker()
        install_image(self._image_name(request))
        model_dir = os.path.dirname(model_path)
        model_filename = os.path.basename(model_path)
        container_model_path = "/models/%s" % model_filename
        command = [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            _DEFAULT_COMMAND,
        ]
        command.extend(["-v", "%s:/models:ro" % model_dir])
        if shutil.which("nvidia-smi") is not None:
            command.extend(["--gpus", "all"])
        command.append(self._image_name(request))
        command.extend(
            self._build_llama_cli_command(
                model_path=container_model_path,
                prompt=str(profile_spec["prompt"]),
                max_tokens=int(profile_spec["max_tokens"]),
                ctx_size=int(profile_spec["ctx_size"]),
                request=request,
            )
        )
        execution = run_command_with_optional_gpu_monitor(command)
        raw_log = "%s\n%s" % (execution.stdout, execution.stderr)
        raw_log = raw_log.strip()
        if execution.returncode != 0:
            return {
                "iteration": iteration,
                "warmup": is_warmup,
                "status": "failed",
                "command": command,
                "duration_seconds": round(execution.duration_seconds, 4),
                "peak_vram_mb": execution.peak_vram_mb,
                "error": raw_log or "llama.cpp container command failed",
            }
        parsed = _parse_llama_timings(raw_log)
        metrics = {
            "ttft_ms": _compute_ttft_ms(parsed),
            "latency_ms": parsed.get("total_time_ms") or round(execution.duration_seconds * 1000.0, 2),
            "decode_tokens_per_second": parsed.get("eval_tokens_per_second") or _safe_tokens_per_second(parsed),
            "load_time_ms": parsed.get("load_time_ms"),
            "peak_vram_mb": execution.peak_vram_mb,
        }
        return {
            "iteration": iteration,
            "warmup": is_warmup,
            "status": "completed",
            "command": command,
            "duration_seconds": round(execution.duration_seconds, 4),
            "peak_vram_mb": execution.peak_vram_mb,
            "metrics": metrics,
            "parsed_timings": parsed,
            "log_tail": raw_log.splitlines()[-40:],
        }

    def _build_llama_cli_command(
        self,
        model_path: str,
        prompt: str,
        max_tokens: int,
        ctx_size: int,
        request: RunRequest,
    ) -> List[str]:
        command = [
            "-m",
            model_path,
            "-p",
            prompt,
            "-n",
            str(max_tokens),
            "-c",
            str(ctx_size),
            "--seed",
            "0",
            "--temp",
            "0",
            "--top-p",
            "1",
            "--simple-io",
            "--no-display-prompt",
            "--single-turn",
            "--perf",
            "--no-warmup",
        ]
        command.extend(request.backend_flags)
        return command

    def _profile_spec(self, profile_id: str, use_case: Optional[str]) -> Dict[str, object]:
        shared_prefix = (
            "You are participating in a InferGrade deployment benchmark. "
            "Respond directly and compactly."
        )
        if profile_id == "interactive_chat_v1":
            return {
                "prompt": "%s\n\nUser: Summarize the practical trade-offs between 4-bit and 8-bit quantization for open-source LLM deployment in five bullet points.\nAssistant:" % shared_prefix,
                "max_tokens": 160,
                "ctx_size": 4096,
            }
        if profile_id == "batch_generation_v1":
            return {
                "prompt": "%s\n\nUser: Write eight short release-note bullets describing recent improvements to a benchmarking platform for quantized models. Keep each bullet crisp and specific.\nAssistant:" % shared_prefix,
                "max_tokens": 256,
                "ctx_size": 4096,
            }
        long_context_prompt = self._long_context_prompt(use_case)
        return {
            "prompt": long_context_prompt,
            "max_tokens": 96,
            "ctx_size": 8192,
        }

    def _long_context_prompt(self, use_case: Optional[str]) -> str:
        repeated_paragraph = (
            "InferGrade compares deployable artifacts rather than abstract model labels. "
            "A benchmark subject is a specific artifact bound to a specific runtime. "
            "Reproducibility depends on capturing the artifact, runtime, hardware, and prompt profile. "
        )
        body = repeated_paragraph * 160
        task = (
            "User: After reading the benchmark notes above, explain why artifact identity and runtime binding should be tracked separately in three concise paragraphs.\nAssistant:"
        )
        if use_case == "agentic_coding":
            task = (
                "User: After reading the benchmark notes above, explain how you would encode artifact identity, backend binding, and deployment metrics in a benchmark schema for agentic coding models.\nAssistant:"
            )
        return "%s\n\n%s\n\n%s" % (
            "You are participating in a InferGrade long-context benchmark.",
            body,
            task,
        )


def _parse_llama_timings(raw_log: str) -> Dict[str, float]:
    payload: Dict[str, float] = {}
    for line in raw_log.splitlines():
        lowered = line.lower()
        if "load time" in lowered:
            match = _LOAD_TIME_RE.search(line)
            if match:
                payload["load_time_ms"] = round(float(match.group(1)), 4)
            continue
        if "prompt eval time" in lowered:
            match = _PROMPT_EVAL_TIME_RE.search(line)
            if match:
                payload["prompt_eval_time_ms"] = round(float(match.group(1)), 4)
            match = _PROMPT_EVAL_TOKENS_RE.search(line)
            if match:
                payload["prompt_eval_tokens"] = round(float(match.group(1)), 4)
            continue
        if "eval time" in lowered:
            match = _EVAL_TIME_RE.search(line)
            if match:
                payload["eval_time_ms"] = round(float(match.group(1)), 4)
            match = _EVAL_TOKENS_RE.search(line)
            if match:
                payload["eval_tokens"] = round(float(match.group(1)), 4)
            match = _EVAL_TPS_RE.search(line)
            if match:
                payload["eval_tokens_per_second"] = round(float(match.group(1)), 4)
            continue
        if "total time" in lowered:
            match = _TOTAL_TIME_RE.search(line)
            if match:
                payload["total_time_ms"] = round(float(match.group(1)), 4)
            continue
        if "prompt:" in lowered and "generation:" in lowered:
            match = _SUMMARY_TPS_RE.search(line)
            if match:
                payload["prompt_tokens_per_second"] = round(float(match.group(1)), 4)
                payload["eval_tokens_per_second"] = round(float(match.group(2)), 4)
    return payload


def _compute_ttft_ms(parsed: Dict[str, float]) -> Optional[float]:
    prompt_eval = parsed.get("prompt_eval_time_ms")
    if prompt_eval is None:
        return None
    eval_time = parsed.get("eval_time_ms")
    eval_tokens = parsed.get("eval_tokens")
    first_decode_ms = 0.0
    if eval_time and eval_tokens:
        first_decode_ms = eval_time / max(eval_tokens, 1.0)
    return round(prompt_eval + first_decode_ms, 2)


def _safe_tokens_per_second(parsed: Dict[str, float]) -> Optional[float]:
    eval_time = parsed.get("eval_time_ms")
    eval_tokens = parsed.get("eval_tokens")
    if not eval_time or not eval_tokens:
        return None
    return round(eval_tokens / (eval_time / 1000.0), 2)


def _percentile(values: List[Optional[float]], percentile: float) -> Optional[float]:
    filtered = sorted(value for value in values if value is not None)
    if not filtered:
        return None
    if len(filtered) == 1:
        return round(filtered[0], 2)
    index = int(round((len(filtered) - 1) * percentile))
    index = max(0, min(index, len(filtered) - 1))
    return round(filtered[index], 2)


def _max_or_none(values: List[Optional[float]]) -> Optional[float]:
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return round(max(filtered), 2)


def _deployment_confidence(profile_id: str, measured_successes: int, measured_target: int, failures: int) -> float:
    base = {
        "interactive_chat_v1": 0.88,
        "batch_generation_v1": 0.74,
        "long_context_v1": 0.82,
    }.get(profile_id, 0.7)
    if measured_successes < measured_target:
        base -= 0.2
    if failures:
        base -= 0.1
    return round(max(0.2, min(base, 0.95)), 2)
