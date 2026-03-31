import json
import os
import re
import shutil
import subprocess
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib import error as urllib_error
from urllib import request as urllib_request

from infergrade.adapters.base import BaseAdapter
from infergrade.container_runtime import (
    docker_available,
    sample_total_gpu_memory_used_mb,
)
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
_DEFAULT_SERVER_COMMAND = "llama-server"
_DEFAULT_SERVER_PORT = 8080
_SERVER_READY_TIMEOUT_SECONDS = 180.0
_SERVER_REQUEST_TIMEOUT_SECONDS = 300.0


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

    def run_deployment_profile(
        self,
        request: RunRequest,
        profile_id: str,
        progress_callback: Optional[Callable[[Dict[str, object]], None]] = None,
    ) -> DeploymentExecution:
        if request.simulate:
            return super().run_deployment_profile(request, profile_id, progress_callback=progress_callback)
        if request.execution_mode not in ("local_container", "cloud_container"):
            raise NotImplementedError("Real llama.cpp execution currently supports local_container and cloud_container modes.")
        model_path = self._require_local_gguf_artifact(request)
        profile_spec = self._profile_spec(profile_id, request.use_case)
        warmup_runs = 1 if request.tier == "canary" else 2
        measured_runs = 1 if request.tier == "canary" else 5
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

        monitor = _start_gpu_monitor()
        started = time.perf_counter()
        logs_text = ""
        try:
            completed = subprocess.run(command, capture_output=True, text=True)
            startup_output = (completed.stdout or completed.stderr or "").strip()
            if completed.returncode != 0:
                return {
                    "iteration": iteration,
                    "warmup": is_warmup,
                    "status": "failed",
                    "command": command,
                    "duration_seconds": round(time.perf_counter() - started, 4),
                    "peak_vram_mb": _stop_gpu_monitor(monitor),
                    "error": startup_output or "llama.cpp server container failed to start",
                }

            published_port = _resolve_published_port(container_name, _DEFAULT_SERVER_PORT)
            base_url, load_time_ms = _wait_for_server_ready(
                container_name=container_name,
                published_port=published_port,
                started_at=started,
            )
            completion = _stream_server_completion(
                base_url=base_url,
                prompt=str(profile_spec["prompt"]),
                max_tokens=int(profile_spec["max_tokens"]),
            )
            logs_text = _fetch_container_logs(container_name)
            parsed = _parse_llama_timings(logs_text)
            peak_vram_mb = _stop_gpu_monitor(monitor)
            metrics = _metrics_from_server_completion(
                completion=completion,
                parsed_timings=parsed,
                load_time_ms=load_time_ms,
                peak_vram_mb=peak_vram_mb,
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
                "log_tail": logs_text.splitlines()[-40:],
            }
        finally:
            _stop_container(container_name)

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

    def _build_llama_server_command(
        self,
        model_path: str,
        ctx_size: int,
        request: RunRequest,
    ) -> List[str]:
        command = [
            "-m",
            model_path,
            "-c",
            str(ctx_size),
            "--host",
            "0.0.0.0",
            "--port",
            str(_DEFAULT_SERVER_PORT),
            "--perf",
            "--no-warmup",
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
        text=True,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError("Failed to inspect published port for %s: %s" % (container_name, message or "unknown error"))
    lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
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
        text=True,
    )
    return completed.returncode == 0 and (completed.stdout or "").strip().lower() == "true"


def _fetch_container_logs(container_name: str) -> str:
    completed = subprocess.run(
        ["docker", "logs", container_name],
        capture_output=True,
        text=True,
    )
    return ("%s\n%s" % (completed.stdout or "", completed.stderr or "")).strip()


def _stop_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "stop", container_name],
        capture_output=True,
        text=True,
    )


def _stream_server_completion(base_url: str, prompt: str, max_tokens: int) -> Dict[str, Any]:
    payload = {
        "prompt": prompt,
        "n_predict": max_tokens,
        "temperature": 0,
        "top_p": 1,
        "seed": 0,
        "stream": True,
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
                chunk_payload = json.loads(text[len("data:") :].strip())
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
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("llama.cpp completion request failed: %s %s" % (exc.code, body))
    if final_payload is None:
        raise RuntimeError("llama.cpp streaming completion ended without a final payload.")
    return {
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 2),
        "first_token_ms": first_token_ms,
        "text": "".join(content_chunks).strip(),
        "final_payload": final_payload,
    }


def _metrics_from_server_completion(
    completion: Dict[str, Any],
    parsed_timings: Dict[str, float],
    load_time_ms: Optional[float],
    peak_vram_mb: Optional[float],
) -> Dict[str, Optional[float]]:
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
    return {
        "ttft_ms": round(ttft_ms, 2) if ttft_ms is not None else None,
        "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
        "prompt_tokens_per_second": round(prompt_tps, 4) if prompt_tps is not None else None,
        "decode_tokens_per_second": round(decode_tps, 4) if decode_tps is not None else _safe_tokens_per_second(parsed_timings),
        "load_time_ms": round(load_time_ms, 2) if load_time_ms is not None else parsed_timings.get("load_time_ms"),
        "peak_vram_mb": peak_vram_mb,
        "prompt_eval_time_ms": round(prompt_ms, 4) if prompt_ms is not None else None,
        "eval_time_ms": round(predicted_ms, 4) if predicted_ms is not None else None,
    }


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
