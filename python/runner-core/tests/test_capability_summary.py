import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.capability_contract import validate_capability_summary_artifact
from infergrade.capability_summary import build_capability_summary_artifact
from infergrade.models import CapabilityExecution, RunRequest
from infergrade.utils import write_json


class CapabilitySummaryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="infergrade-capability-summary-")

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_summary_preserves_scored_partial_and_missing_surfaces(self):
        assistant_path = self._write_capability_run(
            "multiturn_chat_memory_v1",
            surface="local_assistant_capability",
            state="scored",
            score=1.0,
            task_states=["scored", "scored", "scored"],
        )
        coding_path = self._write_capability_run(
            "coding_static_repair_v1",
            surface="local_coding_capability",
            state="partial",
            score=0.5,
            task_states=["scored", "failed"],
        )
        execution = self._execution(
            {
                "multiturn_chat_memory_v1": assistant_path,
                "coding_static_repair_v1": coding_path,
            }
        )

        summary = build_capability_summary_artifact(self._request(), execution, self.tempdir, created_at="2026-05-08T12:00:00Z")

        self.assertEqual(validate_capability_summary_artifact(summary), [])
        by_surface = {item["surface"]: item for item in summary["surfaces"]}
        self.assertEqual(by_surface["local_assistant_capability"]["state"], "scored")
        self.assertEqual(by_surface["local_assistant_capability"]["score"], 1.0)
        self.assertEqual(by_surface["local_coding_capability"]["state"], "partial")
        self.assertEqual(by_surface["local_coding_capability"]["failure_count"], 1)
        self.assertEqual(by_surface["local_reasoning_capability"]["state"], "not_yet_benchmarked")
        self.assertEqual(by_surface["quant_fidelity"]["state"], "not_yet_benchmarked")
        self.assertEqual(summary["next_recommended_benchmark_action"]["action"], "retry_or_inspect_capability_lane")
        self.assertEqual(summary["next_recommended_benchmark_action"]["surface"], "local_coding_capability")
        self.assertEqual(len(summary["capability_artifacts"]), 2)
        self.assertTrue(summary["capability_artifacts"][0]["path"].startswith("artifacts/capability/"))
        self.assertIn("This summary is not a global intelligence score.", summary["unsupported_claim_summary"])

    def test_summary_recommends_missing_reasoning_after_assistant_and_coding_score(self):
        execution = self._execution(
            {
                "multiturn_chat_memory_v1": self._write_capability_run(
                    "multiturn_chat_memory_v1",
                    surface="local_assistant_capability",
                    state="scored",
                    score=1.0,
                    task_states=["scored"],
                ),
                "coding_static_repair_v1": self._write_capability_run(
                    "coding_static_repair_v1",
                    surface="local_coding_capability",
                    state="scored",
                    score=1.0,
                    task_states=["scored"],
                ),
            }
        )

        summary = build_capability_summary_artifact(self._request(), execution, self.tempdir)

        self.assertEqual(summary["next_recommended_benchmark_action"]["action"], "run_reasoning_decision_lane")
        self.assertEqual(summary["next_recommended_benchmark_action"]["benchmark_check_id"], "reasoning_exact_answer_v1")

    def test_summary_recommends_repetition_when_thin_local_samples_exist(self):
        execution = self._execution(
            {
                "multiturn_chat_memory_v1": self._write_capability_run(
                    "multiturn_chat_memory_v1",
                    surface="local_assistant_capability",
                    state="scored",
                    score=1.0,
                    task_states=["scored"],
                ),
                "coding_static_repair_v1": self._write_capability_run(
                    "coding_static_repair_v1",
                    surface="local_coding_capability",
                    state="scored",
                    score=1.0,
                    task_states=["scored"],
                ),
                "reasoning_exact_answer_v1": self._write_capability_run(
                    "reasoning_exact_answer_v1",
                    surface="local_reasoning_capability",
                    state="scored",
                    score=1.0,
                    task_states=["scored"],
                ),
            }
        )

        summary = build_capability_summary_artifact(self._request(), execution, self.tempdir)

        self.assertEqual(summary["next_recommended_benchmark_action"]["action"], "repeat_local_capability_run")
        self.assertEqual(summary["next_recommended_benchmark_action"]["surface"], None)
        self.assertEqual(
            {item["confidence_label"] for item in summary["surfaces"] if item["confidence_label"]},
            {"thin_local_sample"},
        )

    def test_summary_uses_legacy_benchmark_summaries_when_capability_run_is_absent(self):
        benchmark_dir = os.path.join(self.tempdir, "artifacts", "capability", "evalplus_humaneval")
        summary_path = os.path.join(benchmark_dir, "summary.json")
        write_json(
            summary_path,
            {
                "benchmark_id": "evalplus_humaneval",
                "status": "completed",
                "primary_metric": {"name": "pass_at_1_plus", "value": 0.75},
                "total_cases": 20,
                "generation_failure_count": 0,
            },
        )
        execution = CapabilityExecution(
            use_case="agentic_coding",
            suite_id=None,
            suite_ids=[],
            benchmark_tier="gold",
            benchmark_group_ids=[],
            benchmark_check_ids=["evalplus_humaneval"],
            components=[],
            score=0.75,
            score_method="mean_primary_metric_v1",
            component_scores={"evalplus_humaneval": 0.75},
            confidence=0.9,
            status="completed",
            benchmark_results={
                "evalplus_humaneval": {
                    "benchmark_id": "evalplus_humaneval",
                    "status": "completed",
                    "primary_metric": {"name": "pass_at_1_plus", "value": 0.75},
                    "total_cases": 20,
                    "generation_failure_count": 0,
                }
            },
            artifacts={"evalplus_humaneval": {"summary_path": summary_path}},
        )

        summary = build_capability_summary_artifact(self._request(), execution, self.tempdir)

        by_surface = {item["surface"]: item for item in summary["surfaces"]}
        self.assertEqual(by_surface["local_coding_capability"]["state"], "scored")
        self.assertEqual(by_surface["local_coding_capability"]["score"], 0.75)
        self.assertEqual(summary["capability_artifacts"][0]["artifact_kind"], "benchmark_summary")
        self.assertEqual(summary["capability_artifacts"][0]["path"], "artifacts/capability/evalplus_humaneval/summary.json")

    def _request(self):
        return RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            benchmark_check_ids=["multiturn_chat_memory_v1"],
            output_dir=self.tempdir,
            simulate=False,
        )

    def _execution(self, artifact_paths):
        artifacts = {}
        for benchmark_id, path in artifact_paths.items():
            artifacts[benchmark_id] = {"capability_run_path": path}
        return CapabilityExecution(
            use_case=None,
            suite_id=None,
            suite_ids=[],
            benchmark_tier="standard",
            benchmark_group_ids=[],
            benchmark_check_ids=list(artifact_paths),
            components=[],
            score=None,
            score_method=None,
            component_scores={},
            confidence=None,
            status="partial",
            benchmark_results={},
            artifacts=artifacts,
        )

    def _write_capability_run(self, benchmark_id, surface, state, score, task_states):
        benchmark_dir = os.path.join(self.tempdir, "artifacts", "capability", benchmark_id)
        path = os.path.join(benchmark_dir, "capability_run.json")
        tasks = []
        for index, task_state in enumerate(task_states):
            tasks.append(
                {
                    "task_id": "%s_%d" % (benchmark_id, index),
                    "task_family": "fixture",
                    "state": task_state,
                    "score": 1.0 if task_state == "scored" else None,
                    "error_class": None if task_state == "scored" else "generation_failed",
                }
            )
        payload = {
            "artifact_spec_version": "0.1.0",
            "artifact_kind": "capability_run",
            "capability_run_id": "caprun_%s" % benchmark_id,
            "created_at": "2026-05-08T12:00:00Z",
            "runner": {"name": "infergrade-runner", "version": "0.2.11-dev"},
            "evidence": {
                "lane": "decision",
                "surface": surface,
                "grade": "thin_local_sample",
                "experimental": True,
                "confidence_label": "thin_local_sample",
            },
            "subject": {
                "model": {"model": "Qwen/Qwen2.5-7B-Instruct"},
                "runtime": {"backend": "llama.cpp"},
                "hardware": {"source": "run_bundle_environment"},
            },
            "protocol": {
                "task_family": "fixture",
                "fixture_revision": "summary-test-fixtures",
                "scorer_type": "exact_match",
                "scoring_policy": "summary_fixture_policy",
                "repetitions": 1,
            },
            "summary": {
                "state": state,
                "score": score,
                "score_dimension": "fixture",
                "failed_count": len([item for item in task_states if item == "failed"]),
                "partial_count": 1 if state == "partial" else 0,
            },
            "tasks": tasks,
            "artifacts": {"manifest": "capability_run.json", "raw_outputs": [], "scoring_outputs": []},
            "claim_boundary": {
                "supported_claims": ["This setup attempted a pinned local %s task." % surface],
                "unsupported_claims": ["This is not a global %s score." % surface],
            },
        }
        write_json(path, payload)
        return path


if __name__ == "__main__":
    unittest.main()
