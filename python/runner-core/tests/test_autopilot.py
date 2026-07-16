import sys
import unittest
from unittest import mock

sys.path.insert(0, "python/runner-core/src")

from infergrade.autopilot import run_agent_work_loop


class AgentAutopilotTests(unittest.TestCase):
    def test_loop_materializes_hub_choice_and_executes_exact_run(self):
        candidate = {
            "candidate_id": "candidate-1",
            "model_id": "Qwen/Qwen3.5-9B",
            "quantization_scheme": "q4_k_m",
            "use_case": "general_assistant",
            "selection_basis": "calibration_gate_evidence_gap",
            "download_size_bytes": 5 * 1024 ** 3,
        }
        plans = [
            {"grant": {"grant_id": "grant-1", "remaining_jobs": 1}, "candidates": [candidate]},
            {"grant": {"grant_id": "grant-1", "remaining_jobs": 0}, "candidates": []},
        ]
        messages = []
        with mock.patch("infergrade.autopilot.fetch_agent_work_plan", side_effect=plans):
            with mock.patch(
                "infergrade.autopilot.materialize_agent_work_candidate",
                return_value={"created": True, "run": {"run_id": "run-1"}},
            ) as materialize_mock:
                with mock.patch(
                    "infergrade.autopilot.run_worker_once",
                    return_value={"claimed": True, "completed": True, "failed": False},
                ) as worker_mock:
                    result = run_agent_work_loop(
                        api_url="https://infergrade.com",
                        worker_id="runner-agent",
                        api_token="secret",
                        emit_progress=messages.append,
                    )

        materialize_mock.assert_called_once_with(
            "https://infergrade.com",
            candidate_id="candidate-1",
            grant_id="grant-1",
            api_token="secret",
        )
        worker_mock.assert_called_once_with(
            api_url="https://infergrade.com",
            execution_mode="local_native",
            worker_id="runner-agent",
            run_id="run-1",
            hostname=None,
            api_token="secret",
            run_token=None,
            simulate=False,
            emit_progress=messages.append,
        )
        self.assertEqual(result["processed_jobs"], 1)
        self.assertEqual(result["completed_jobs"], 1)
        self.assertEqual(result["stopped_reason"], "grant_has_no_remaining_candidates")
        self.assertIn("Qwen/Qwen3.5-9B", messages[0])

    def test_loop_stops_at_local_job_cap_without_exceeding_grant(self):
        candidate = {"candidate_id": "candidate-1", "download_size_bytes": 1}
        plans = [
            {"grant": {"grant_id": "grant-1"}, "candidates": [candidate]},
            {"grant": {"grant_id": "grant-1"}, "candidates": [{"candidate_id": "candidate-2"}]},
        ]
        with mock.patch("infergrade.autopilot.fetch_agent_work_plan", side_effect=plans):
            with mock.patch(
                "infergrade.autopilot.materialize_agent_work_candidate",
                return_value={"run": {"run_id": "run-1"}},
            ):
                with mock.patch(
                    "infergrade.autopilot.run_worker_once",
                    return_value={"claimed": True, "completed": False, "failed": True},
                ):
                    result = run_agent_work_loop(
                        api_url="https://infergrade.com",
                        worker_id="runner-agent",
                        api_token="secret",
                        max_jobs=1,
                    )

        self.assertEqual(result["processed_jobs"], 1)
        self.assertEqual(result["failed_jobs"], 1)
        self.assertEqual(result["stopped_reason"], "local_max_jobs_reached")

    def test_loop_fails_if_materialized_run_cannot_be_claimed(self):
        plans = [{"grant": {"grant_id": "grant-1"}, "candidates": [{"candidate_id": "candidate-1"}]}]
        with mock.patch("infergrade.autopilot.fetch_agent_work_plan", side_effect=plans):
            with mock.patch(
                "infergrade.autopilot.materialize_agent_work_candidate",
                return_value={"run": {"run_id": "run-1"}},
            ):
                with mock.patch("infergrade.autopilot.run_worker_once", return_value={"claimed": False}):
                    with self.assertRaisesRegex(RuntimeError, "not claimable"):
                        run_agent_work_loop(
                            api_url="https://infergrade.com", worker_id="runner-agent", api_token="secret"
                        )


if __name__ == "__main__":
    unittest.main()
