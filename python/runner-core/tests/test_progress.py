import sys
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.models import RunRequest
from infergrade.benchmark_catalog import normalize_request_selection
from infergrade.progress import initialize_progress, lifecycle_timing_snapshot, mark_failed
from infergrade.runner import _planned_capability_benchmarks


class ProgressTests(unittest.TestCase):
    def test_lifecycle_timing_snapshot_separates_operational_phases(self):
        progress = {
            "current_stage": "deployment",
            "stages": {
                "artifact_resolution": {
                    "status": "completed",
                    "started_at": "2026-08-01T12:00:00Z",
                    "completed_at": "2026-08-01T12:02:00Z",
                    "metadata": {"artifact_cache_hit": False},
                },
                "runtime_lock": {
                    "status": "completed",
                    "started_at": "2026-08-01T12:02:00Z",
                    "completed_at": "2026-08-01T12:02:05Z",
                },
                "backend_resolution": {
                    "status": "completed",
                    "started_at": "2026-08-01T12:02:05Z",
                    "completed_at": "2026-08-01T12:03:05Z",
                },
                "capability": {
                    "status": "completed",
                    "started_at": "2026-08-01T12:03:05Z",
                    "completed_at": "2026-08-01T12:13:05Z",
                },
            },
            "deployment_profiles": {
                "interactive_chat_v1": {
                    "status": "running",
                    "started_at": "2026-08-01T12:13:05Z",
                    "completed_at": None,
                },
            },
        }

        timing = lifecycle_timing_snapshot(
            progress,
            observed_at="2026-08-01T12:14:05Z",
            preflight_seconds=10.25,
            worker_wall_seconds=850.25,
        )

        self.assertEqual(timing["timing_version"], "run_lifecycle_timing_v1")
        self.assertEqual(timing["phases"]["artifact"]["elapsed_seconds"], 120.0)
        self.assertEqual(timing["phases"]["runtime_model"]["elapsed_seconds"], 65.0)
        self.assertEqual(timing["phases"]["capability"]["elapsed_seconds"], 600.0)
        self.assertEqual(timing["phases"]["deployment"]["status"], "running")
        self.assertEqual(timing["current_phase"], "deployment")
        self.assertEqual(timing["phases"]["deployment"]["elapsed_seconds"], 60.0)
        self.assertFalse(timing["artifact_cache_hit"])
        self.assertIsNone(timing["phases"]["upload"]["elapsed_seconds"])

        uploading = lifecycle_timing_snapshot(progress, observed_at="2026-08-01T12:14:05Z", upload_status="running")
        self.assertEqual(uploading["current_phase"], "upload")

    def test_mark_failed_closes_the_active_phase_for_timing(self):
        progress = {
            "status": "running",
            "current_stage": "artifact_resolution",
            "current_detail": None,
            "completed_at": None,
            "stages": {
                "artifact_resolution": {
                    "status": "running",
                    "started_at": "2026-08-01T12:00:00Z",
                    "completed_at": None,
                }
            },
            "deployment_profiles": {},
            "errors": [],
        }

        with mock.patch("infergrade.progress.utcnow_iso", return_value="2026-08-01T12:01:00Z"):
            with mock.patch("infergrade.progress.save_progress"):
                mark_failed("runs/example", progress, "artifact_resolution", None, "download failed")

        timing = lifecycle_timing_snapshot(progress, observed_at="2026-08-01T12:02:00Z")
        self.assertEqual(timing["phases"]["artifact"]["status"], "failed")
        self.assertEqual(timing["phases"]["artifact"]["elapsed_seconds"], 60.0)

    def test_planned_capability_benchmarks_use_normalized_catalog_case_limits(self):
        request = RunRequest(
            model="Qwen/Qwen3.5-4B",
            backend="llama.cpp",
            tier="gold",
            benchmark_check_ids=[
                "ifeval",
                "multiturn_chat_memory_v1",
                "assistant_compositional_instruction_v2",
            ],
        )
        normalize_request_selection(request)

        self.assertEqual(
            _planned_capability_benchmarks(request),
            [
                {"benchmark_id": "ifeval", "display_name": "IFEval", "total_cases": 541},
                {
                    "benchmark_id": "multiturn_chat_memory_v1",
                    "display_name": "Multi-turn chat memory",
                    "total_cases": 5,
                },
                {
                    "benchmark_id": "assistant_compositional_instruction_v2",
                    "display_name": "Compositional instruction following",
                    "total_cases": 24,
                },
            ],
        )

    def test_initialize_progress_records_the_full_capability_plan(self):
        request = RunRequest(
            model="Qwen/Qwen3.5-4B",
            backend="llama.cpp",
            tier="gold",
            use_case="general_assistant",
        )

        progress = initialize_progress(
            "qb_example",
            request,
            "2026-07-29T12:00:00Z",
            planned_capability_benchmarks=[
                {"benchmark_id": "ifeval", "display_name": "IFEval", "total_cases": 541},
                {
                    "benchmark_id": "multiturn_chat_memory_v1",
                    "display_name": "Multi-turn chat memory",
                    "total_cases": 5,
                },
            ],
        )

        self.assertEqual(list(progress["capability_benchmarks"]), ["ifeval", "multiturn_chat_memory_v1"])
        self.assertEqual(progress["capability_benchmarks"]["ifeval"]["status"], "pending")
        self.assertEqual(progress["capability_benchmarks"]["ifeval"]["total_cases"], 541)
        self.assertEqual(progress["capability_benchmarks"]["ifeval"]["completed_cases"], 0)


if __name__ == "__main__":
    unittest.main()
