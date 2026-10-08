#!/usr/bin/env python3
"""Verify CUDA's dynamic dependencies without relying on build-host libraries."""
import argparse
import os
from pathlib import Path
import re
import subprocess


BUNDLED_LIBRARIES = ("libcublas.so.12", "libcublasLt.so.12", "libcudart.so.12", "libnccl.so.2")


def verify_package(directory, output):
    directory = Path(directory).resolve()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(directory.glob("libcuda.so*")):
        raise ValueError("The NVIDIA driver must remain host-owned")
    for name in (*BUNDLED_LIBRARIES[:3], "libggml-cuda.so"):
        if not (directory / name).is_file():
            raise ValueError("CUDA package is missing " + name)
    nccl = directory / "libnccl.so.2"
    if nccl.exists() and not (directory / "LICENSE.nccl").is_file():
        raise ValueError("CUDA package is missing LICENSE.nccl")
    env = {key: value for key, value in os.environ.items()
           if key not in {"LD_LIBRARY_PATH", "LD_PRELOAD"}}
    libraries = ("libggml-cuda.so", *BUNDLED_LIBRARIES[:3]) + (("libnccl.so.2",) if nccl.exists() else ())
    for name in libraries:
        result = subprocess.run(["ldd", str(directory / name)], env=env,
                                capture_output=True, text=True, timeout=30)
        detail = result.stdout + result.stderr
        (output / (name + "-ldd.txt")).write_text(detail)
        if result.returncode:
            raise ValueError("Could not inspect CUDA package dependency: " + name + "\n" + detail)
        if re.search(r"^\s*libnccl\.so\.2\s+=>", detail, re.MULTILINE) and not nccl.is_file():
            raise ValueError("CUDA package is missing libnccl.so.2")
        for line in detail.splitlines():
            missing = re.match(r"\s*(\S+)\s+=>\s+not found", line)
            if missing and missing[1] != "libcuda.so.1":
                raise ValueError("CUDA package has an unresolved dependency: " + missing[1])
            resolved = re.match(r"\s*(\S+)\s+=>\s+(\S+)", line)
            if resolved and resolved[1] in BUNDLED_LIBRARIES:
                if Path(resolved[2]).resolve().parent != directory:
                    raise ValueError("CUDA package relies on a host library: " + resolved[1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    verify_package(args.directory, args.output)
