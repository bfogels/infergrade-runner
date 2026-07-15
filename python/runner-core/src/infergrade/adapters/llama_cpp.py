import json
import math
import os
import re
import shlex
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request

from infergrade import __version__
from infergrade.adapters.base import BaseAdapter
from infergrade.benchmark_catalog import fidelity_enabled_for_request
from infergrade.container_runtime import (
    docker_available,
    sample_total_gpu_memory_used_mb,
)
from infergrade.images import install_image
from infergrade.models import DeploymentExecution, FidelityExecution, RunRequest
from infergrade.profiles import DIRECT_ANSWER_GENERATION_PRESET
from infergrade.runtimes import managed_llama_cpp_binary_path, selected_llama_cpp_runtime
from infergrade.utils import env_value, stable_hash, utcnow_iso


_LOAD_TIME_RE = re.compile(r"load time\s*=\s*([0-9.]+)\s*ms", re.IGNORECASE)
_PROMPT_EVAL_TIME_RE = re.compile(r"prompt eval time\s*=\s*([0-9.]+)\s*ms", re.IGNORECASE)
_PROMPT_EVAL_TOKENS_RE = re.compile(r"prompt eval time\s*=\s*[0-9.]+\s*ms\s*/\s*([0-9.]+)\s*tokens?", re.IGNORECASE)
_EVAL_TIME_RE = re.compile(r"eval time\s*=\s*([0-9.]+)\s*ms", re.IGNORECASE)
_EVAL_TOKENS_RE = re.compile(r"eval time\s*=\s*[0-9.]+\s*ms\s*/\s*([0-9.]+)\s*runs?", re.IGNORECASE)
_EVAL_TPS_RE = re.compile(r"\(\s*[0-9.]+\s*ms per token,\s*([0-9.]+)\s*tokens per second\)", re.IGNORECASE)
_TOTAL_TIME_RE = re.compile(r"total time\s*=\s*([0-9.]+)\s*ms", re.IGNORECASE)
_TOTAL_TIME_TOKENS_RE = re.compile(r"total time\s*=\s*[0-9.]+\s*ms\s*/\s*([0-9.]+)\s*tokens?", re.IGNORECASE)
_SUMMARY_TPS_RE = re.compile(
    r"\[\s*prompt:\s*([0-9.]+)\s*t/s\s*\|\s*generation:\s*([0-9.]+)\s*t/s\s*\]",
    re.IGNORECASE,
)
_PERPLEXITY_RE = re.compile(r"Final estimate:\s*PPL\s*=\s*([0-9.]+)\s*\+/-\s*([0-9.]+)", re.IGNORECASE)
_PERPLEXITY_TOKENIZATION_RE = re.compile(r"tokenizes to only\s*([0-9.]+)\s*tokens", re.IGNORECASE)
_MEMORY_BUFFER_RE = re.compile(
    r"(?P<label>[^\n]*?(?:model|kv)[^\n]*?buffer size)\s*=\s*(?P<value>[0-9.]+)\s*(?P<unit>[KMGT]i?B)",
    re.IGNORECASE,
)

_DEFAULT_IMAGE = "ghcr.io/bfogels/infergrade-llama-cpp:%s" % __version__
_DEFAULT_COMMAND = "llama-cli"
_DEFAULT_SERVER_COMMAND = "llama-server"
_DEFAULT_PERPLEXITY_COMMAND = "llama-perplexity"
_DEFAULT_SERVER_PORT = 8080
_SERVER_READY_TIMEOUT_SECONDS = 180.0
_SERVER_REQUEST_TIMEOUT_SECONDS = 300.0
_CONTAINER_MEMORY_SAMPLE_INTERVAL_SECONDS = 0.25
_PINNED_LLAMA_CPP_REF = "9f102a1407ed5d73b8c954f32edab50f8dfa3f58"
_UNSUPPORTED_STABLE_CONTAINER_ARCHITECTURES = {
    "gemma4": "the stable llama.cpp container predates Gemma 4 GGUF support",
}
_PERPLEXITY_CORPUS_ID = "infergrade_quantfidelity_v1"
_PERPLEXITY_CORPUS_REVISION = "sha256:ca86babd3cb6e69ca5db20f7625723da6951f98bcaab98f12291db36deef3512"
_PERPLEXITY_PROTOCOL_ID = "infergrade_perplexity_v1"
_PERPLEXITY_CONTEXT_SIZE = 128
_PERPLEXITY_OUTPUT_TYPE = 0
_PERPLEXITY_STRIDE = 0
_PERPLEXITY_CORPUS_TEXT = (
    "InferGrade measures how deployable model artifacts behave on real hardware. "
    "Every benchmark result should preserve which quantized file ran, which runtime executed it, and which machine produced the evidence. "
    "Throughput, load time, and time to first token all matter because users care about how a model feels in practice, not only how it looks on paper. "
    "Capability benchmarks should stay use-case aware so coding results are not silently mixed with general assistant results. "
    "Trust requires pinned runtime identity, hardware capture, and artifact provenance. "
    "Users also need a fidelity signal for comparing nearby quantization variants, especially when task scores cluster tightly. "
    "Perplexity is useful for that narrow job, but it should not replace task-level capability or deployment telemetry. "
    "InferGrade therefore treats fidelity as a supporting signal that sits beside capability rather than above it. "
) * 20


