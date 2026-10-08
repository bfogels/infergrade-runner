"""Assert reported model names on a real CI host without collecting unique device identifiers."""
import json
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python" / "runner-core" / "src"))
from infergrade.environment import _detect_cpu_model, _detect_machine_model, _windows_model_probe

cpu = _detect_cpu_model()
machine = _detect_machine_model()
receipt = {"schema_version": "infergrade.platform_hardware_identity.v1", "system": platform.system(), "cpu_model": cpu, "machine_model": machine, "identity_available": bool(machine and cpu and cpu != platform.machine())}
print(json.dumps(receipt, sort_keys=True))
if not receipt["identity_available"]:
    if platform.system() == "Windows":
        # Diagnostic repeat cannot repair the failed acceptance receipt above.
        # Fixed queries collect model names only; stderr/error text is discarded.
        print(json.dumps({"diagnostic_only": True, "windows_model_probes": {
            "cpu": _windows_model_probe("Win32_Processor", "Name"),
            "machine": _windows_model_probe("Win32_ComputerSystem", "Model"),
        }}, sort_keys=True))
    raise SystemExit("Reported CPU/machine model unavailable on this CI host")
