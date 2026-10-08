from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")
from infergrade.admission import admission_status, claim_admission, set_admission_paused
from infergrade.worker import run_worker_loop, run_worker_once


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = mock.patch.dict(os.environ, {"INFERGRADE_CONFIG_DIR": self.directory.name})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_pause_persists_and_blocks_claim_without_touching_active_execution(self):
        self.assertFalse(admission_status()["paused"])
        set_admission_paused(True)
        with mock.patch("infergrade.worker.claim_run_job") as claim:
            result = run_worker_once("http://localhost:8000", "local_native", simulate=True)
        claim.assert_not_called()
        self.assertTrue(result["admission_paused"])
        output = subprocess.check_output([sys.executable, "-m", "infergrade", "admission", "status", "--json"], env=dict(os.environ, PYTHONPATH="python/runner-core/src"), text=True)
        self.assertTrue(json.loads(output)["paused"])
        if os.name != "nt":
            self.assertEqual(Path(self.directory.name, "admission.json").stat().st_mode & 0o777, 0o600)
        set_admission_paused(False)
        with claim_admission() as allowed:
            self.assertTrue(allowed)

    def test_pause_waits_for_claim_admission_but_not_active_job(self):
        entered, release, confirmed = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def claim(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(5))
            return {"run": {"run_id": "run_test"}}
        def execute(**kwargs):
            self.assertTrue(confirmed.wait(5))
            self.assertTrue(admission_status()["paused"])
            return {"completed": True}
        def worker():
            try:
                self.assertTrue(run_worker_once("http://localhost:8000", "local_native", simulate=True)["completed"])
            except BaseException as exc:
                errors.append(exc)
        def pause():
            set_admission_paused(True)
            confirmed.set()
        with mock.patch("infergrade.worker.claim_run_job", side_effect=claim), mock.patch("infergrade.worker.execute_run_job", side_effect=execute):
            job = threading.Thread(target=worker)
            job.start()
            self.assertTrue(entered.wait(5))
            pauser = threading.Thread(target=pause)
            pauser.start()
            self.assertFalse(confirmed.wait(.1))
            release.set()
            job.join(5)
            pauser.join(5)
            self.assertFalse(job.is_alive())
            self.assertFalse(pauser.is_alive())
        self.assertEqual(errors, [])

    def test_invalid_oversized_and_linked_state_fail_closed(self):
        path = Path(self.directory.name, "admission.json")
        for value in [b"broken", b"x" * 4097, b'{"schema_version":"infergrade.admission.v1","paused":1}']:
            path.write_bytes(value)
            with mock.patch("infergrade.worker.claim_run_job") as claim:
                with self.assertRaisesRegex(RuntimeError, "blocked"):
                    run_worker_once("http://localhost:8000", "local_native", simulate=True)
            claim.assert_not_called()
        set_admission_paused(True)
        self.assertTrue(admission_status()["paused"])
        path.unlink()
        target = Path(self.directory.name, "external.json")
        target.write_text('{"schema_version":"infergrade.admission.v1","paused":false}')
        try:
            path.symlink_to(target)
        except OSError:
            return
        with self.assertRaises(RuntimeError):
            admission_status()
        with self.assertRaises(RuntimeError):
            set_admission_paused(False)
        self.assertFalse(json.loads(target.read_text())["paused"])

    def test_paused_loop_keeps_authenticated_heartbeat_and_queue_untouched(self):
        class EndLoop(BaseException):
            pass
        set_admission_paused(True)
        with mock.patch("infergrade.worker.collect_runner_diagnostics", return_value={}), mock.patch("infergrade.worker.load_runner_profile", return_value={}), mock.patch("infergrade.worker.register_runner"), mock.patch("infergrade.worker.heartbeat_runner") as heartbeat, mock.patch("infergrade.worker.claim_run_job") as claim, mock.patch("infergrade.worker.time.sleep", side_effect=EndLoop):
            with self.assertRaises(EndLoop):
                run_worker_loop("http://localhost:8000", "local_native", worker_id="runner_test", api_token="test_only_authority", simulate=True)
        claim.assert_not_called()
        final = heartbeat.call_args.kwargs
        self.assertTrue(final["metadata"]["admission_paused"])
        self.assertEqual(final["api_token"], "test_only_authority")
        self.assertEqual(final["status"], "listening")

    def test_separate_process_pause_waits_for_claim_and_crash_releases_lock(self):
        env = dict(os.environ, PYTHONPATH="python/runner-core/src")
        with claim_admission():
            child = subprocess.Popen([sys.executable, "-u", "-c", "from infergrade.admission import set_admission_paused; print('ready',flush=True); set_admission_paused(True); print('confirmed',flush=True)"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            self.addCleanup(lambda: child.kill() if child.poll() is None else None)
            self.assertEqual(child.stdout.readline().strip(), "ready")
            self.assertIsNone(child.poll())
        stdout, stderr = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, stderr)
        self.assertEqual(stdout.strip(), "confirmed")
        self.assertTrue(admission_status()["paused"])
        owner = subprocess.Popen([sys.executable, "-u", "-c", "from infergrade.admission import claim_admission; import time; gate=claim_admission(); gate.__enter__(); print('locked',flush=True); time.sleep(30)"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: owner.kill() if owner.poll() is None else None)
        self.assertEqual(owner.stdout.readline().strip(), "locked")
        owner.kill()
        owner.communicate(timeout=5)
        set_admission_paused(False)
        self.assertFalse(admission_status()["paused"])

    def test_stalled_actual_claim_times_out_and_releases_admission(self):
        received, release = threading.Event(), threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                received.set()
                release.wait(3)
                try:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"run":null}')
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch("infergrade.transport.CLAIM_REQUEST_TIMEOUT_SECONDS", .15):
                with self.assertRaises((TimeoutError, OSError)):
                    run_worker_once("http://127.0.0.1:%s" % server.server_port, "local_native", simulate=True)
            self.assertTrue(received.is_set())
            set_admission_paused(True)
            self.assertTrue(admission_status()["paused"])
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            thread.join(3)