def _decode_utf8_lossy(value) -> str:
    """Decode external runtime bytes without letting bad UTF-8 crash the runner."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


def _llama_cpp_version_label(output: str) -> Optional[str]:
    """Extract the stable version line from noisy llama.cpp startup output."""
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    if not lines:
        return None
    for line in lines:
        if line.lower().startswith("version:"):
            return line
    first = lines[0]
    if first.lower().startswith(("ggml_", "llama_", "load_backend")):
        return None
    return first


class LlamaCppAdapter(BaseAdapter):
    backend_name = "llama.cpp"

    def __init__(self):
        # Direct-answer capability suites can contain hundreds of cases. Keep a
        # native chat server alive only while one suite is executing; individual
        # generate_text calls outside that boundary retain the one-shot path.
        self._capability_server_reuse_enabled = False
        self._capability_server_session = None

    def default_backend_flags(self):
        return ["--n-gpu-layers=99"] if shutil.which("nvidia-smi") is not None else []

    def runtime_metadata(self, request: RunRequest) -> Dict[str, object]:
        if request and request.execution_mode == "local_native":
            cli_binary = self._native_command_path(request)
            server_binary = self._native_server_path(request)
            return {
                "container_image": None,
                "container_runtime": None,
                "container_command": None,
                "native_binary": cli_binary,
                "native_server_binary": server_binary,
                "native_perplexity_binary": _try_resolve_native_binary(
                    explicit=getattr(request, "llama_cpp_perplexity_path", None),
                    env_name="INFERGRADE_LLAMA_CPP_PERPLEXITY",
                    default=_DEFAULT_PERPLEXITY_COMMAND,
                ),
                "runtime_source": _native_runtime_source(request),
                "pinned_runtime_ref": None,
            }
        return {
            "container_image": self._image_name(request),
            "container_runtime": "docker",
            "container_command": _DEFAULT_COMMAND,
            "runtime_source": "container_image",
            "pinned_runtime_ref": _PINNED_LLAMA_CPP_REF,
        }

    def resolve_version(self, simulate: bool = True, request: RunRequest = None) -> str:
        if simulate:
            return "simulated-%s" % self.backend_name.replace(".", "-")
        if request is not None:
            self._ensure_backend_model_compatibility(request)
        if request and request.execution_mode == "local_native":
            command = [self._native_command_path(request), "--version"]
            completed = subprocess.run(command, capture_output=True)
            stdout = _decode_utf8_lossy(completed.stdout)
            stderr = _decode_utf8_lossy(completed.stderr)
            if completed.returncode != 0:
                message = (stderr or stdout or "").strip()
                raise RuntimeError(
                    "Failed to resolve llama.cpp version via native binary %s: %s"
                    % (self._native_command_path(request), message or "unknown error")
                )
            output = (stdout or stderr or "").strip()
            return _llama_cpp_version_label(output) or self._native_command_path(request)
        self._ensure_docker()
        install_image(self._image_name(request))
        command = ["docker", "run", "--rm", "--entrypoint", _DEFAULT_COMMAND, self._image_name(request), "--version"]
        completed = subprocess.run(command, capture_output=True)
        stdout = _decode_utf8_lossy(completed.stdout)
        stderr = _decode_utf8_lossy(completed.stderr)
        if completed.returncode != 0:
            message = (stderr or stdout or "").strip()
            raise RuntimeError(
                "Failed to resolve llama.cpp version via Docker image %s: %s"
                % (self._image_name(request), message or "unknown error")
            )
        output = (stdout or stderr or "").strip()
        return _llama_cpp_version_label(output) or self._image_name(request)

    def run_deployment_profile(
        self,
        request: RunRequest,
        profile_id: str,
        progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> DeploymentExecution:
        if request.simulate:
            return super().run_deployment_profile(request, profile_id, progress_callback=progress_callback)
        if request.execution_mode not in ("local_container", "local_native", "cloud_container"):
            raise NotImplementedError("Real llama.cpp execution currently supports local_container, local_native, and cloud_container modes.")
        self._ensure_backend_model_compatibility(request)
        model_path = self._require_local_gguf_artifact(request)
        profile_spec = self._profile_spec(profile_id, request.use_case)
        warmup_runs = _bounded_deployment_run_count(
            request.deployment_warmup_runs,
            default=1 if request.tier == "canary" else 2,
            minimum=0,
            maximum=5,
            field_name="deployment_warmup_runs",
        )
        measured_runs = _bounded_deployment_run_count(
            request.deployment_measured_runs,
            default=1 if request.tier == "canary" else 5,
            minimum=1,
            maximum=20,
            field_name="deployment_measured_runs",
        )
        total_iterations = warmup_runs + measured_runs
        measurements = []
        raw_runs = []
        failures = []

        if progress_callback:
            progress_callback(
                {
                    "event": "profile_started",
                    "profile_id": profile_id,
                    "warmup_runs": warmup_runs,
                    "measured_runs": measured_runs,
                    "total_iterations": total_iterations,
                    "message": "Deployment profile %s started." % profile_id,
                }
            )

        for iteration in range(total_iterations):
            is_warmup = iteration < warmup_runs
            if progress_callback:
                phase = "warmup" if is_warmup else "measured"
                progress_callback(
                    {
                        "event": "iteration_started",
                        "profile_id": profile_id,
                        "total_iterations": total_iterations,
                        "completed_iterations": iteration,
                        "current_iteration": iteration + 1,
                        "warmup_runs": warmup_runs,
                        "measured_runs": measured_runs,
                        "phase": phase,
                        "message": "Deployment profile %s %s iteration %d/%d." % (
                            profile_id,
                            phase,
                            iteration + 1,
                            total_iterations,
                        ),
                    }
                )
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
            elif not is_warmup:
                measurements.append(execution["metrics"])
            if progress_callback:
                phase = "warmup" if is_warmup else "measured"
                progress_callback(
                    {
                        "event": "iteration_completed",
                        "profile_id": profile_id,
                        "total_iterations": total_iterations,
                        "completed_iterations": iteration + 1,
                        "current_iteration": iteration + 1,
                        "warmup_runs": warmup_runs,
                        "measured_runs": measured_runs,
                        "phase": phase,
                        "status": execution["status"],
                        "message": "Deployment profile %s completed %s iteration %d/%d." % (
                            profile_id,
                            phase,
                            iteration + 1,
                            total_iterations,
                        ),
                    }
                )

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
            "warmup_runs": warmup_runs,
            "measured_runs": measured_runs,
            "ttft_p50_ms": _percentile([item["ttft_ms"] for item in measurements], 0.50),
            "ttft_p95_ms": _percentile([item["ttft_ms"] for item in measurements], 0.95),
            "latency_p50_ms": _percentile([item["latency_ms"] for item in measurements], 0.50),
            "latency_p95_ms": _percentile([item["latency_ms"] for item in measurements], 0.95),
            "prompt_tokens_per_second_p50": _percentile(
                [item["prompt_tokens_per_second"] for item in measurements], 0.50
            ),
            "prompt_tokens_per_second_p95": _percentile(
                [item["prompt_tokens_per_second"] for item in measurements], 0.95
            ),
            "decode_tokens_per_second_p50": _percentile([item["decode_tokens_per_second"] for item in measurements], 0.50),
            "decode_tokens_per_second_p95": _percentile([item["decode_tokens_per_second"] for item in measurements], 0.95),
            "output_tokens_p50": _percentile([item.get("output_tokens") for item in measurements], 0.50),
            "output_tokens_p95": _percentile([item.get("output_tokens") for item in measurements], 0.95),
            "natural_stop_rate": round(
                sum(1 for item in measurements if item.get("natural_stop")) / float(len(measurements)),
                4,
            ),
            "token_budget_exhaustion_rate": round(
                sum(1 for item in measurements if item.get("token_budget_exhausted")) / float(len(measurements)),
                4,
            ),
            "semantic_task_completion_proof": False,
            "completion_semantics": "natural_stop_is_not_semantic_correctness; use capability task-time for scored task completion",
            "request_throughput_per_minute": round(60000.0 / max(_percentile([item["latency_ms"] for item in measurements], 0.50), 1.0), 2),
            "peak_vram_mb": _max_or_none([item["peak_vram_mb"] for item in measurements]),
            "peak_memory_mb": _max_or_none([item.get("peak_memory_mb") for item in measurements]),
            "peak_memory_measurement_method": _first_nonempty(
                [item.get("peak_memory_measurement_method") for item in measurements]
            ),
            "model_weights_bytes": os.path.getsize(model_path),
            "model_buffer_bytes": _max_or_none([item.get("model_buffer_bytes") for item in measurements]),
            "kv_cache_bytes": _max_or_none([item.get("kv_cache_bytes") for item in measurements]),
            "kv_cache_context_tokens": int(profile_spec["ctx_size"]),
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

    def run_capability(
        self,
        request: RunRequest,
        progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ):
        if not request.simulate:
            self._ensure_backend_model_compatibility(request)
        reuse_native_server = _uses_native_direct_answer_server(request)
        if not reuse_native_server and _can_reuse_native_capability_server(request):
            try:
                self._native_server_path(request)
            except RuntimeError:
                # A raw completion setup that predates the managed three-binary
                # runtime remains supported through its existing one-shot path.
                reuse_native_server = False
            else:
                reuse_native_server = True
        if not reuse_native_server:
            return super().run_capability(request, progress_callback=progress_callback)
        self._capability_server_reuse_enabled = True
        try:
            return super().run_capability(request, progress_callback=progress_callback)
        finally:
            self._stop_capability_server_session()
            self._capability_server_reuse_enabled = False

    def generate_text(
        self,
        request: RunRequest,
        prompt: str,
        max_tokens: int,
    ) -> Dict[str, object]:
        if request.simulate:
            return super().generate_text(request, prompt, max_tokens)
        if request.execution_mode not in ("local_container", "local_native", "cloud_container"):
            raise NotImplementedError("Real llama.cpp generation currently supports local_container, local_native, and cloud_container modes.")
        self._ensure_backend_model_compatibility(request)
        model_path = self._require_local_gguf_artifact(request)
        if (
            request.generation_preset == DIRECT_ANSWER_GENERATION_PRESET
            and _is_qwen36_request(request)
            and request.execution_mode != "local_native"
        ):
            raise RuntimeError(
                "Qwen3.6 direct-answer generation requires the local_native llama-server chat path so "
                "InferGrade can pass chat_template_kwargs.enable_thinking=false. The /no_think prompt "
                "switch used by older Qwen models is not valid evidence for Qwen3.6."
            )
        if (
            request.generation_preset == DIRECT_ANSWER_GENERATION_PRESET
            and _infer_llama_cpp_architecture(request) == "gemma4"
            and request.execution_mode != "local_native"
        ):
            raise RuntimeError(
                "Gemma 4 direct-answer generation requires the local_native llama-server chat path. "
                "Runner container capability generation still uses llama-completion, which cannot safely apply "
                "Gemma 4's Jinja chat template."
            )
        if _uses_native_direct_answer_server(request):
            return self._generate_native_server_text(
                request=request,
                model_path=model_path,
                prompt=prompt,
                max_tokens=max_tokens,
            )
        effective_prompt, prompt_transform = _prepare_llama_prompt(request, prompt)
        if request.execution_mode == "local_native":
            if self._capability_server_reuse_enabled:
                return self._generate_native_completion_server_text(
                    request=request,
                    model_path=model_path,
                    prompt=effective_prompt,
                    prompt_transform=prompt_transform,
                    max_tokens=max_tokens,
                )
            command = [self._native_completion_path(request)]
            command.extend(
                self._build_llama_cli_command(
                    model_path=model_path,
                    prompt=effective_prompt,
                    max_tokens=max_tokens,
                    ctx_size=max(4096, min(16384, len(prompt) * 2)),
                    request=request,
                )
            )
        else:
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
                "-v",
                "%s:/models:ro" % model_dir,
            ]
            if shutil.which("nvidia-smi") is not None:
                command.extend(["--gpus", "all"])
            command.append(self._image_name(request))
            command.extend(
                self._build_llama_cli_command(
                    model_path=container_model_path,
                    prompt=effective_prompt,
                    max_tokens=max_tokens,
                    ctx_size=max(4096, min(16384, len(prompt) * 2)),
                    request=request,
                )
            )
        completed = subprocess.run(command, capture_output=True)
        stdout = _decode_utf8_lossy(completed.stdout)
        stderr = _decode_utf8_lossy(completed.stderr)
        raw_log = "%s\n%s" % (stdout, stderr)
        if completed.returncode != 0:
            raise RuntimeError((raw_log or "llama.cpp generation failed").strip())
        parsed = _parse_llama_timings(raw_log)
        output = stdout.strip()
        protocol_error = _llama_generation_protocol_error(
            output,
            max_tokens=max_tokens,
            output_tokens=_whole_token_count(parsed.get("eval_tokens")),
        )
        if protocol_error:
            raise RuntimeError(protocol_error)
        return {
            "text": output,
            "status": "completed",
            "error": None,
            "latency_ms": parsed.get("total_time_ms"),
            "time_to_first_token_ms": _compute_ttft_ms(parsed),
            "tokens_per_second": parsed.get("eval_tokens_per_second") or _safe_tokens_per_second(parsed),
            "input_tokens": _whole_token_count(parsed.get("prompt_eval_tokens")),
            "output_tokens": _whole_token_count(parsed.get("eval_tokens")),
            "measurement_source": "llama_cpp_timings",
            "load_time_ms": parsed.get("load_time_ms"),
            "prompt_transform": prompt_transform,
        }

    def _generate_native_server_text(
        self,
        request: RunRequest,
        model_path: str,
        prompt: str,
        max_tokens: int,
    ) -> Dict[str, object]:
        """Generate one capability answer through llama-server's chat template.

        Qwen3.5's embedded template does not honor the legacy ``/no_think``
        directive through ``llama-completion``. The server chat API accepts the
        same explicit ``enable_thinking=false`` policy already used by deployment
        profiles, so direct-answer capability tasks use that protocol as well.
        Gemma 4 also requires its Jinja chat template; recent llama-completion
        builds abort when asked to infer that template from a preformatted prompt.
        """
        messages, prompt_transform = _prepare_llama_server_chat(request, prompt)
        if messages is None:
            raise RuntimeError("Direct-answer generation requires structured chat messages")
        ctx_size = max(4096, min(16384, len(prompt) * 2))
        if self._capability_server_reuse_enabled:
            session = self._ensure_capability_server_session(request, model_path, ctx_size)
            try:
                return self._complete_native_server_text(
                    session=session,
                    messages=messages,
                    prompt_transform=prompt_transform,
                    max_tokens=max_tokens,
                    reuse_session=True,
                )
            except Exception:
                # Invalid model output is a case-level benchmark failure, not a
                # reason to reload the model. Discard only a server process that
                # actually exited; a live stateless endpoint can serve the next
                # independent case safely.
                process = session.get("process")
                if process is None or process.poll() is not None:
                    self._stop_capability_server_session()
                raise

        published_port = _find_free_local_port()
        command = [self._native_server_path(request)]
        command.extend(
            self._build_llama_server_command(
                model_path=model_path,
                ctx_size=ctx_size,
                request=request,
                host="127.0.0.1",
                port=published_port,
            )
        )
        log_handle = tempfile.NamedTemporaryFile(prefix="infergrade-llama-capability-", suffix=".log", delete=False)
        log_path = log_handle.name
        log_handle.close()
        process = None
        started = time.perf_counter()
        try:
            with open(log_path, "wb") as log_file:
                process = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)
            base_url, load_time_ms = _wait_for_native_server_ready(process, published_port, started, log_path)
            return self._complete_native_server_text(
                session={
                    "base_url": base_url,
                    "load_time_ms": load_time_ms,
                    "load_time_reported": False,
                    "log_path": log_path,
                },
                messages=messages,
                prompt_transform=prompt_transform,
                max_tokens=max_tokens,
                reuse_session=False,
            )
        except Exception as exc:
            logs_text = _read_log_file(log_path)
            detail = str(exc)
            if logs_text and not detail:
                detail = logs_text.splitlines()[-1]
            raise RuntimeError(detail or "llama.cpp Qwen3.5 chat generation failed") from exc
        finally:
            _stop_process(process)
            try:
                os.unlink(log_path)
            except OSError:
                pass

    def _ensure_capability_server_session(
        self,
        request: RunRequest,
        model_path: str,
        ctx_size: int,
    ) -> Dict[str, object]:
        # Bucket growth so a suite can restart at most twice after its initial
        # 4K server rather than once for every new prompt-length high water mark.
        ctx_size = 4096 if ctx_size <= 4096 else 8192 if ctx_size <= 8192 else 16384
        session = self._capability_server_session
        request_key = (
            os.path.abspath(model_path),
            self._native_server_path(request),
            tuple(request.backend_flags),
        )
        if (
            session
            and session.get("request_key") == request_key
            and int(session.get("ctx_size") or 0) >= ctx_size
            and session.get("process") is not None
            and session["process"].poll() is None
        ):
            return session

        self._stop_capability_server_session()
        published_port = _find_free_local_port()
        command = [request_key[1]]
        command.extend(
            self._build_llama_server_command(
                model_path=model_path,
                ctx_size=ctx_size,
                request=request,
                host="127.0.0.1",
                port=published_port,
            )
        )
        log_handle = tempfile.NamedTemporaryFile(
            prefix="infergrade-llama-capability-suite-",
            suffix=".log",
            delete=False,
        )
        log_path = log_handle.name
        log_handle.close()
        process = None
        started = time.perf_counter()
        try:
            with open(log_path, "wb") as log_file:
                process = subprocess.Popen(command, stdout=log_file, stderr=subprocess.STDOUT)
            base_url, load_time_ms = _wait_for_native_server_ready(
                process,
                published_port,
                started,
                log_path,
            )
        except Exception:
            _stop_process(process)
            try:
                os.unlink(log_path)
            except OSError:
                pass
            raise
        session = {
            "base_url": base_url,
            "ctx_size": ctx_size,
            "load_time_ms": load_time_ms,
            "load_time_reported": False,
            "log_path": log_path,
            "process": process,
            "request_key": request_key,
        }
        self._capability_server_session = session
        return session

    def _generate_native_completion_server_text(
        self,
        request: RunRequest,
        model_path: str,
        prompt: str,
        prompt_transform: Optional[Dict[str, str]],
        max_tokens: int,
    ) -> Dict[str, object]:
        ctx_size = max(4096, min(16384, len(prompt) * 2))
        session = self._ensure_capability_server_session(request, model_path, ctx_size)
        try:
            completion = _stream_server_completion(
                base_url=str(session["base_url"]),
                prompt=prompt,
                max_tokens=max_tokens,
            )
            final_payload = dict(completion.get("final_payload") or {})
            timings = dict(final_payload.get("timings") or {})
            output_tokens = _whole_token_count(
                final_payload.get("tokens_predicted") or timings.get("predicted_n")
            )
            protocol_error = _llama_generation_protocol_error(
                str(completion.get("text") or ""),
                max_tokens=max_tokens,
                output_tokens=output_tokens,
            )
            if protocol_error:
                raise RuntimeError(protocol_error)
            report_load_time = not bool(session.get("load_time_reported"))
            metrics = _metrics_from_server_completion(
                completion=completion,
                parsed_timings={},
                load_time_ms=session.get("load_time_ms") if report_load_time else None,
                peak_vram_mb=None,
            )
            session["load_time_reported"] = True
            return {
                "text": completion["text"],
                "status": "completed",
                "error": None,
                "latency_ms": metrics.get("latency_ms"),
                "time_to_first_token_ms": metrics.get("ttft_ms"),
                "tokens_per_second": metrics.get("decode_tokens_per_second"),
                "input_tokens": _whole_token_count(
                    final_payload.get("tokens_evaluated") or timings.get("prompt_n")
                ),
                "output_tokens": metrics.get("output_tokens"),
                "measurement_source": "llama_cpp_server_completion_timings",
                "load_time_ms": metrics.get("load_time_ms"),
                "prompt_transform": prompt_transform,
            }
        except Exception:
            process = session.get("process")
            if process is None or process.poll() is not None:
                self._stop_capability_server_session()
            raise

    def _complete_native_server_text(
        self,
        session: Dict[str, object],
        messages: List[Dict[str, str]],
        prompt_transform: Optional[Dict[str, str]],
        max_tokens: int,
        reuse_session: bool,
    ) -> Dict[str, object]:
        completion = _stream_server_chat_completion(
            base_url=str(session["base_url"]),
            messages=messages,
            max_tokens=max_tokens,
        )
        _validate_direct_answer_server_completion(completion, prompt_transform)
        parsed = {} if reuse_session else _parse_llama_timings(_read_log_file(str(session["log_path"])))
        report_load_time = not bool(session.get("load_time_reported"))
        metrics = _metrics_from_server_completion(
            completion=completion,
            parsed_timings=parsed,
            load_time_ms=session.get("load_time_ms") if report_load_time else None,
            peak_vram_mb=None,
        )
        session["load_time_reported"] = True
        final_payload = dict(completion.get("final_payload") or {})
        usage = dict(final_payload.get("usage") or {})
        timings = dict(final_payload.get("timings") or {})
        return {
            "text": completion["text"],
            "status": "completed",
            "error": None,
            "latency_ms": metrics.get("latency_ms"),
            "time_to_first_token_ms": metrics.get("ttft_ms"),
            "tokens_per_second": metrics.get("decode_tokens_per_second"),
            "input_tokens": _whole_token_count(
                usage.get("prompt_tokens") or timings.get("prompt_n") or parsed.get("prompt_eval_tokens")
            ),
            "output_tokens": metrics.get("output_tokens"),
            "measurement_source": "llama_cpp_server_chat_timings",
            "load_time_ms": metrics.get("load_time_ms"),
            "prompt_transform": prompt_transform,
        }

    def _stop_capability_server_session(self) -> None:
        session = self._capability_server_session
        self._capability_server_session = None
        if not session:
            return
        _stop_process(session.get("process"))
        try:
            os.unlink(str(session.get("log_path") or ""))
        except OSError:
            pass

    def run_fidelity(self, request: RunRequest) -> FidelityExecution:
        if request.simulate:
            return FidelityExecution(
                state="not_yet_measured",
                reason_codes=["simulated_run_skips_fidelity"],
                context=self._perplexity_context(),
            )
        if not fidelity_enabled_for_request(request):
            return FidelityExecution(
                state="skipped",
                reason_codes=["fidelity_check_not_selected"],
                context=self._perplexity_context(),
            )
        if request.execution_mode not in ("local_container", "local_native", "cloud_container"):
            return FidelityExecution(
                state="not_comparable",
                reason_codes=["execution_mode_not_supported_for_fidelity"],
                context=self._perplexity_context(),
            )

        self._ensure_backend_model_compatibility(request)
        model_path = self._require_local_gguf_artifact(request)
        started = time.perf_counter()
        try:
            result = self._run_perplexity(request, model_path)
            bits_per_byte = _bits_per_byte(
                result.get("perplexity"),
                result.get("corpus_token_count"),
                result.get("corpus_byte_count"),
            )
            metrics = {
                "perplexity": {
                    "metric_name": "perplexity",
                    "value": result["perplexity"],
                    "stderr": result.get("stderr"),
                    "bits_per_byte": bits_per_byte,
                    "lower_is_better": True,
                    "evaluation_backend": result.get("evaluation_backend"),
                    "duration_seconds": result.get("duration_seconds"),
                    "corpus_token_count": result.get("corpus_token_count"),
                    "corpus_byte_count": result.get("corpus_byte_count"),
                    "status": "measured",
                    "comparability_key": self._perplexity_comparability_key(request),
                    "protocol_id": _PERPLEXITY_PROTOCOL_ID,
                    "corpus_id": _PERPLEXITY_CORPUS_ID,
                    "corpus_revision": _PERPLEXITY_CORPUS_REVISION,
                    "protocol_parameters": self._perplexity_protocol_parameters(),
                }
            }
            return FidelityExecution(
                state="measured",
                reason_codes=["perplexity_measured"],
                metrics=metrics,
                context=self._perplexity_context(),
                artifacts={"command": result.get("command"), "log_tail": result.get("log_tail")},
            )
        except Exception as exc:
            return FidelityExecution(
                state="not_yet_measured",
                reason_codes=["perplexity_measurement_failed"],
                context=self._perplexity_context(),
                artifacts={
                    "error": str(exc),
                    "duration_seconds": round(time.perf_counter() - started, 4),
                },
            )

    def _ensure_docker(self) -> None:
        if not docker_available():
            raise RuntimeError("Docker is required for real llama.cpp container runs.")

    def _native_command_path(self, request: RunRequest = None) -> str:
        return _resolve_native_binary(
            explicit=getattr(request, "llama_cpp_cli_path", None),
            env_name="INFERGRADE_LLAMA_CPP_CLI",
            default=_DEFAULT_COMMAND,
            label="CLI",
        )

    def _native_server_path(self, request: RunRequest = None) -> str:
        return _resolve_native_binary(
            explicit=getattr(request, "llama_cpp_server_path", None),
            env_name="INFERGRADE_LLAMA_CPP_SERVER",
            default=_DEFAULT_SERVER_COMMAND,
            label="server",
        )

    def _native_perplexity_path(self, request: RunRequest = None) -> str:
        return _resolve_native_binary(
            explicit=getattr(request, "llama_cpp_perplexity_path", None),
            env_name="INFERGRADE_LLAMA_CPP_PERPLEXITY",
            default=_DEFAULT_PERPLEXITY_COMMAND,
            label="perplexity",
        )

    def _image_name(self, request: RunRequest = None) -> str:
        if request and request.backend_image:
            return request.backend_image
        return env_value("INFERGRADE_LLAMA_CPP_IMAGE", "QUANTBENCH_LLAMA_CPP_IMAGE", _DEFAULT_IMAGE)

    def _ensure_backend_model_compatibility(self, request: RunRequest) -> None:
        architecture = _infer_llama_cpp_architecture(request)
        if architecture not in _UNSUPPORTED_STABLE_CONTAINER_ARCHITECTURES:
            return None
        # The release-default container remains on the stable pin. Explicit
        # native runtimes and custom images are deliberate candidate lanes and
        # may attempt the load while preserving their exact version and failure.
        selected_image = self._image_name(request)
        if request.execution_mode == "local_native" or selected_image != _DEFAULT_IMAGE:
            return None
        raise RuntimeError(
            "llama.cpp backend compatibility check failed: GGUF architecture '%s' is not supported by "
            "the stable container runtime (%s) because %s. Use an explicit reviewed candidate runtime "
            "or custom image to collect candidate-lane evidence."
            % (
                architecture,
                _PINNED_LLAMA_CPP_REF,
                _UNSUPPORTED_STABLE_CONTAINER_ARCHITECTURES[architecture],
            )
        )

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
        if request.execution_mode == "local_native":
            return self._run_native_benchmark(
                request=request,
                model_path=model_path,
                profile_id=profile_id,
                profile_spec=profile_spec,
                is_warmup=is_warmup,
                iteration=iteration,
            )
        self._ensure_docker()
        install_image(self._image_name(request))
        model_dir = os.path.dirname(model_path)
        model_filename = os.path.basename(model_path)
        container_model_path = "/models/%s" % model_filename
        container_name = "infergrade-llama-%s" % stable_hash(
            [model_path, profile_id, iteration, utcnow_iso()]
        )[:12]
        command = [
            "docker",
            "run",
            "-d",
            "--rm",
            "--name",
            container_name,
            "--entrypoint",
            _DEFAULT_SERVER_COMMAND,
            "-p",
            "%s" % _DEFAULT_SERVER_PORT,
            "-v",
            "%s:/models:ro" % model_dir,
        ]
        if shutil.which("nvidia-smi") is not None:
            command.extend(["--gpus", "all"])
        command.append(self._image_name(request))
        command.extend(
            self._build_llama_server_command(
                model_path=container_model_path,
                ctx_size=int(profile_spec["ctx_size"]),
                request=request,
            )
        )

        effective_prompt = str(profile_spec["prompt"])
        chat_messages, prompt_transform = _prepare_llama_server_chat(request, effective_prompt)
        monitor = _start_gpu_monitor()
        memory_monitor = None
        started = time.perf_counter()
        logs_text = ""
        try:
            completed = subprocess.run(command, capture_output=True)
            stdout = _decode_utf8_lossy(completed.stdout)
            stderr = _decode_utf8_lossy(completed.stderr)
            startup_output = (stdout or stderr or "").strip()
            if completed.returncode != 0:
                return {
                    "iteration": iteration,
                    "warmup": is_warmup,
                    "status": "failed",
                    "command": command,
                    "duration_seconds": round(time.perf_counter() - started, 4),
                    "peak_vram_mb": _stop_gpu_monitor(monitor),
                    "error": startup_output or "llama.cpp server container failed to start",
                    "prompt_transform": prompt_transform,
                }

            memory_monitor = _start_container_memory_monitor(container_name)

            published_port = _resolve_published_port(container_name, _DEFAULT_SERVER_PORT)
            base_url, load_time_ms = _wait_for_server_ready(
                container_name=container_name,
                published_port=published_port,
                started_at=started,
            )
            completion = (
                _stream_server_chat_completion(
                    base_url=base_url,
                    messages=chat_messages,
                    max_tokens=int(profile_spec["max_tokens"]),
                )
                if chat_messages is not None
                else _stream_server_completion(
                    base_url=base_url,
                    prompt=effective_prompt,
                    max_tokens=int(profile_spec["max_tokens"]),
                )
            )
            _validate_direct_answer_server_completion(completion, prompt_transform)
            logs_text = _fetch_container_logs(container_name)
            parsed = _parse_llama_timings(logs_text)
            memory_allocations = _parse_llama_memory_allocations(logs_text)
            peak_vram_mb = _stop_gpu_monitor(monitor)
            peak_memory_mb, peak_memory_method = _stop_container_memory_monitor(memory_monitor)
            memory_monitor = None
            metrics = _metrics_from_server_completion(
                completion=completion,
                parsed_timings=parsed,
                load_time_ms=load_time_ms,
                peak_vram_mb=peak_vram_mb,
            )
            metrics.update(memory_allocations)
            metrics["peak_memory_mb"] = peak_memory_mb if peak_memory_mb is not None else peak_vram_mb
            metrics["peak_memory_measurement_method"] = (
                peak_memory_method
                if peak_memory_mb is not None
                else ("nvidia_smi_total_used_delta" if peak_vram_mb is not None else None)
            )
            return {
                "iteration": iteration,
                "warmup": is_warmup,
                "status": "completed",
                "command": command,
                "duration_seconds": round((load_time_ms + metrics["latency_ms"]) / 1000.0, 4)
                if load_time_ms is not None and metrics.get("latency_ms") is not None
                else round(time.perf_counter() - started, 4),
                "peak_vram_mb": peak_vram_mb,
                "metrics": metrics,
                "parsed_timings": parsed,
                "completion_summary": completion["final_payload"],
                "prompt_transform": prompt_transform,
                "log_tail": logs_text.splitlines()[-40:],
            }
        except Exception as exc:
            logs_text = logs_text or _fetch_container_logs(container_name)
            return {
                "iteration": iteration,
                "warmup": is_warmup,
                "status": "failed",
                "command": command,
                "duration_seconds": round(time.perf_counter() - started, 4),
                "peak_vram_mb": _stop_gpu_monitor(monitor),
                "error": str(exc),
                "prompt_transform": prompt_transform,
                "log_tail": logs_text.splitlines()[-40:],
            }
        finally:
            _stop_container_memory_monitor(memory_monitor)
            _stop_container(container_name)

    def _run_native_benchmark(
        self,
        request: RunRequest,
        model_path: str,
        profile_id: str,
        profile_spec: Dict[str, object],
        is_warmup: bool,
        iteration: int,
    ) -> Dict[str, object]:
        server_binary = self._native_server_path(request)
        published_port = _find_free_local_port()
        log_handle = tempfile.NamedTemporaryFile(prefix="infergrade-llama-native-", suffix=".log", delete=False)
        log_path = log_handle.name
        log_handle.close()
        command = [server_binary]
        command.extend(
            self._build_llama_server_command(
                model_path=model_path,
                ctx_size=int(profile_spec["ctx_size"]),
                request=request,
                host="127.0.0.1",
                port=published_port,
            )
        )
        effective_prompt = str(profile_spec["prompt"])
        chat_messages, prompt_transform = _prepare_llama_server_chat(request, effective_prompt)
        monitor = _start_gpu_monitor()
        started = time.perf_counter()
        process = None
        memory_monitor = None
        logs_text = ""
        try:
            with open(log_path, "wb") as log_file:
                process = subprocess.Popen(
                    command,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                )
            memory_monitor = _start_process_rss_monitor(process.pid)
            base_url, load_time_ms = _wait_for_native_server_ready(process, published_port, started, log_path)
            completion = (
                _stream_server_chat_completion(
                    base_url=base_url,
                    messages=chat_messages,
                    max_tokens=int(profile_spec["max_tokens"]),
                )
                if chat_messages is not None
                else _stream_server_completion(
                    base_url=base_url,
                    prompt=effective_prompt,
                    max_tokens=int(profile_spec["max_tokens"]),
                )
            )
            _validate_direct_answer_server_completion(completion, prompt_transform)
            logs_text = _read_log_file(log_path)
            parsed = _parse_llama_timings(logs_text)
            peak_vram_mb = _stop_gpu_monitor(monitor)
            peak_memory_mb = _stop_process_rss_monitor(memory_monitor)
            memory_allocations = _parse_llama_memory_allocations(logs_text)
            metrics = _metrics_from_server_completion(
                completion=completion,
                parsed_timings=parsed,
                load_time_ms=load_time_ms,
                peak_vram_mb=peak_vram_mb,
            )
            metrics.update(memory_allocations)
            metrics["peak_memory_mb"] = peak_memory_mb
            metrics["peak_memory_measurement_method"] = "process_rss" if peak_memory_mb is not None else None
            return {
                "iteration": iteration,
                "warmup": is_warmup,
                "status": "completed",
                "command": command,
                "duration_seconds": round((load_time_ms + metrics["latency_ms"]) / 1000.0, 4)
                if load_time_ms is not None and metrics.get("latency_ms") is not None
                else round(time.perf_counter() - started, 4),
                "peak_vram_mb": peak_vram_mb,
                "peak_memory_mb": peak_memory_mb,
                "metrics": metrics,
                "parsed_timings": parsed,
                "completion_summary": completion["final_payload"],
                "prompt_transform": prompt_transform,
                "log_tail": logs_text.splitlines()[-40:],
            }
        except Exception as exc:
            logs_text = logs_text or _read_log_file(log_path)
            return {
                "iteration": iteration,
                "warmup": is_warmup,
                "status": "failed",
                "command": command,
                "duration_seconds": round(time.perf_counter() - started, 4),
                "peak_vram_mb": _stop_gpu_monitor(monitor),
                "peak_memory_mb": _stop_process_rss_monitor(memory_monitor),
                "error": str(exc),
                "prompt_transform": prompt_transform,
                "log_tail": logs_text.splitlines()[-40:],
            }
        finally:
            _stop_process(process)
            try:
                os.unlink(log_path)
            except OSError:
                pass

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

    def _native_completion_path(self, request: RunRequest) -> str:
        """Resolve the non-interactive generation binary paired with llama-cli.

        New llama.cpp builds auto-enable conversation mode in ``llama-cli`` for
        chat-template models. Its banner, echoed prompt, and interactive markers
        are stdout, so they cannot be distinguished from a model completion after
        the fact. ``llama-completion`` is the supported subprocess protocol.
        """
        cli_path = self._native_command_path(request)
        if os.path.basename(cli_path) in ("llama-completion", "llama-completion.exe"):
            return cli_path
        suffix = ".exe" if cli_path.lower().endswith(".exe") else ""
        sibling = os.path.join(os.path.dirname(cli_path), "llama-completion%s" % suffix)
        resolved = shutil.which(sibling) or shutil.which("llama-completion%s" % suffix)
        if resolved:
            return resolved
        raise RuntimeError(
            "llama.cpp generation protocol requires llama-completion beside llama-cli; "
            "interactive llama-cli output is not safe to score."
        )

    def _build_llama_server_command(
        self,
        model_path: str,
        ctx_size: int,
        request: RunRequest,
        host: str = "0.0.0.0",
        port: int = _DEFAULT_SERVER_PORT,
    ) -> List[str]:
        command = [
            "-m",
            model_path,
            "-c",
            str(ctx_size),
            "--host",
            host,
            "--port",
            str(port),
            "--perf",
            "--no-warmup",
            "--log-verbosity",
            "4",
            "-np",
            "1",
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

    def _perplexity_context(self) -> Dict[str, object]:
        return {
            "corpus_id": _PERPLEXITY_CORPUS_ID,
            "corpus_revision": _PERPLEXITY_CORPUS_REVISION,
            "corpus_label": "InferGrade Quant Fidelity v1",
            "metric_family": "quantization_fidelity",
            "tool": "llama-perplexity",
            "protocol_id": _PERPLEXITY_PROTOCOL_ID,
            "protocol_parameters": self._perplexity_protocol_parameters(),
            "comparability_key_basis": [
                "model_family",
                "checkpoint",
                "tokenizer_id",
                "corpus_id",
                "corpus_revision",
                "protocol_id",
            ],
            "interpretation": "Lower perplexity is a same-family quant-fidelity signal on the pinned corpus and protocol; it is not general model quality or task capability.",
        }

    def _perplexity_protocol_parameters(self) -> Dict[str, object]:
        return {
            "ctx_size": _PERPLEXITY_CONTEXT_SIZE,
            "stride": _PERPLEXITY_STRIDE,
            "ppl_output_type": _PERPLEXITY_OUTPUT_TYPE,
            "threads": 4,
            "warmup": False,
        }

    def _perplexity_comparability_key(self, request: RunRequest = None) -> str:
        if request is None:
            return "pending_subject:%s:%s:%s" % (
                _PERPLEXITY_CORPUS_ID,
                _PERPLEXITY_CORPUS_REVISION,
                _PERPLEXITY_PROTOCOL_ID,
            )
        tokenizer_id = "%s_default" % re.sub(r"[^a-z0-9]+", "_", request.model.split("/")[-1].lower()).strip("_")
        return stable_hash(
            {
                "model_ref": request.model,
                "tokenizer_id": tokenizer_id,
                "corpus_id": _PERPLEXITY_CORPUS_ID,
                "corpus_revision": _PERPLEXITY_CORPUS_REVISION,
                "protocol_id": _PERPLEXITY_PROTOCOL_ID,
                "protocol_parameters": self._perplexity_protocol_parameters(),
            },
            length=24,
        )

    def _run_perplexity(self, request: RunRequest, model_path: str) -> Dict[str, object]:
        corpus_handle = tempfile.NamedTemporaryFile(prefix="infergrade-ppl-", suffix=".txt", delete=False)
        corpus_path = corpus_handle.name
        corpus_handle.close()
        with open(corpus_path, "w", encoding="utf-8") as handle:
            handle.write(_PERPLEXITY_CORPUS_TEXT)
        try:
            if request.execution_mode == "local_native":
                command = [self._native_perplexity_path(request)]
                command.extend(
                    self._build_llama_perplexity_command(
                        model_path=model_path,
                        corpus_path=corpus_path,
                        request=request,
                    )
                )
            else:
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
                    "sh",
                    "-v",
                    "%s:/models:ro" % model_dir,
                    "-v",
                    "%s:/corpus.txt:ro" % corpus_path,
                ]
                if shutil.which("nvidia-smi") is not None:
                    command.extend(["--gpus", "all"])
                command.extend(
                    [
                        self._image_name(request),
                        "-lc",
                        " ".join(
                            [
                                shlex.quote("/opt/llama.cpp/build/bin/llama-perplexity"),
                                *[
                                    shlex.quote(part)
                                    for part in self._build_llama_perplexity_command(
                                        model_path=container_model_path,
                                        corpus_path="/corpus.txt",
                                        request=request,
                                    )
                                ],
                            ]
                        ),
                    ]
                )
            started = time.perf_counter()
            completed = subprocess.run(command, capture_output=True)
            stdout = _decode_utf8_lossy(completed.stdout)
            stderr = _decode_utf8_lossy(completed.stderr)
            raw_log = "%s\n%s" % (stdout, stderr)
            if completed.returncode != 0:
                raise RuntimeError((raw_log or "llama.cpp perplexity failed").strip())
            parsed = _parse_perplexity_output(raw_log)
            if parsed.get("perplexity") is None:
                raise RuntimeError("llama.cpp perplexity output did not include a final estimate.")
            return {
                "command": command,
                "perplexity": parsed.get("perplexity"),
                "stderr": parsed.get("stderr"),
                "corpus_token_count": parsed.get("corpus_token_count"),
                "corpus_byte_count": len(_PERPLEXITY_CORPUS_TEXT.encode("utf-8")),
                "duration_seconds": parsed.get("duration_seconds") or round(time.perf_counter() - started, 4),
                "evaluation_backend": "llama-perplexity",
                "log_tail": raw_log.splitlines()[-40:],
            }
        finally:
            try:
                os.unlink(corpus_path)
            except OSError:
                pass

    def _build_llama_perplexity_command(
        self,
        model_path: str,
        corpus_path: str,
        request: RunRequest,
    ) -> List[str]:
        command = [
            "-m",
            model_path,
            "-f",
            corpus_path,
            "-c",
            str(_PERPLEXITY_CONTEXT_SIZE),
            "--ppl-output-type",
            str(_PERPLEXITY_OUTPUT_TYPE),
            "--ppl-stride",
            str(_PERPLEXITY_STRIDE),
            "--threads",
            "4",
            "--no-warmup",
        ]
        command.extend(request.backend_flags)
        return command


def _llama_generation_protocol_error(text: str, max_tokens: int, output_tokens: Optional[int]) -> Optional[str]:
    """Identify runtime UI/protocol output that must not be scored as model text."""
    lowered = text.lower()
    if "available commands:" in lowered or ("loading model..." in lowered and "\n> " in text):
        return (
            "llama.cpp generation protocol failure: interactive llama-cli output "
            "contaminated the completion; use llama-completion for non-interactive generation."
        )
    unfinished_thinking = (
        ("[start thinking]" in lowered and "[end thinking]" not in lowered)
        or ("<think>" in lowered and "</think>" not in lowered)
    )
    # llama.cpp timing logs commonly report generated runs as n_predict - 1
    # because the terminal token is accounted separately.
    exhausted_budget = output_tokens is not None and output_tokens >= max(1, max_tokens - 1)
    if unfinished_thinking and exhausted_budget:
        return (
            "llama.cpp generation protocol failure: response exhausted max_tokens "
            "inside an unfinished thinking block before a scorable answer."
        )
    return None


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
            match = _TOTAL_TIME_TOKENS_RE.search(line)
            if match:
                payload["total_time_tokens"] = round(float(match.group(1)), 4)
            continue
        if "prompt:" in lowered and "generation:" in lowered:
            match = _SUMMARY_TPS_RE.search(line)
            if match:
                payload["prompt_tokens_per_second"] = round(float(match.group(1)), 4)
                payload["eval_tokens_per_second"] = round(float(match.group(2)), 4)
    return payload


def _parse_perplexity_output(raw_log: str) -> Dict[str, float]:
    payload: Dict[str, float] = {}
    for line in raw_log.splitlines():
        match = _PERPLEXITY_RE.search(line)
        if match:
            payload["perplexity"] = round(float(match.group(1)), 6)
            payload["stderr"] = round(float(match.group(2)), 6)
        match = _TOTAL_TIME_RE.search(line)
        if match:
            payload["duration_seconds"] = round(float(match.group(1)) / 1000.0, 4)
        match = _TOTAL_TIME_TOKENS_RE.search(line)
        if match:
            payload["corpus_token_count"] = int(float(match.group(1)))
        match = _PERPLEXITY_TOKENIZATION_RE.search(line)
        if match and "corpus_token_count" not in payload:
            payload["corpus_token_count"] = int(float(match.group(1)))
    return payload


def _bits_per_byte(perplexity: Any, token_count: Any, byte_count: Any) -> Optional[float]:
    try:
        ppl = float(perplexity)
        tokens = float(token_count)
        bytes_scored = float(byte_count)
    except (TypeError, ValueError):
        return None
    if ppl <= 0 or tokens <= 0 or bytes_scored <= 0:
        return None
    return round(math.log(ppl, 2) * tokens / bytes_scored, 6)


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


def _whole_token_count(value: Any) -> Optional[int]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0 or not parsed.is_integer():
        return None
    return int(parsed)


def _bounded_deployment_run_count(
    value: Optional[int],
    default: int,
    minimum: int,
    maximum: int,
    field_name: str,
) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > maximum:
        raise ValueError("%s must be an integer from %d to %d" % (field_name, minimum, maximum))
    return value


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


def _start_gpu_monitor() -> Dict[str, object]:
    baseline_vram_mb = sample_total_gpu_memory_used_mb()
    stop_event = threading.Event()
    samples: List[float] = []

    def monitor() -> None:
        while not stop_event.is_set():
            sample = sample_total_gpu_memory_used_mb()
            if sample is not None:
                samples.append(sample)
            stop_event.wait(0.1)

    thread = None
    if baseline_vram_mb is not None:
        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
    return {
        "baseline_vram_mb": baseline_vram_mb,
        "samples": samples,
        "stop_event": stop_event,
        "thread": thread,
    }


def _stop_gpu_monitor(handle: Dict[str, object]) -> Optional[float]:
    baseline_vram_mb = handle.get("baseline_vram_mb")
    if baseline_vram_mb is None:
        return None
    stop_event = handle["stop_event"]
    stop_event.set()
    thread = handle.get("thread")
    if thread is not None and thread.is_alive():
        thread.join(timeout=0.2)
    samples = handle.get("samples") or []
    if not samples:
        return None
    return round(max(0.0, max(samples) - baseline_vram_mb), 2)


def _resolve_published_port(container_name: str, container_port: int) -> int:
    completed = subprocess.run(
        ["docker", "port", container_name, "%s/tcp" % container_port],
        capture_output=True,
    )
    stdout = _decode_utf8_lossy(completed.stdout)
    stderr = _decode_utf8_lossy(completed.stderr)
    if completed.returncode != 0:
        message = (stderr or stdout or "").strip()
        raise RuntimeError("Failed to inspect published port for %s: %s" % (container_name, message or "unknown error"))
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("Docker did not report a published port for %s." % container_name)
    first = lines[0]
    if ":" not in first:
        raise RuntimeError("Unexpected docker port output for %s: %s" % (container_name, first))
    return int(first.rsplit(":", 1)[1])


def _wait_for_server_ready(container_name: str, published_port: int, started_at: float) -> Tuple[str, float]:
    deadline = started_at + _SERVER_READY_TIMEOUT_SECONDS
    last_error: Optional[str] = None
    while time.perf_counter() < deadline:
        if not _container_is_running(container_name):
            logs = _fetch_container_logs(container_name)
            raise RuntimeError("llama.cpp server exited before becoming ready. %s" % (logs or ""))
        for base_url in _server_base_url_candidates(published_port):
            try:
                with urllib_request.urlopen("%s/health" % base_url, timeout=1.0) as response:
                    if response.status == 200:
                        return base_url, round((time.perf_counter() - started_at) * 1000.0, 2)
            except Exception as exc:
                last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(
        "Timed out waiting for llama.cpp server readiness on published port %s. %s"
        % (published_port, last_error or "")
    )


def _wait_for_native_server_ready(process: subprocess.Popen, port: int, started_at: float, log_path: str) -> Tuple[str, float]:
    deadline = started_at + _SERVER_READY_TIMEOUT_SECONDS
    last_error: Optional[str] = None
    base_url = "http://127.0.0.1:%s" % port
    while time.perf_counter() < deadline:
        if process.poll() is not None:
            logs = _read_log_file(log_path)
            raise RuntimeError("Native llama.cpp server exited before becoming ready. %s" % (logs or ""))
        try:
            with urllib_request.urlopen("%s/health" % base_url, timeout=1.0) as response:
                if response.status == 200:
                    return base_url, round((time.perf_counter() - started_at) * 1000.0, 2)
        except Exception as exc:
            last_error = str(exc)
        time.sleep(0.2)
    raise RuntimeError(
        "Timed out waiting for native llama.cpp server readiness on port %s. %s"
        % (port, last_error or "")
    )


def _server_base_url_candidates(published_port: int) -> List[str]:
    candidates = ["http://127.0.0.1:%s" % published_port]
    host_alias = env_value("INFERGRADE_DOCKER_HOST_ALIAS", "", "")
    if host_alias:
        candidates.append("http://%s:%s" % (host_alias, published_port))
    candidates.append("http://host.docker.internal:%s" % published_port)
    deduped = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped


def _container_is_running(container_name: str) -> bool:
    completed = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
        capture_output=True,
    )
    stdout = _decode_utf8_lossy(completed.stdout)
    return completed.returncode == 0 and stdout.strip().lower() == "true"


def _fetch_container_logs(container_name: str) -> str:
    completed = subprocess.run(
        ["docker", "logs", container_name],
        capture_output=True,
    )
    stdout = _decode_utf8_lossy(completed.stdout)
    stderr = _decode_utf8_lossy(completed.stderr)
    return ("%s\n%s" % (stdout, stderr)).strip()


def _read_log_file(path: str) -> str:
    try:
        with open(path, "rb") as handle:
            return _decode_utf8_lossy(handle.read())
    except OSError:
        return ""


def _memory_bytes(value: float, unit: str) -> int:
    multipliers = {
        "kb": 1000,
        "kib": 1024,
        "mb": 1000 ** 2,
        "mib": 1024 ** 2,
        "gb": 1000 ** 3,
        "gib": 1024 ** 3,
        "tb": 1000 ** 4,
        "tib": 1024 ** 4,
    }
    return int(round(value * multipliers[unit.lower()]))


def _first_nonempty(values: List[object]) -> Optional[object]:
    return next((value for value in values if value not in (None, "")), None)


def _parse_llama_memory_allocations(logs_text: str) -> Dict[str, Optional[int]]:
    """Parse llama.cpp's own model and KV allocations without calling them RSS/VRAM."""
    model_buffers = []
    kv_buffers = []
    for match in _MEMORY_BUFFER_RE.finditer(str(logs_text or "")):
        size_bytes = _memory_bytes(float(match.group("value")), match.group("unit"))
        label = match.group("label").lower()
        if "kv" in label:
            kv_buffers.append(size_bytes)
        elif "model" in label:
            model_buffers.append(size_bytes)
    return {
        "model_buffer_bytes": sum(model_buffers) if model_buffers else None,
        "kv_cache_bytes": sum(kv_buffers) if kv_buffers else None,
    }


