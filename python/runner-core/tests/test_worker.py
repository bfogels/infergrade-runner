import json
import os
import sys
import tempfile
import unittest
from unittest import mock
from urllib import error as urllib_error

sys.path.insert(0, "python/runner-core/src")

from infergrade.worker import _claim_error_message, _classify_worker_failure, _desktop_progress_projection, _emit_desktop_event, _listener_error_summary, _progress_detail, _progress_percent, _runtime_progress_update, run_worker_loop, run_worker_once

DESKTOP_EVENT_PREFIX = "INFERGRADE_DESKTOP_EVENT "


class WorkerTests(unittest.TestCase):
    def test_worker_once_returns_unclaimed_when_no_job_available(self):
        messages = []
        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": None}):
            result = run_worker_once(
                api_url="http://localhost:8000",
                execution_mode="local_container",
                worker_id="worker-1",
                emit_progress=messages.append,
            )
        self.assertFalse(result["claimed"])
        self.assertEqual(result["worker_id"], "worker-1")
        self.assertEqual([message for message in messages if message.startswith(DESKTOP_EVENT_PREFIX)], [])

    def test_worker_once_emits_desktop_idle_event_when_enabled(self):
        messages = []
        with mock.patch.dict("os.environ", {"INFERGRADE_DESKTOP_EVENTS": "1"}, clear=False):
            with mock.patch("infergrade.worker.claim_run_job", return_value={"run": None}):
                result = run_worker_once(
                    api_url="http://localhost:8000",
                    execution_mode="local_container",
                    worker_id="worker-1",
                    emit_progress=messages.append,
                )

        self.assertFalse(result["claimed"])
        structured = [
            json.loads(message[len(DESKTOP_EVENT_PREFIX) :])
            for message in messages
            if message.startswith(DESKTOP_EVENT_PREFIX)
        ]
        self.assertEqual(structured, [{"type": "assignment_idle"}])

    def test_worker_once_can_suppress_repeated_human_idle_status(self):
        messages = []
        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": None}):
            result = run_worker_once(
                api_url="http://localhost:8000",
                execution_mode="local_container",
                worker_id="worker-1",
                emit_progress=messages.append,
                emit_idle_status=False,
            )

        self.assertFalse(result["claimed"])
        self.assertNotIn("No matching run jobs are awaiting execution.", messages)

    def test_desktop_structured_events_redact_token_shaped_values(self):
        messages = []
        with mock.patch.dict("os.environ", {"INFERGRADE_DESKTOP_EVENTS": "1"}, clear=False):
            _emit_desktop_event(
                messages.append,
                "assignment_update",
                phase="Needs attention",
                description="Bearer qbhr_secret failed for igrt_run_token and pairing code IGRP-8421",
                check_name="signed https://example.test/private?token=secret",
                nested={"api_token": "qbhr_nested_secret", "safe": ["keep", "igrp_pair_secret"]},
            )

        self.assertEqual(len(messages), 1)
        event = json.loads(messages[0][len(DESKTOP_EVENT_PREFIX) :])
        encoded = json.dumps(event)
        self.assertNotIn("qbhr_secret", encoded)
        self.assertNotIn("igrt_run_token", encoded)
        self.assertNotIn("IGRP-8421", encoded)
        self.assertNotIn("qbhr_nested_secret", encoded)
        self.assertNotIn("igrp_pair_secret", encoded)
        self.assertIn("Bearer [redacted]", event["description"])
        self.assertEqual(event["nested"]["api_token"], "[redacted]")
        self.assertEqual(event["nested"]["safe"][1], "igrp_[redacted]")

    def test_worker_once_passes_run_id_filter_when_provided(self):
        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": None}) as claim_mock:
            result = run_worker_once(
                api_url="http://localhost:8000",
                execution_mode="local_container",
                worker_id="worker-1",
                run_id="run_specific",
            )

        self.assertFalse(result["claimed"])
        claim_mock.assert_called_once_with(
            "http://localhost:8000",
            worker_id="worker-1",
            execution_mode="local_container",
            api_token=None,
            run_token=None,
            run_id="run_specific",
            run_config_id=None,
            provider_id=None,
            instance_type_id=None,
            hostname=mock.ANY,
        )

    def test_worker_once_reports_string_claim_errors(self):
        with mock.patch("infergrade.worker.claim_run_job", return_value={"error": "runner session expired"}):
            with self.assertRaisesRegex(RuntimeError, "runner session expired"):
                run_worker_once(
                    api_url="http://localhost:8000",
                    execution_mode="local_container",
                    worker_id="worker-1",
                )

    def test_worker_once_reports_detail_only_claim_errors(self):
        with mock.patch("infergrade.worker.claim_run_job", return_value={"detail": [{"msg": "field required"}]}):
            with self.assertRaisesRegex(RuntimeError, "field required"):
                run_worker_once(
                    api_url="http://localhost:8000",
                    execution_mode="local_container",
                    worker_id="worker-1",
                )

    def test_claim_error_message_handles_common_api_envelopes(self):
        self.assertEqual(_claim_error_message({"error": "plain failure"}), "plain failure")
        self.assertEqual(_claim_error_message({"error": {"message": "structured failure"}}), "structured failure")
        self.assertEqual(_claim_error_message({"detail": "detail failure"}), "detail failure")
        self.assertEqual(_claim_error_message({"detail": [{"msg": "field required"}]}), "field required")

    def test_worker_once_executes_claimed_job_and_uploads_bundle(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_container",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        run_config = {
            "run_config_id": "rcfg_example",
            "name": "Example",
            "request": {
                "run": {
                    "model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
                    "backend": "llama.cpp",
                    "tier": "canary",
                }
            },
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_container"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.quant_artifact_cache_dir = "~/.cache/infergrade/artifacts"
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with tempfile.TemporaryDirectory() as output_root:
            expected_output_dir = os.path.join(os.path.realpath(output_root), "run_example")
            messages = []
            env = {
                "INFERGRADE_HOST_ARTIFACT_CACHE_DIR": "/host/cache",
                "INFERGRADE_RUNNER_OUTPUT_ROOT": output_root,
                "INFERGRADE_DESKTOP_EVENTS": "1",
            }
            with mock.patch.dict("os.environ", env, clear=False):
                with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}) as claim_mock:
                    with mock.patch("infergrade.worker.fetch_run_config", return_value=run_config):
                        with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                            with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}) as doctor_mock:
                                with mock.patch(
                                    "infergrade.worker.load_progress",
                                    return_value={
                                        "current_stage": "deployment",
                                        "current_detail": "interactive_chat_v1",
                                        "request_context": {"deployment_profiles": ["interactive_chat_v1"]},
                                        "deployment_profiles": {"interactive_chat_v1": {"status": "running"}},
                                    },
                                ):
                                    with mock.patch(
                                        "infergrade.worker.run_infergrade",
                                        side_effect=lambda request, emit_progress=None: (
                                            emit_progress("Running deployment profile interactive_chat_v1...") if emit_progress else None,
                                            {"bundle_id": "qb_bundle", "output_dir": request.output_dir},
                                        )[1],
                                    ):
                                        with mock.patch("infergrade.worker.upload_run_bundle", return_value={"stored": True}) as upload_mock:
                                            with mock.patch("infergrade.worker.complete_run_job", return_value={"run": {"run_id": "run_example", "status": "completed"}}) as complete_mock:
                                                with mock.patch("infergrade.worker.heartbeat_run_job") as heartbeat_mock:
                                                    result = run_worker_once(
                                                        api_url="http://localhost:8000",
                                                        execution_mode="local_container",
                                                        worker_id="worker-1",
                                                        emit_progress=messages.append,
                                                    )

        self.assertTrue(result["claimed"])
        self.assertTrue(result["completed"])
        claim_mock.assert_called_once()
        doctor_mock.assert_called_once()
        upload_mock.assert_called_once_with(
            expected_output_dir,
            "http://localhost:8000",
            run_id="run_example",
            run_token=None,
            api_token=None,
        )
        complete_mock.assert_called_once()
        completion_timing = complete_mock.call_args.kwargs["lifecycle_timing"]
        self.assertEqual(completion_timing["timing_version"], "run_lifecycle_timing_v1")
        self.assertEqual(completion_timing["phases"]["upload"]["status"], "completed")
        self.assertIsNotNone(completion_timing["phases"]["upload"]["elapsed_seconds"])
        self.assertNotIn("output_dir", json.dumps(completion_timing))
        heartbeat_mock.assert_called()
        self.assertTrue(
            any(
                call.kwargs.get("stage") == "deployment"
                and call.kwargs.get("detail") == "interactive_chat_v1"
                and call.kwargs.get("progress_percent") is not None
                and call.kwargs.get("progress_percent") >= 60.0
                and (call.kwargs.get("lifecycle_timing") or {}).get("timing_version") == "run_lifecycle_timing_v1"
                for call in heartbeat_mock.call_args_list
            )
        )
        self.assertTrue(
            any(
                call.kwargs.get("stage") == "preflight_complete"
                and call.kwargs.get("message") == "Non-executing run preflight passed."
                and "model load remain pending" in call.kwargs.get("detail", "")
                for call in heartbeat_mock.call_args_list
            )
        )
        self.assertEqual(fake_request.output_dir, expected_output_dir)
        self.assertEqual(fake_request.quant_artifact_cache_dir, "/host/cache")
        self.assertTrue(fake_request.resume)
        structured = [
            json.loads(message[len(DESKTOP_EVENT_PREFIX) :])
            for message in messages
            if message.startswith(DESKTOP_EVENT_PREFIX)
        ]
        self.assertEqual(
            [event["phase"] for event in structured if event["type"] == "assignment_update"],
            ["Preparing", "Preparing", "Preparing", "Preparing", "Running", "Uploading", "Complete"],
        )
        self.assertTrue(all(event["run_id"] == "run_example" for event in structured if event["type"] == "assignment_update"))
        self.assertTrue(
            any(
                event.get("check_name") == "interactive_chat_v1"
                for event in structured
                if event["type"] == "assignment_update" and event["phase"] == "Running"
            )
        )
        self.assertTrue(
            any(
                event.get("preflight") == {"stage": "non_executing", "status": "passed"}
                for event in structured
                if event["type"] == "assignment_update"
            )
        )
        self.assertFalse(
            any(event.get("preflight", {}).get("stage") == "complete" for event in structured)
        )

    def test_desktop_progress_projection_keeps_claim_bound_preflight_stages_explicit(self):
        artifact_checking = _desktop_progress_projection("artifact_resolution", "Resolving model artifact...")
        self.assertEqual(artifact_checking["preflight"], {"stage": "artifact", "status": "checking"})
        artifact_passed = _desktop_progress_projection(
            "artifact_resolution",
            "Exact model artifact resolved; configured size and digest constraints passed.",
        )
        self.assertEqual(artifact_passed["preflight"], {"stage": "artifact", "status": "passed"})
        runtime_passed = _desktop_progress_projection(
            "runtime_lock",
            "Immutable runtime bound to this run.",
            execution_mode="local_native",
        )
        self.assertEqual(runtime_passed["preflight"], {"stage": "runtime_lock", "status": "passed"})
        model_checking = _desktop_progress_projection(
            "backend_resolution",
            "Checking model/runtime compatibility...",
            execution_mode="local_native",
        )
        self.assertEqual(model_checking["preflight"], {"stage": "model_load", "status": "checking"})
        model_passed = _desktop_progress_projection(
            "backend_resolution",
            "Exact model loaded with the locked runtime before scoring.",
            execution_mode="local_native",
        )
        self.assertEqual(model_passed["preflight"], {"stage": "model_load", "status": "passed"})
        scoring = _desktop_progress_projection(
            "capability",
            "Running capability suite...",
            execution_mode="local_native",
        )
        self.assertEqual(scoring["phase"], "Running")
        self.assertEqual(scoring["preflight"], {"stage": "complete", "status": "passed"})
        container_scoring = _desktop_progress_projection(
            "capability",
            "Running capability suite...",
            execution_mode="local_container",
        )
        self.assertNotIn("preflight", container_scoring)
        container_model = _desktop_progress_projection(
            "backend_resolution",
            "Checking model/runtime compatibility...",
            execution_mode="local_container",
        )
        self.assertNotIn("preflight", container_model)
        self.assertNotIn("locked runtime", container_model["description"].lower())
        simulated_model = _desktop_progress_projection(
            "backend_resolution",
            "Checking model/runtime compatibility...",
            execution_mode="local_native",
            simulate=True,
        )
        self.assertNotIn("preflight", simulated_model)
        self.assertNotIn("locked runtime", simulated_model["description"].lower())
        container_runtime = _desktop_progress_projection(
            "runtime_lock",
            "Immutable runtime bound to this run.",
            execution_mode="local_container",
        )
        self.assertNotIn("preflight", container_runtime)
        self.assertNotIn("immutable runtime", container_runtime["description"].lower())
        simulated_runtime = _desktop_progress_projection(
            "runtime_lock",
            "Immutable runtime bound to this run.",
            execution_mode="local_native",
            simulate=True,
        )
        self.assertNotIn("preflight", simulated_runtime)
        self.assertNotIn("immutable runtime", simulated_runtime["description"].lower())

    def test_upload_failure_closes_publish_phase_with_elapsed_time(self):
        claimed_run = {
            "run_id": "run_upload_failure",
            "run_config_id": "rcfg_upload_failure",
            "execution_mode": "local_native",
            "output_dir": "runs/run_upload_failure",
            "cloud": None,
        }
        fake_request = mock.Mock(
            execution_mode="local_native",
            resume=False,
            output_dir=None,
            cloud_provider=None,
            cloud_instance_type=None,
        )
        with tempfile.TemporaryDirectory() as output_root:
            with mock.patch.dict("os.environ", {"INFERGRADE_RUNNER_OUTPUT_ROOT": output_root}, clear=False):
                with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
                    with mock.patch("infergrade.worker.fetch_run_config", return_value={"run_config_id": "rcfg_upload_failure"}):
                        with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                            with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                                with mock.patch(
                                    "infergrade.worker.load_progress",
                                    return_value={"current_stage": "finalization", "stages": {"finalization": {"status": "completed"}}},
                                ):
                                    with mock.patch(
                                        "infergrade.worker.run_infergrade",
                                        return_value={"bundle_id": "qb_bundle", "output_dir": "runs/run_upload_failure"},
                                    ):
                                        with mock.patch("infergrade.worker.upload_run_bundle", side_effect=RuntimeError("upload unavailable")):
                                            with mock.patch("infergrade.worker.heartbeat_run_job"):
                                                with mock.patch(
                                                    "infergrade.worker.fail_run_job",
                                                    return_value={"run": {"run_id": "run_upload_failure", "status": "failed"}},
                                                ) as fail_mock:
                                                    result = run_worker_once(
                                                        api_url="http://localhost:8000",
                                                        execution_mode="local_native",
                                                        worker_id="worker-1",
                                                    )

        self.assertFalse(result["completed"])
        failure_timing = fail_mock.call_args.kwargs["details"]["lifecycle_timing"]
        self.assertEqual(failure_timing["phases"]["upload"]["status"], "failed")
        self.assertIsNotNone(failure_timing["phases"]["upload"]["elapsed_seconds"])

    def test_transient_progress_heartbeat_failure_does_not_abort_benchmark(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_native",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        fake_request = mock.Mock(
            execution_mode="local_native",
            resume=False,
            output_dir=None,
            cloud_provider=None,
            cloud_instance_type=None,
        )
        messages = []

        def heartbeat_side_effect(*_args, **kwargs):
            if kwargs.get("stage") == "capability":
                raise ConnectionResetError(54, "Connection reset by peer")
            return {"run": {"run_id": "run_example"}}

        with tempfile.TemporaryDirectory() as output_root:
            with mock.patch.dict(
                "os.environ",
                {"INFERGRADE_RUNNER_OUTPUT_ROOT": output_root},
                clear=False,
            ):
                with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
                    with mock.patch("infergrade.worker.fetch_run_config", return_value={"run_config_id": "rcfg_example"}):
                        with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                            with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                                with mock.patch(
                                    "infergrade.worker.load_progress",
                                    return_value={
                                        "current_stage": "capability",
                                        "current_detail": "ifeval",
                                        "capability_benchmarks": {
                                            "ifeval": {
                                                "status": "running",
                                                "completed_cases": 179,
                                                "total_cases": 541,
                                            }
                                        },
                                    },
                                ):
                                    with mock.patch(
                                        "infergrade.worker.run_infergrade",
                                        side_effect=lambda request, emit_progress=None: (
                                            emit_progress("Capability benchmark IFEval 179/541 cases."),
                                            {"bundle_id": "qb_bundle", "output_dir": request.output_dir},
                                        )[1],
                                    ):
                                        with mock.patch(
                                            "infergrade.worker.upload_run_bundle",
                                            return_value={"stored": True},
                                        ):
                                            with mock.patch(
                                                "infergrade.worker.complete_run_job",
                                                return_value={"run": {"run_id": "run_example", "status": "completed"}},
                                            ):
                                                with mock.patch(
                                                    "infergrade.worker.heartbeat_run_job",
                                                    side_effect=heartbeat_side_effect,
                                                ):
                                                    result = run_worker_once(
                                                        api_url="http://localhost:8000",
                                                        execution_mode="local_native",
                                                        worker_id="worker-1",
                                                        emit_progress=messages.append,
                                                    )

        self.assertTrue(result["completed"])
        self.assertEqual(
            messages.count("Progress reporting is temporarily unavailable; benchmark execution continues."),
            1,
        )

    def test_repeated_case_progress_throttles_hub_heartbeats(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_native",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        fake_request = mock.Mock(
            execution_mode="local_native",
            resume=False,
            output_dir=None,
            cloud_provider=None,
            cloud_instance_type=None,
        )

        def emit_three_cases(request, emit_progress=None):
            emit_progress("Capability benchmark IFEval 1/541 cases.")
            emit_progress("Capability benchmark IFEval 2/541 cases.")
            emit_progress("Capability benchmark IFEval 3/541 cases.")
            return {"bundle_id": "qb_bundle", "output_dir": request.output_dir}

        with tempfile.TemporaryDirectory() as output_root:
            with mock.patch.dict(
                "os.environ",
                {"INFERGRADE_RUNNER_OUTPUT_ROOT": output_root},
                clear=False,
            ):
                with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
                    with mock.patch("infergrade.worker.fetch_run_config", return_value={"run_config_id": "rcfg_example"}):
                        with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                            with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                                with mock.patch(
                                    "infergrade.worker.load_progress",
                                    return_value={
                                        "current_stage": "capability",
                                        "current_detail": "ifeval",
                                        "capability_benchmarks": {
                                            "ifeval": {
                                                "status": "running",
                                                "completed_cases": 3,
                                                "total_cases": 541,
                                            }
                                        },
                                    },
                                ):
                                    with mock.patch("infergrade.worker.run_infergrade", side_effect=emit_three_cases):
                                        with mock.patch(
                                            "infergrade.worker.upload_run_bundle",
                                            return_value={"stored": True},
                                        ):
                                            with mock.patch(
                                                "infergrade.worker.complete_run_job",
                                                return_value={"run": {"run_id": "run_example", "status": "completed"}},
                                            ):
                                                with mock.patch("infergrade.worker.heartbeat_run_job") as heartbeat_mock:
                                                    with mock.patch(
                                                        "infergrade.worker.time.monotonic",
                                                        side_effect=[100.0, 101.0, 102.0],
                                                    ):
                                                        result = run_worker_once(
                                                            api_url="http://localhost:8000",
                                                            execution_mode="local_native",
                                                            worker_id="worker-1",
                                                        )

        capability_heartbeats = [
            call
            for call in heartbeat_mock.call_args_list
            if call.kwargs.get("stage") == "capability"
        ]
        self.assertTrue(result["completed"])
        self.assertEqual(len(capability_heartbeats), 1)

    def test_worker_rehomes_absolute_claim_output_dir_by_default(self):
        with tempfile.TemporaryDirectory() as output_root:
            absolute_output_dir = os.path.join(tempfile.gettempdir(), "hub-requested-explicit")
            claimed_run = {
                "run_id": "run_example",
                "run_config_id": "rcfg_example",
                "execution_mode": "local_native",
                "output_dir": absolute_output_dir,
                "cloud": None,
            }
            fake_request = mock.Mock()
            fake_request.execution_mode = "local_native"
            fake_request.resume = False
            fake_request.output_dir = None
            fake_request.cloud_provider = None
            fake_request.cloud_instance_type = None

            with mock.patch.dict("os.environ", {"INFERGRADE_RUNNER_OUTPUT_ROOT": output_root}, clear=False):
                with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}) as claim_mock:
                    with mock.patch("infergrade.worker.fetch_run_config", return_value={"request": {"run": {}}}):
                        with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                            with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                                with mock.patch("infergrade.worker.run_infergrade", side_effect=lambda request, emit_progress=None: {"bundle_id": "qb_bundle", "output_dir": request.output_dir}):
                                    with mock.patch("infergrade.worker.upload_run_bundle", return_value={"stored": True}) as upload_mock:
                                        with mock.patch("infergrade.worker.complete_run_job", return_value={"run": {"run_id": "run_example", "status": "completed"}}):
                                            with mock.patch("infergrade.worker.heartbeat_run_job"):
                                                result = run_worker_once(
                                                    api_url="http://localhost:8000",
                                                    execution_mode="local_native",
                                                    worker_id="worker-1",
                                                )

        self.assertTrue(result["claimed"])
        self.assertTrue(result["completed"])
        claim_mock.assert_called_once()
        expected_output_dir = os.path.join(os.path.realpath(output_root), "run_example")
        self.assertEqual(fake_request.output_dir, expected_output_dir)
        upload_mock.assert_called_once_with(
            expected_output_dir,
            "http://localhost:8000",
            run_id="run_example",
            run_token=None,
            api_token=None,
        )

    def test_worker_sanitizes_traversal_output_dir_and_run_id(self):
        claimed_run = {
            "run_id": "../run/escape",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_native",
            "output_dir": "runs/../../escape",
            "cloud": None,
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_native"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with tempfile.TemporaryDirectory() as output_root:
            with mock.patch.dict("os.environ", {"INFERGRADE_RUNNER_OUTPUT_ROOT": output_root}, clear=False):
                with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
                    with mock.patch("infergrade.worker.fetch_run_config", return_value={"request": {"run": {}}}):
                        with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                            with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                                with mock.patch("infergrade.worker.run_infergrade", side_effect=lambda request, emit_progress=None: {"bundle_id": "qb_bundle", "output_dir": request.output_dir}):
                                    with mock.patch("infergrade.worker.upload_run_bundle", return_value={"stored": True}) as upload_mock:
                                        with mock.patch("infergrade.worker.complete_run_job", return_value={"run": {"run_id": claimed_run["run_id"], "status": "completed"}}):
                                            with mock.patch("infergrade.worker.heartbeat_run_job"):
                                                result = run_worker_once(
                                                    api_url="http://localhost:8000",
                                                    execution_mode="local_native",
                                                    worker_id="worker-1",
                                                )

            expected_output_dir = os.path.join(os.path.realpath(output_root), "_run_escape")
            self.assertTrue(result["claimed"])
            self.assertEqual(fake_request.output_dir, expected_output_dir)
            upload_mock.assert_called_once_with(
                expected_output_dir,
                "http://localhost:8000",
                run_id="../run/escape",
                run_token=None,
                api_token=None,
            )

    def test_worker_once_fails_when_preflight_fails(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_container",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        run_config = {
            "run_config_id": "rcfg_example",
            "request": {
                "run": {
                    "model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0",
                    "backend": "llama.cpp",
                    "tier": "canary",
                }
            },
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_container"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
            with mock.patch("infergrade.worker.fetch_run_config", return_value=run_config):
                with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                    with mock.patch(
                        "infergrade.worker.run_doctor",
                        return_value={
                            "ok": False,
                            "checks": [
                                {"id": "docker_daemon", "status": "error", "message": "Docker daemon is not reachable."}
                            ],
                        },
                    ):
                        with mock.patch("infergrade.worker.fail_run_job", return_value={"run": {"run_id": "run_example", "status": "failed"}}) as fail_mock:
                            with mock.patch("infergrade.worker.heartbeat_run_job"):
                                result = run_worker_once(
                                    api_url="http://localhost:8000",
                                    execution_mode="local_container",
                                    worker_id="worker-1",
                                )

        self.assertTrue(result["claimed"])
        self.assertFalse(result["completed"])
        self.assertIn("Preflight failed", result["error"])
        fail_mock.assert_called_once()
        self.assertEqual(fail_mock.call_args.kwargs["error_code"], "missing_runtime_image")
        self.assertTrue(fail_mock.call_args.kwargs["recovery"])
        failure_timing = fail_mock.call_args.kwargs["details"]["lifecycle_timing"]
        self.assertEqual(failure_timing["timing_version"], "run_lifecycle_timing_v1")
        self.assertEqual(failure_timing["phases"]["preflight"]["status"], "failed")
        self.assertIsNotNone(failure_timing["phases"]["preflight"]["elapsed_seconds"])
        self.assertNotIn("output_dir", json.dumps(failure_timing))

    def test_worker_once_marks_interrupted_job_failed_before_exiting(self):
        claimed_run = {
            "run_id": "run_interrupted",
            "run_config_id": "rcfg_interrupted",
            "execution_mode": "local_native",
            "output_dir": "runs/run_interrupted",
            "cloud": None,
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_native"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None
        messages = []

        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
            with mock.patch("infergrade.worker.fetch_run_config", return_value={"request": {"run": {}}}):
                with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                    with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                        with mock.patch("infergrade.worker.run_infergrade", side_effect=KeyboardInterrupt):
                            with mock.patch("infergrade.worker.fail_run_job", return_value={}) as fail_mock:
                                with mock.patch("infergrade.worker.heartbeat_run_job"):
                                    with self.assertRaises(KeyboardInterrupt):
                                        run_worker_once(
                                            api_url="http://localhost:8000",
                                            execution_mode="local_native",
                                            worker_id="worker-1",
                                            emit_progress=messages.append,
                                        )

        fail_mock.assert_called_once()
        self.assertEqual(fail_mock.call_args.args[:3], ("http://localhost:8000", "run_interrupted", "worker-1"))
        self.assertEqual(fail_mock.call_args.kwargs["error_code"], "runner_interrupted")
        self.assertIn("partial output is preserved", fail_mock.call_args.kwargs["recovery"][0]["detail"])
        self.assertIn("marked failed and can be retried", messages[-1])

    def test_cloud_worker_passes_provider_filters_when_claiming(self):
        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": None}) as claim_mock:
            result = run_worker_once(
                api_url="http://localhost:8000",
                execution_mode="cloud_container",
                worker_id="worker-cloud-1",
                provider_id="modal",
                instance_type_id="a10g",
                hostname="cloud-host-1",
            )

        self.assertFalse(result["claimed"])
        claim_mock.assert_called_once_with(
            "http://localhost:8000",
            worker_id="worker-cloud-1",
            execution_mode="cloud_container",
            api_token=None,
            run_token=None,
            run_id=None,
            run_config_id=None,
            provider_id="modal",
            instance_type_id="a10g",
            hostname="cloud-host-1",
        )

    def test_run_token_uses_run_scoped_upload(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_container",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        run_config = {
            "run_config_id": "rcfg_example",
            "request": {"run": {"model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0", "backend": "llama.cpp", "tier": "canary"}},
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_container"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
            with mock.patch("infergrade.worker.fetch_run_config", return_value=run_config):
                with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                    with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                        with mock.patch("infergrade.worker.run_infergrade", return_value={"bundle_id": "qb_bundle", "output_dir": "runs/run_example"}):
                            with mock.patch("infergrade.worker.upload_run_bundle", return_value={"stored": True}) as scoped_upload_mock:
                                with mock.patch("infergrade.worker.complete_run_job", return_value={"run": {"run_id": "run_example", "status": "completed"}}):
                                    with mock.patch("infergrade.worker.heartbeat_run_job"):
                                        result = run_worker_once(
                                            api_url="http://localhost:8000",
                                            execution_mode="local_container",
                                            worker_id="worker-1",
                                            run_id="run_example",
                                            run_token="igrt_example",
                                        )

        self.assertTrue(result["completed"])
        scoped_upload_mock.assert_called_once_with(
            "runs/run_example",
            "http://localhost:8000",
            run_id="run_example",
            run_token="igrt_example",
            api_token=None,
        )

    def test_runner_session_token_uses_run_scoped_upload(self):
        claimed_run = {
            "run_id": "run_example",
            "run_config_id": "rcfg_example",
            "execution_mode": "local_container",
            "output_dir": "runs/run_example",
            "cloud": None,
        }
        run_config = {
            "run_config_id": "rcfg_example",
            "request": {"run": {"model": "TinyLlama/TinyLlama-1.1B-Chat-v1.0", "backend": "llama.cpp", "tier": "canary"}},
        }
        fake_request = mock.Mock()
        fake_request.execution_mode = "local_container"
        fake_request.resume = False
        fake_request.output_dir = None
        fake_request.cloud_provider = None
        fake_request.cloud_instance_type = None

        with mock.patch("infergrade.worker.claim_run_job", return_value={"run": claimed_run}):
            with mock.patch("infergrade.worker.fetch_run_config", return_value=run_config):
                with mock.patch("infergrade.worker.request_from_run_config_document", return_value=fake_request):
                    with mock.patch("infergrade.worker.run_doctor", return_value={"ok": True, "checks": []}):
                        with mock.patch("infergrade.worker.run_infergrade", return_value={"bundle_id": "qb_bundle", "output_dir": "runs/run_example"}):
                            with mock.patch("infergrade.worker.upload_run_bundle", return_value={"stored": True}) as scoped_upload_mock:
                                with mock.patch("infergrade.worker.complete_run_job", return_value={"run": {"run_id": "run_example", "status": "completed"}}):
                                    with mock.patch("infergrade.worker.heartbeat_run_job"):
                                        with mock.patch("infergrade.worker.heartbeat_runner"):
                                            result = run_worker_once(
                                                api_url="http://localhost:8000",
                                                execution_mode="local_container",
                                                worker_id="worker-1",
                                                api_token="qbhr_runner_session",
                                            )

        self.assertTrue(result["completed"])
        scoped_upload_mock.assert_called_once_with(
            "runs/run_example",
            "http://localhost:8000",
            run_id="run_example",
            run_token=None,
            api_token="qbhr_runner_session",
        )

    def test_progress_percent_uses_capability_case_progress(self):
        payload = {
            "current_stage": "capability",
            "current_detail": "multi_turn_chat_memory_v1",
            "capability_benchmarks": {
                "multi_turn_chat_memory_v1": {
                    "status": "running",
                    "display_name": "Multi-turn chat memory",
                    "completed_cases": 5,
                    "total_cases": 5,
                    "progress_detail": "5/5",
                }
            },
        }
        self.assertGreater(_progress_percent(payload), 52.0)
        self.assertLess(_progress_percent(payload), 60.1)
        self.assertEqual(_progress_detail(payload), "Multi-turn chat memory 5/5")
        with mock.patch("infergrade.worker.load_progress", return_value=payload):
            stage, hub_detail, desktop_detail, progress_percent = _runtime_progress_update("runs/run_example")
        self.assertEqual(stage, "capability")
        self.assertEqual(hub_detail, "multi_turn_chat_memory_v1")
        self.assertEqual(desktop_detail, "Multi-turn chat memory 5/5")
        self.assertGreater(progress_percent, 52.0)

    def test_progress_percent_weights_planned_capability_cases_without_regressing(self):
        capability_benchmarks = {
            "ifeval": {
                "status": "running",
                "display_name": "IFEval",
                "completed_cases": 141,
                "total_cases": 541,
            },
            "multiturn_chat_memory_v1": {
                "status": "pending",
                "display_name": "Multi-turn chat memory",
                "completed_cases": 0,
                "total_cases": 5,
            },
            "assistant_compositional_instruction_v2": {
                "status": "pending",
                "display_name": "Compositional instruction following",
                "completed_cases": 0,
                "total_cases": 24,
            },
        }
        during_ifeval = _progress_percent(
            {
                "current_stage": "capability",
                "current_detail": "ifeval",
                "capability_benchmarks": capability_benchmarks,
            }
        )
        self.assertEqual(during_ifeval, 51.0)

        capability_benchmarks["ifeval"]["status"] = "completed"
        capability_benchmarks["multiturn_chat_memory_v1"]["status"] = "running"
        after_transition = _progress_percent(
            {
                "current_stage": "capability",
                "current_detail": "multiturn_chat_memory_v1",
                "capability_benchmarks": capability_benchmarks,
            }
        )
        self.assertGreaterEqual(after_transition, during_ifeval)

        capability_benchmarks["multiturn_chat_memory_v1"]["completed_cases"] = 3
        during_memory = _progress_percent(
            {
                "current_stage": "capability",
                "current_detail": "multiturn_chat_memory_v1",
                "capability_benchmarks": capability_benchmarks,
            }
        )
        self.assertGreater(during_memory, after_transition)

    def test_progress_percent_uses_deployment_iteration_progress(self):
        payload = {
            "current_stage": "deployment",
            "request_context": {"deployment_profiles": ["interactive_chat_v1"]},
            "deployment_profiles": {
                "interactive_chat_v1": {
                    "status": "running",
                    "completed_iterations": 3,
                    "total_iterations": 7,
                }
            },
        }
        self.assertGreater(_progress_percent(payload), 60.0)
        self.assertLess(_progress_percent(payload), 94.1)

    def test_worker_loop_registers_runner_diagnostics(self):
        snapshot = {
            "environment": {"hardware_class": "apple_silicon"},
            "contract": {"publisher": "infergrade-runner", "contract_version": "0.1.0"},
            "diagnostics": {"status": "ready", "checks": []},
        }
        with mock.patch("infergrade.worker.collect_runner_diagnostics", return_value=snapshot):
            with mock.patch("infergrade.worker.register_runner") as register_mock:
                with mock.patch("infergrade.worker.heartbeat_runner"):
                    with mock.patch("infergrade.worker.run_worker_once", return_value={"claimed": True, "completed": True, "worker_id": "runner-1"}):
                        result = run_worker_loop(
                            api_url="http://localhost:8000",
                            execution_mode="local_native",
                            worker_id="runner-1",
                            max_jobs=1,
                        )

        self.assertEqual(result["processed_jobs"], 1)
        register_mock.assert_called_once()
        self.assertEqual(register_mock.call_args.kwargs["environment"], snapshot["environment"])
        self.assertEqual(register_mock.call_args.kwargs["contract"], snapshot["contract"])
        self.assertEqual(register_mock.call_args.kwargs["diagnostics"], snapshot["diagnostics"])

    def test_worker_loop_announces_listening_once_and_suppresses_poll_spam(self):
        snapshot = {"environment": {}, "contract": {}, "diagnostics": {}}
        messages = []
        attempts = [
            {"claimed": False, "worker_id": "runner-1"},
            {"claimed": True, "completed": True, "worker_id": "runner-1"},
        ]
        with mock.patch("infergrade.worker.collect_runner_diagnostics", return_value=snapshot), mock.patch(
            "infergrade.worker.register_runner"
        ), mock.patch("infergrade.worker.heartbeat_runner"), mock.patch(
            "infergrade.worker.time.sleep"
        ), mock.patch("infergrade.worker.run_worker_once", side_effect=attempts) as once_mock:
            result = run_worker_loop(
                api_url="http://localhost:8000",
                execution_mode="local_native",
                worker_id="runner-1",
                max_jobs=1,
                emit_progress=messages.append,
            )

        self.assertEqual(result["completed_jobs"], 1)
        self.assertEqual(messages.count("✓ Runner connected · waiting for benchmarks from InferGrade Hub."), 1)
        self.assertNotIn("No matching run jobs are awaiting execution.", messages)
        self.assertTrue(all(call.kwargs["emit_idle_status"] is False for call in once_mock.call_args_list))

    def test_worker_loop_retries_after_claim_error(self):
        snapshot = {
            "environment": {"hardware_class": "apple_silicon"},
            "contract": {"publisher": "infergrade-runner", "contract_version": "0.1.0"},
            "diagnostics": {"status": "ready", "checks": []},
        }
        messages = []
        attempts = [
            RuntimeError("temporary claim failure"),
            {"claimed": True, "completed": True, "worker_id": "runner-1"},
        ]

        def worker_once_side_effect(**_kwargs):
            next_attempt = attempts.pop(0)
            if isinstance(next_attempt, Exception):
                raise next_attempt
            return next_attempt

        with mock.patch("infergrade.worker.collect_runner_diagnostics", return_value=snapshot):
            with mock.patch("infergrade.worker.register_runner"):
                with mock.patch("infergrade.worker.heartbeat_runner") as heartbeat_mock:
                    with mock.patch("infergrade.worker.time.sleep") as sleep_mock:
                        with mock.patch("infergrade.worker.run_worker_once", side_effect=worker_once_side_effect):
                            result = run_worker_loop(
                                api_url="http://localhost:8000",
                                execution_mode="local_native",
                                worker_id="runner-1",
                                max_jobs=1,
                                emit_progress=messages.append,
                            )

        self.assertEqual(result["processed_jobs"], 1)
        self.assertEqual(result["completed_jobs"], 1)
        self.assertIn("Hub connection interrupted: temporary claim failure. Retrying quietly.", messages)
        self.assertIn("✓ Hub connection restored.", messages)
        sleep_mock.assert_called_once()
        self.assertTrue(
            any(
                "Last claim failed: temporary claim failure." == call.kwargs.get("metadata", {}).get("message")
                for call in heartbeat_mock.call_args_list
            )
        )

    def test_worker_loop_retries_after_transient_api_disconnect(self):
        snapshot = {
            "environment": {"hardware_class": "apple_silicon"},
            "contract": {"publisher": "infergrade-runner", "contract_version": "0.1.0"},
            "diagnostics": {"status": "ready", "checks": []},
        }
        messages = []
        attempts = [
            urllib_error.URLError("connection refused"),
            {"claimed": True, "completed": True, "worker_id": "runner-1"},
        ]

        def worker_once_side_effect(**_kwargs):
            next_attempt = attempts.pop(0)
            if isinstance(next_attempt, Exception):
                raise next_attempt
            return next_attempt

        with mock.patch("infergrade.worker.collect_runner_diagnostics", return_value=snapshot):
            with mock.patch("infergrade.worker.register_runner"):
                with mock.patch("infergrade.worker.heartbeat_runner", side_effect=[None, urllib_error.URLError("still down")]):
                    with mock.patch("infergrade.worker.time.sleep") as sleep_mock:
                        with mock.patch("infergrade.worker.run_worker_once", side_effect=worker_once_side_effect):
                            result = run_worker_loop(
                                api_url="http://localhost:8000",
                                execution_mode="local_native",
                                worker_id="runner-1",
                                max_jobs=1,
                                emit_progress=messages.append,
                            )

        self.assertEqual(result["processed_jobs"], 1)
        self.assertEqual(result["completed_jobs"], 1)
        self.assertTrue(any("Hub connection interrupted:" in message and "connection refused" in message for message in messages))
        self.assertIn("✓ Hub connection restored.", messages)
        self.assertFalse(any("Runner heartbeat failed:" in message for message in messages))
        sleep_mock.assert_called_once()

    def test_worker_loop_summarizes_and_deduplicates_html_outages(self):
        snapshot = {"environment": {}, "contract": {}, "diagnostics": {}}
        messages = []
        html_502 = RuntimeError("<!DOCTYPE html><html><head><title>502</title></head><body>private proxy page</body></html>")
        attempts = [
            html_502,
            RuntimeError(str(html_502)),
            {"claimed": True, "completed": True, "worker_id": "runner-1"},
        ]

        with mock.patch("infergrade.worker.collect_runner_diagnostics", return_value=snapshot), mock.patch(
            "infergrade.worker.register_runner"
        ), mock.patch("infergrade.worker.heartbeat_runner"), mock.patch(
            "infergrade.worker.time.sleep"
        ) as sleep_mock, mock.patch("infergrade.worker.run_worker_once", side_effect=attempts):
            result = run_worker_loop(
                api_url="http://localhost:8000",
                execution_mode="local_native",
                worker_id="runner-1",
                max_jobs=1,
                emit_progress=messages.append,
            )

        self.assertEqual(result["completed_jobs"], 1)
        self.assertEqual(messages.count("Hub connection interrupted: Hub returned HTTP 502. Retrying quietly."), 1)
        self.assertEqual(messages.count("✓ Hub connection restored."), 1)
        self.assertFalse(any("<!DOCTYPE" in message or "private proxy page" in message for message in messages))
        self.assertEqual(sleep_mock.call_count, 2)

    def test_listener_error_summary_redacts_and_bounds_unstructured_errors(self):
        summary = _listener_error_summary(RuntimeError("Bearer qbhr_secret " + ("failure " * 100)))

        self.assertNotIn("qbhr_secret", summary)
        self.assertIn("Bearer [redacted]", summary)
        self.assertLessEqual(len(summary), 180)

    def test_classify_worker_failure_maps_download_errors_to_actionable_code(self):
        failure = _classify_worker_failure(
            RuntimeError("curl failed while downloading https://example.invalid/model.gguf: 404")
        )

        self.assertEqual(failure["error_code"], "artifact_download_failed")
        self.assertIn("Artifact download failed", failure["message"])
        self.assertTrue(failure["recovery"])
        self.assertIn("raw_error", failure["details"])

    def test_classify_worker_failure_distinguishes_recoverable_and_unqualified_specialized_runtimes(self):
        recoverable = _classify_worker_failure(
            RuntimeError(
                "requires exact runtime target 'infergrade/prism/runtime.tar.gz' "
                "(runtime build %s)" % ("a" * 64)
            )
        )
        unsupported = _classify_worker_failure(
            RuntimeError("signed catalog has no valid exact-artifact compatibility assertion for abc")
        )

        self.assertEqual(recoverable["error_code"], "specialized_runtime_required")
        self.assertIn("Install", recoverable["message"])
        self.assertEqual(
            recoverable["details"]["required_runtime"],
            {
                "target_name": "infergrade/prism/runtime.tar.gz",
                "runtime_build_id": "a" * 64,
            },
        )
        self.assertEqual(unsupported["error_code"], "specialized_artifact_unsupported")
        self.assertIn("reviewed alternative", unsupported["message"])

    def test_classify_worker_failure_treats_http_get_as_download_recovery(self):
        failure = _classify_worker_failure(RuntimeError("HTTP GET failed with HTTP 503"))

        self.assertEqual(failure["error_code"], "artifact_download_failed")
        self.assertIn("download", failure["message"].lower())

    def test_classify_worker_failure_maps_low_disk_errors_to_actionable_code(self):
        failure = _classify_worker_failure(
            RuntimeError("insufficient free disk space for artifact cache: 1.00 GB free, 5.00 GB required")
        )

        self.assertEqual(failure["error_code"], "insufficient_disk")
        self.assertIn("could not write", failure["message"])
        self.assertIn("raw_error", failure["details"])

    def test_classify_doctor_cache_low_disk_failure_uses_disk_error_code(self):
        failure = _classify_worker_failure(
            RuntimeError("Preflight failed."),
            doctor_report={
                "ok": False,
                "checks": [
                    {
                        "id": "artifact_cache_dir",
                        "status": "error",
                        "message": "Insufficient free disk space.",
                        "details": {"path": "/tmp/cache"},
                    }
                ],
            },
        )

        self.assertEqual(failure["error_code"], "insufficient_disk")
        self.assertIn("artifact cache", failure["message"])
        self.assertIn("failed_check", failure["details"])


if __name__ == "__main__":
    unittest.main()
