#!/usr/bin/env python3
"""Smoke the packaged installer and pair/start against a local HTTP contract fixture.

Only application release downloads use a local mirror. The managed runtime is
downloaded by the actual Rust installer from its checksum-pinned public asset.
This proves CPU setup and listener handoff, not hosted Hub or NVIDIA execution.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shlex
import subprocess
import threading
import time


def smoke(bundle, output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    mirror = output / "mirror"
    mirror.mkdir()
    # Mirror the freshly built application archive, retaining release checksums.
    (mirror / "SHA256SUMS").write_bytes((bundle / "SHA256SUMS.headless").read_bytes())
    archives = list(bundle.glob("infergrade-runner-*-linux-x86_64.tar.gz"))
    if len(archives) != 1:
        raise ValueError("Expected exactly one Linux headless package")
    archive = archives[0]
    version = archive.name.removeprefix("infergrade-runner-").removesuffix("-linux-x86_64.tar.gz")
    (mirror / archive.name).symlink_to(archive.resolve())
    shim = output / "download-tools"
    shim.mkdir()
    curl = shim / "curl"
    curl.write_text("#!/usr/bin/python3\nimport pathlib, shutil, sys\n"
                    "args=sys.argv[1:]\n"
                    "name=args[args.index('-o')-1].rsplit('/',1)[-1]\n"
                    "shutil.copyfile(pathlib.Path(" + repr(str(mirror)) + ") / name,args[args.index('-o')+1])\n")
    curl.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if key not in {
        "INFERGRADE_HUB_TOKEN", "INFERGRADE_API_TOKEN", "INFERGRADE_PAIR_CODE", "INFERGRADE_LLAMA_CPP_CLI",
        "INFERGRADE_LLAMA_CPP_SERVER", "LD_LIBRARY_PATH", "PYTHONPATH",
    }}
    env.update(PATH=str(shim) + ":/usr/bin:/bin", INFERGRADE_VERSION=version,
               INFERGRADE_INSTALL_DIR=str(output / "installation"),
               INFERGRADE_BIN_DIR=str(output / "commands"),
               INFERGRADE_CONFIG_DIR=str(output / "profile"),
               INFERGRADE_RUNTIME_CACHE_DIR=str(output / "runtime-cache"))
    for attempt in ("install", "repeat-install"):
        result = subprocess.run(["bash", str(bundle / "install.sh")], env=env,
                                capture_output=True, text=True, timeout=900)
        (output / (attempt + ".txt")).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise ValueError(attempt + " failed: " + result.stderr[-2000:])
    listener_ready = threading.Event()
    observed = []
    api_url = ""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(self.path)
            status = 200
            if self.path == "/api/runner/device-codes":
                response = {"device_code": "local_contract_fixture_secret_123456789",
                            "user_code": "ABCD-EFGH", "verification_uri": api_url + "/connect",
                            "expires_in": 60, "interval": 1}
            elif self.path in {"/v1/runner-pairings/redeem", "/api/runner/device-codes/token"}:
                response = {"runner_profile": {
                    "api_url": api_url, "runner_id": "installer-smoke",
                    "access_token": "qbhr_local_contract_fixture", "label": "Installer smoke",
                    "preferred_execution_mode": "local_native", "runner_kind": "local_listener",
                }}
            elif self.headers.get("Authorization") != "Bearer qbhr_local_contract_fixture":
                status, response = 403, {"detail": "paired profile was not used"}
            elif self.path == "/v1/runners/register":
                response = {"runner": {"runner_id": payload.get("runner_id")}}
                (output / "registration.json").write_text(json.dumps(payload, indent=2))
            elif self.path.endswith("/heartbeat"):
                response = {"runner": {"runner_id": "installer-smoke"}}
                if payload.get("status") == "listening":
                    listener_ready.set()
            else:
                response = {"run": None}
            data = json.dumps(response).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    api_url = "http://127.0.0.1:%s" % server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    command = output / "commands/infergrade"
    try:
        for flow, flags in (("pasted-code", ["--pair-code-stdin"]), ("device-code", [])):
            listener_ready.clear()
            log = output / (flow + "-pair-start.txt")
            with log.open("w") as handle:
                process = subprocess.Popen([str(command), "pair", "--start", "--api-url", api_url] + flags,
                                           env=env, stdin=subprocess.PIPE, stdout=handle, stderr=handle, text=True)
                try:
                    if flags:
                        process.stdin.write("igrp_local_contract_fixture\n")
                    process.stdin.close()
                    deadline = time.monotonic() + 60
                    while not listener_ready.wait(0.2):
                        if process.poll() is not None or time.monotonic() > deadline:
                            raise ValueError(flow + " installed pair --start did not listen: " + log.read_text()[-2000:])
                finally:
                    if process.poll() is None:
                        process.terminate()
                    process.wait(timeout=15)
            registration = json.loads((output / "registration.json").read_text())
            if registration.get("runner_id") != "installer-smoke" or registration.get("execution_modes") != ["local_native"]:
                raise ValueError(flow + " installed listener lost its paired native identity")
            if registration.get("diagnostics", {}).get("blocking_count") != 0:
                raise ValueError(flow + " installed listener reported native readiness blockers")
        if not {"/api/runner/device-codes", "/api/runner/device-codes/token", "/v1/runner-pairings/redeem"}.issubset(observed):
            raise ValueError("Packaged pairing did not exercise both device approval and pasted-code redemption")
    finally:
        server.shutdown()
        server.server_close()
    receipt = {"status": "passed", "runner_version": version, "application_archive": archive.name,
               "installed_command": shlex.quote(str(command)), "repeat_install": "passed",
               "pair_and_start": "passed", "device_pair_and_start": "passed",
               "pasted_code_pair_and_start": "passed", "device_approval": "local_fixture_only",
               "observed_paths": observed,
               "native_readiness_blockers": 0,
               "claim_boundary": "Actual Linux package, system prerequisites, public managed runtime and paired-profile listener against a local HTTP contract fixture. Hosted Hub and NVIDIA execution unverified."}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    smoke(args.bundle.resolve(), args.output)


if __name__ == "__main__":
    main()