def _sample_process_rss_mb(pid: int) -> Optional[float]:
    """Return process RSS in MiB. This is working-set evidence, not GPU-only memory."""
    try:
        completed = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if completed.returncode != 0 or not completed.stdout.strip():
            return None
        return round(float(completed.stdout.strip().splitlines()[0]) / 1024.0, 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _start_process_rss_monitor(pid: int) -> Dict[str, object]:
    samples: List[float] = []
    stop_event = threading.Event()

    def monitor() -> None:
        while not stop_event.is_set():
            sample = _sample_process_rss_mb(pid)
            if sample is not None:
                samples.append(sample)
            stop_event.wait(0.1)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    return {"stop_event": stop_event, "thread": thread, "samples": samples}


def _stop_process_rss_monitor(handle: Optional[Dict[str, object]]) -> Optional[float]:
    if not handle:
        return None
    handle["stop_event"].set()
    thread = handle.get("thread")
    if thread is not None and thread.is_alive():
        thread.join(timeout=0.3)
    samples = handle.get("samples") or []
    return round(max(samples), 2) if samples else None


def _sample_container_cgroup_memory(container_name: str) -> Tuple[Optional[float], Optional[str]]:
    """Read container-scoped memory from cgroup counters inside the container.

    Kernel peak counters are preferred. A sampled current counter is retained as
    an honest fallback for cgroup layouts that do not expose a peak file.
    """
    script = (
        "if [ -r /sys/fs/cgroup/memory.peak ]; then "
        "printf 'container_cgroup_v2_peak:'; cat /sys/fs/cgroup/memory.peak; "
        "elif [ -r /sys/fs/cgroup/memory/memory.max_usage_in_bytes ]; then "
        "printf 'container_cgroup_v1_max_usage:'; cat /sys/fs/cgroup/memory/memory.max_usage_in_bytes; "
        "elif [ -r /sys/fs/cgroup/memory.current ]; then "
        "printf 'container_cgroup_current_sampled:'; cat /sys/fs/cgroup/memory.current; "
        "elif [ -r /sys/fs/cgroup/memory/memory.usage_in_bytes ]; then "
        "printf 'container_cgroup_current_sampled:'; cat /sys/fs/cgroup/memory/memory.usage_in_bytes; "
        "else exit 1; fi"
    )
    try:
        completed = subprocess.run(
            ["docker", "exec", container_name, "sh", "-c", script],
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if completed.returncode != 0 or ":" not in completed.stdout:
            return None, None
        method, raw_bytes = completed.stdout.strip().split(":", 1)
        value = int(raw_bytes.strip())
        if value <= 0:
            return None, None
        return round(value / float(1024 ** 2), 2), method
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, None


def _start_container_memory_monitor(container_name: str) -> Dict[str, object]:
    samples: List[Tuple[float, str]] = []
    stop_event = threading.Event()
    initial_value, initial_method = _sample_container_cgroup_memory(container_name)
    if initial_value is not None and initial_method:
        samples.append((initial_value, initial_method))
    if initial_method in {"container_cgroup_v2_peak", "container_cgroup_v1_max_usage"}:
        # Kernel peak counters are monotonic for the container lifetime. Reading
        # once at stop is exact and avoids perturbing the benchmark with polling.
        return {
            "stop_event": stop_event,
            "thread": None,
            "samples": samples,
            "container_name": container_name,
            "polling": False,
        }

    def monitor() -> None:
        while not stop_event.is_set():
            value, method = _sample_container_cgroup_memory(container_name)
            if value is not None and method:
                samples.append((value, method))
                if method in {"container_cgroup_v2_peak", "container_cgroup_v1_max_usage"}:
                    break
            stop_event.wait(_CONTAINER_MEMORY_SAMPLE_INTERVAL_SECONDS)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    return {
        "stop_event": stop_event,
        "thread": thread,
        "samples": samples,
        "container_name": container_name,
        "polling": True,
    }


def _stop_container_memory_monitor(
    handle: Optional[Dict[str, object]],
) -> Tuple[Optional[float], Optional[str]]:
    if not handle:
        return None, None
    handle["stop_event"].set()
    thread = handle.get("thread")
    if thread is not None and thread.is_alive():
        thread.join(timeout=1.3)
    final_sample = _sample_container_cgroup_memory(str(handle.get("container_name") or ""))
    samples = list(handle.get("samples") or [])
    if final_sample[0] is not None and final_sample[1]:
        samples.append(final_sample)
    if not samples:
        return None, None
    value, method = max(samples, key=lambda item: item[0])
    return round(value, 2), method


def _stop_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "stop", container_name],
        capture_output=True,
    )


