import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class ContainerCommandResult:
    stdout: str
    stderr: str
    returncode: int
    duration_seconds: float
    peak_vram_mb: Optional[float]


def docker_available() -> bool:
    return shutil.which("docker") is not None


def run_command_with_optional_gpu_monitor(command: List[str]) -> ContainerCommandResult:
    peak_vram_mb = None
    baseline_vram_mb = sample_total_gpu_memory_used_mb()
    samples = []
    stop_event = threading.Event()

    def monitor() -> None:
        while not stop_event.is_set():
            sample = sample_total_gpu_memory_used_mb()
            if sample is not None:
                samples.append(sample)
            stop_event.wait(0.1)

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    if baseline_vram_mb is not None:
        monitor_thread.start()

    started = time.perf_counter()
    completed = subprocess.run(command, capture_output=True, text=True)
    duration_seconds = time.perf_counter() - started
    stop_event.set()
    if monitor_thread.is_alive():
        monitor_thread.join(timeout=0.2)

    if baseline_vram_mb is not None and samples:
        peak_vram_mb = max(0.0, max(samples) - baseline_vram_mb)

    return ContainerCommandResult(
        stdout=completed.stdout,
        stderr=completed.stderr,
        returncode=completed.returncode,
        duration_seconds=duration_seconds,
        peak_vram_mb=peak_vram_mb,
    )


def sample_total_gpu_memory_used_mb() -> Optional[float]:
    """Return the total currently used GPU memory across visible NVIDIA devices."""
    if shutil.which("nvidia-smi") is None:
        return None
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
    except Exception:
        return None
    values = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            values.append(float(line))
        except ValueError:
            continue
    if not values:
        return None
    return sum(values)
