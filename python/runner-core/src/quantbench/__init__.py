"""Legacy compatibility package for the InferGrade runner."""

from importlib import import_module
import sys

from infergrade import *  # noqa: F401,F403

_SUBMODULES = [
    "analysis",
    "artifacts",
    "capabilities",
    "cli",
    "constants",
    "container_runtime",
    "doctor",
    "environment",
    "models",
    "ontology",
    "profiles",
    "progress",
    "request",
    "run_configs",
    "runner",
    "templates",
    "transport",
    "utils",
    "validators",
    "worker",
    "adapters",
    "adapters.base",
    "adapters.llama_cpp",
    "adapters.vllm",
]

for _name in _SUBMODULES:
    sys.modules["%s.%s" % (__name__, _name)] = import_module("infergrade.%s" % _name)