def _stop_process(process: Optional[subprocess.Popen]) -> None:
    if process is None:
        return
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def _find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _stream_server_completion(base_url: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    payload = {
        "prompt": prompt,
        "n_predict": max_tokens,
        "temperature": 0,
        "top_p": 1,
        "seed": 0,
        "stream": True,
        "cache_prompt": False,
    }
    request = urllib_request.Request(
        "%s/completion" % base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_ms: Optional[float] = None
    final_payload: Optional[Dict[str, Any]] = None
    content_chunks: List[str] = []
    try:
        with urllib_request.urlopen(request, timeout=_SERVER_REQUEST_TIMEOUT_SECONDS) as response:
            while True:
                line = response.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text or not text.startswith("data:"):
                    continue
                try:
                    chunk_payload = json.loads(text[len("data:") :].strip())
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Malformed llama.cpp streaming JSON: %s" % text) from exc
                if (
                    chunk_payload.get("tokens_predicted", 0) > 0
                    and not chunk_payload.get("stop")
                    and first_token_ms is None
                ):
                    first_token_ms = round((time.perf_counter() - started) * 1000.0, 2)
                if chunk_payload.get("content"):
                    content_chunks.append(chunk_payload["content"])
                if chunk_payload.get("stop"):
                    final_payload = chunk_payload
    except urllib_error.HTTPError as exc:
        body = _decode_utf8_lossy(exc.read())
        raise RuntimeError("llama.cpp completion request failed: %s %s" % (exc.code, body))
    if final_payload is None:
        raise RuntimeError("llama.cpp streaming completion ended without a final payload.")
    return {
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "first_token_ms": first_token_ms,
        "text": "".join(content_chunks).strip(),
        "final_payload": final_payload,
    }


def _stream_server_chat_completion(base_url: str, messages: List[Dict[str, str]], max_tokens: int) -> Dict[str, Any]:
    """Stream a templated chat completion while retaining llama.cpp timing extensions."""
    payload = {
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
        "top_p": 1,
        "seed": 0,
        "stream": True,
        "cache_prompt": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib_request.Request(
        "%s/v1/chat/completions" % base_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    first_token_ms: Optional[float] = None
    final_payload: Dict[str, Any] = {}
    content_chunks: List[str] = []
    finish_reason: Optional[str] = None
    try:
        with urllib_request.urlopen(request, timeout=_SERVER_REQUEST_TIMEOUT_SECONDS) as response:
            while True:
                line = response.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text or not text.startswith("data:"):
                    continue
                event = text[len("data:") :].strip()
                if event == "[DONE]":
                    break
                try:
                    chunk_payload = json.loads(event)
                except json.JSONDecodeError as exc:
                    raise RuntimeError("Malformed llama.cpp chat streaming JSON: %s" % text) from exc
                if chunk_payload.get("timings"):
                    final_payload["timings"] = chunk_payload["timings"]
                if chunk_payload.get("usage"):
                    final_payload["usage"] = chunk_payload["usage"]
                choices = list(chunk_payload.get("choices") or [])
                if not choices:
                    continue
                choice = choices[0]
                delta = dict(choice.get("delta") or {})
                content = delta.get("content")
                if content:
                    if first_token_ms is None:
                        first_token_ms = round((time.perf_counter() - started) * 1000.0, 2)
                    content_chunks.append(str(content))
                if choice.get("finish_reason") is not None:
                    finish_reason = str(choice.get("finish_reason"))
    except urllib_error.HTTPError as exc:
        body = _decode_utf8_lossy(exc.read())
        raise RuntimeError("llama.cpp chat completion request failed: %s %s" % (exc.code, body))
    if finish_reason is None:
        raise RuntimeError("llama.cpp streaming chat completion ended without a finish reason.")
    timings = dict(final_payload.get("timings") or {})
    usage = dict(final_payload.get("usage") or {})
    predicted_n = usage.get("completion_tokens") or timings.get("predicted_n")
    final_payload.update(
        {
            "stop": True,
            "stop_type": finish_reason,
            "tokens_predicted": predicted_n,
            "content": "".join(content_chunks),
            "protocol": "openai_chat_completions",
        }
    )
    return {
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "first_token_ms": first_token_ms,
        "text": "".join(content_chunks).strip(),
        "final_payload": final_payload,
    }


def _validate_direct_answer_server_completion(
    completion: Dict[str, Any],
    prompt_transform: Optional[Dict[str, str]],
) -> None:
    """Reject hidden-output samples while retaining honest fixed-budget throughput measurements."""
    if not prompt_transform:
        return
    if not str(completion.get("text") or "").strip():
        raise RuntimeError("Direct-answer deployment completed without visible answer content")


def _metrics_from_server_completion(
    completion: Dict[str, Any],
    parsed_timings: Dict[str, float],
    load_time_ms: Optional[float],
    peak_vram_mb: Optional[float],
) -> Dict[str, Any]:
    final_payload = completion["final_payload"]
    timings = final_payload.get("timings") or {}
    prompt_ms = _coerce_float(timings.get("prompt_ms")) or parsed_timings.get("prompt_eval_time_ms")
    predicted_ms = _coerce_float(timings.get("predicted_ms")) or parsed_timings.get("eval_time_ms")
    predicted_n = _coerce_float(timings.get("predicted_n")) or parsed_timings.get("eval_tokens")
    prompt_tps = _coerce_float(timings.get("prompt_per_second")) or parsed_timings.get("prompt_tokens_per_second")
    decode_tps = _coerce_float(timings.get("predicted_per_second")) or parsed_timings.get("eval_tokens_per_second")
    ttft_ms = completion.get("first_token_ms") or _compute_ttft_ms(
        {
            "prompt_eval_time_ms": prompt_ms,
            "eval_time_ms": predicted_ms,
            "eval_tokens": predicted_n,
        }
    )
    compute_total_ms = None
    if prompt_ms is not None and predicted_ms is not None:
        compute_total_ms = round(prompt_ms + predicted_ms, 2)
    latency_ms = completion.get("elapsed_ms") or compute_total_ms
    if latency_ms is None:
        latency_ms = parsed_timings.get("total_time_ms")
    stop_type = str(final_payload.get("stop_type") or "").lower()
    token_budget_exhausted = stop_type in {"limit", "length", "max_tokens"}
    return {
        "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "prompt_tokens_per_second": round(prompt_tps, 4) if prompt_tps is not None else None,
        "decode_tokens_per_second": round(decode_tps, 4) if decode_tps is not None else _safe_tokens_per_second(parsed_timings),
        "load_time_ms": round(load_time_ms, 2) if load_time_ms is not None else parsed_timings.get("load_time_ms"),
        "peak_vram_mb": peak_vram_mb,
        "prompt_eval_time_ms": round(prompt_ms, 4) if prompt_ms is not None else None,
        "eval_time_ms": round(predicted_ms, 4) if predicted_ms is not None else None,
        "output_tokens": int(predicted_n) if predicted_n is not None else None,
        "stop_type": stop_type or None,
        "natural_stop": bool(stop_type) and not token_budget_exhausted,
        "token_budget_exhausted": token_budget_exhausted,
    }


def _native_runtime_source(request: RunRequest = None) -> str:
    if request and (request.llama_cpp_cli_path or request.llama_cpp_server_path or request.llama_cpp_perplexity_path):
        return "custom_path"
    if any(os.environ.get(name) for name in ("INFERGRADE_LLAMA_CPP_CLI", "INFERGRADE_LLAMA_CPP_SERVER", "INFERGRADE_LLAMA_CPP_PERPLEXITY")):
        return "environment_path"
    if selected_llama_cpp_runtime():
        return "managed_runtime"
    return "system_path"


def _resolve_native_binary(explicit: Optional[str], env_name: str, default: str, label: str) -> str:
    binary = explicit or env_value(env_name, "", "")
    if not binary:
        managed = managed_llama_cpp_binary_path({"CLI": "cli", "server": "server", "perplexity": "perplexity"}.get(label, label))
        if managed:
            return managed
        binary = default
    resolved = shutil.which(binary)
    if not resolved:
        raise RuntimeError(
            "Native llama.cpp %s binary is not available: %s. Set %s or pass the matching --llama-cpp-* path flag."
            % (label, binary, env_name)
        )
    return resolved


def _try_resolve_native_binary(explicit: Optional[str], env_name: str, default: str) -> Optional[str]:
    binary = explicit or env_value(env_name, "", "")
    if binary:
        return shutil.which(binary)
    return managed_llama_cpp_binary_path("perplexity") or shutil.which(default)


def _read_exact(handle, length: int) -> bytes:
    payload = handle.read(length)
    if len(payload) != length:
        raise ValueError("Unexpected end of GGUF metadata.")
    return payload


def _read_u32(handle) -> int:
    return struct.unpack("<I", _read_exact(handle, 4))[0]


def _read_u64(handle) -> int:
    return struct.unpack("<Q", _read_exact(handle, 8))[0]


def _read_gguf_string(handle) -> str:
    length = _read_u64(handle)
    if length > 1024 * 1024:
        raise ValueError("GGUF metadata string is unexpectedly large.")
    return _read_exact(handle, length).decode("utf-8", errors="replace")


def _skip_gguf_value(handle, value_type: int) -> None:
    fixed_width = {
        0: 1,  # uint8
        1: 1,  # int8
        2: 2,  # uint16
        3: 2,  # int16
        4: 4,  # uint32
        5: 4,  # int32
        6: 4,  # float32
        7: 1,  # bool
        10: 8,  # uint64
        11: 8,  # int64
        12: 8,  # float64
    }
    if value_type in fixed_width:
        _read_exact(handle, fixed_width[value_type])
        return
    if value_type == 8:
        _read_gguf_string(handle)
        return
    if value_type == 9:
        item_type = _read_u32(handle)
        count = _read_u64(handle)
        if count > 100000:
            raise ValueError("GGUF metadata array is unexpectedly large.")
        for _ in range(count):
            _skip_gguf_value(handle, item_type)
        return
    raise ValueError("Unsupported GGUF metadata value type: %s" % value_type)


def _read_gguf_architecture(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as handle:
            if _read_exact(handle, 4) != b"GGUF":
                return None
            _read_u32(handle)  # version
            _read_u64(handle)  # tensor_count
            metadata_count = _read_u64(handle)
            if metadata_count > 100000:
                return None
            for _ in range(metadata_count):
                key = _read_gguf_string(handle)
                value_type = _read_u32(handle)
                if key == "general.architecture" and value_type == 8:
                    return _normalize_architecture(_read_gguf_string(handle))
                _skip_gguf_value(handle, value_type)
    except (OSError, struct.error, UnicodeDecodeError, ValueError):
        return None
    return None


def _normalize_architecture(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "").replace("_", "")


def _prepare_llama_prompt(
    request: RunRequest,
    prompt: str,
    placement: str = "append",
) -> Tuple[str, Optional[Dict[str, str]]]:
    """Apply an explicit, versioned direct-answer policy to Qwen 3-family prompts."""
    raw = str(prompt or "")
    if request.generation_preset != DIRECT_ANSWER_GENERATION_PRESET:
        return raw, None
    architecture = _infer_llama_cpp_architecture(request)
    if not str(architecture or "").startswith("qwen3"):
        return raw, None
    if any(line.strip().lower() == "/no_think" for line in raw.splitlines()):
        return raw, {
            "id": "qwen_no_think_directive_v1",
            "policy_id": DIRECT_ANSWER_GENERATION_PRESET,
            "state": "already_present",
        }
    if placement == "final_user_turn":
        assistant_marker = "\nAssistant:"
        marker_index = raw.rfind(assistant_marker)
        if marker_index >= 0:
            effective = raw[:marker_index].rstrip() + "\n/no_think" + raw[marker_index:]
            state = "inserted_before_final_assistant_turn"
        else:
            effective = raw.rstrip() + "\n/no_think"
            state = "appended_fallback_no_assistant_turn"
    elif placement == "append":
        effective = raw.rstrip() + "\n/no_think"
        state = "appended"
    else:
        raise ValueError("Unsupported llama.cpp prompt transform placement: %s" % placement)
    return effective, {
        "id": "qwen_no_think_directive_v1",
        "policy_id": DIRECT_ANSWER_GENERATION_PRESET,
        "state": state,
        "placement": placement,
    }


def _prepare_llama_server_chat(
    request: RunRequest,
    prompt: str,
) -> Tuple[Optional[List[Dict[str, str]]], Optional[Dict[str, str]]]:
    """Use llama-server chat templating for explicit direct-answer protocols."""
    if request.generation_preset != DIRECT_ANSWER_GENERATION_PRESET:
        return None, None
    architecture = str(_infer_llama_cpp_architecture(request) or "")
    if not (architecture.startswith("qwen3") or architecture == "gemma4"):
        return None, None
    transform_id = (
        "gemma4_chat_template_disable_thinking_v1"
        if architecture == "gemma4"
        else "qwen_chat_template_disable_thinking_v1"
    )
    raw = str(prompt or "")
    assistant_marker = "\nAssistant:"
    user_marker = "\nUser:"
    assistant_index = raw.rfind(assistant_marker)
    user_index = raw.rfind(user_marker, 0, assistant_index if assistant_index >= 0 else len(raw))
    if user_index < 0 or assistant_index < 0 or user_index >= assistant_index:
        if not raw.strip():
            raise RuntimeError("Direct-answer prompt is empty")
        return [{"role": "user", "content": raw.strip()}], {
            "id": transform_id,
            "policy_id": DIRECT_ANSWER_GENERATION_PRESET,
            "state": "chat_template_enable_thinking_false_single_user_prompt",
            "placement": "structured_messages",
        }
    system_content = raw[:user_index].strip()
    user_content = raw[user_index + len(user_marker) : assistant_index].strip()
    if not user_content:
        raise RuntimeError("Direct-answer deployment prompt has an empty final user turn")
    messages: List[Dict[str, str]] = []
    if system_content:
        messages.append({"role": "system", "content": system_content})
    messages.append({"role": "user", "content": user_content})
    return messages, {
        "id": transform_id,
        "policy_id": DIRECT_ANSWER_GENERATION_PRESET,
        "state": "chat_template_enable_thinking_false",
        "placement": "structured_messages",
    }


def _infer_llama_cpp_architecture(request: RunRequest) -> Optional[str]:
    hints = dict(request.ontology_hints or {})
    explicit = (
        hints.get("architecture")
        or hints.get("model_architecture")
        or hints.get("gguf_architecture")
        or hints.get("llama_cpp_architecture")
    )
    if explicit:
        return _normalize_architecture(str(explicit))

    artifact = request.quant_artifact_resolved_path or request.quant_artifact
    if artifact and os.path.isfile(artifact) and artifact.lower().endswith(".gguf"):
        architecture = _read_gguf_architecture(artifact)
        if architecture:
            return architecture

    candidates = [
        request.model,
        hints.get("family_name"),
        request.quant_artifact_filename,
        request.quant_artifact,
    ]
    for candidate in candidates:
        normalized = re.sub(r"[^a-z0-9]+", "", str(candidate or "").lower())
        if "qwen35" in normalized:
            return "qwen35"
        if "qwen3" in normalized:
            return "qwen3"
        if "gemma4" in normalized:
            return "gemma4"
        if "gemma3" in normalized:
            return "gemma3"
        if "gemma2" in normalized:
            return "gemma2"
    return None


def _uses_native_direct_answer_server(request: RunRequest) -> bool:
    if request.simulate:
        return False
    architecture = str(_infer_llama_cpp_architecture(request) or "")
    return (
        request.execution_mode == "local_native"
        and request.generation_preset == DIRECT_ANSWER_GENERATION_PRESET
        and (
            architecture.startswith("qwen35")
            or _is_qwen36_request(request)
            or architecture == "gemma4"
        )
    )


def _can_reuse_native_capability_server(request: RunRequest) -> bool:
    return not request.simulate and request.execution_mode == "local_native"


def _is_qwen36_request(request: RunRequest) -> bool:
    hints = request.ontology_hints or {}
    candidates = [
        request.model,
        request.quant_artifact,
        request.quant_artifact_filename,
        hints.get("family_name"),
        hints.get("checkpoint_name"),
    ]
    return any("qwen36" in re.sub(r"[^a-z0-9]+", "", str(value or "").lower()) for value in candidates)


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
