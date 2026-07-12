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
        self.assertEqual(by_surface["local_assistant_capability"]["score"], None)
        self.assertEqual(by_surface["local_assistant_capability"]["score_observed"], 1.0)
        self.assertFalse(by_surface["local_assistant_capability"]["score_ready"])
        self.assertEqual(by_surface["local_assistant_capability"]["score_coverage"]["coverage_fraction"], 0.25)
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

    def test_repeated_local_sample_reports_repeatability_and_instability(self):
        execution = self._execution(
            {
                "multiturn_chat_memory_v1": self._write_capability_run(
                    "multiturn_chat_memory_v1",
                    surface="local_assistant_capability",
                    state="scored",
                    score=0.5,
                    task_states=["scored", "failed", "scored"],
                    repetitions=3,
                    task_metrics=[
                        {"latency_ms": 100.0, "time_to_first_token_ms": 20.0, "tokens_per_second": 40.0, "score": 1.0},
                        {"latency_ms": 400.0, "time_to_first_token_ms": 90.0, "tokens_per_second": 10.0, "score": None},
                        {"latency_ms": 120.0, "time_to_first_token_ms": 22.0, "tokens_per_second": 38.0, "score": 1.0},
                    ],
                )
            }
        )

        summary = build_capability_summary_artifact(self._request(), execution, self.tempdir)

        self.assertEqual(validate_capability_summary_artifact(summary), [])
        assistant = {item["surface"]: item for item in summary["surfaces"]}["local_assistant_capability"]
        self.assertEqual(assistant["confidence_label"], "repeated_local_sample")
        self.assertEqual(assistant["repeatability"]["repetition_count"], 3)
        self.assertGreater(assistant["repeatability"]["latency_p95_ms"], assistant["repeatability"]["latency_median_ms"])
        self.assertTrue(assistant["repeatability"]["unstable"])
        self.assertIn("failure_rate_high", assistant["repeatability"]["instability_reasons"])
        artifact = summary["capability_artifacts"][0]
        self.assertEqual(artifact["confidence_label"], "repeated_local_sample")
        self.assertIn("Repeated local evidence", artifact["confidence_explanation"])

    def test_legacy_reference_label_is_canonicalized_to_sampled_reference(self):
        execution = self._execution(
            {
                "evalplus_humaneval": self._write_capability_run(
                    "evalplus_humaneval",
                    surface="local_coding_capability",
                    state="scored",
                    score=0.75,
                    task_states=["scored", "scored"],
                    lane="reference",
                    grade="reference_sample",
                    confidence_label="reference_sample",
                )
            }
        )

        summary = build_capability_summary_artifact(self._request(), execution, self.tempdir)

        coding = {item["surface"]: item for item in summary["surfaces"]}["local_coding_capability"]
        self.assertEqual(coding["confidence_label"], "sampled_reference")
        self.assertEqual(summary["capability_artifacts"][0]["confidence_label"], "sampled_reference")

    def test_composite_confidence_uses_weakest_score_contributing_evidence(self):
        execution = self._execution(
            {
                "evalplus_humaneval": self._write_capability_run(
                    "evalplus_humaneval",
                    surface="local_coding_capability",
                    state="scored",
                    score=0.75,
                    task_states=["scored"],
                    lane="reference",
                    confidence_label="sampled_reference",
                ),
                "evalplus_mbpp": self._write_capability_run(
                    "evalplus_mbpp",
                    surface="local_coding_capability",
                    state="scored",
                    score=0.65,
                    task_states=["scored"],
                    lane="decision",
                    confidence_label="thin_local_sample",
                ),
            }
        )

        summary = build_capability_summary_artifact(self._request(), execution, self.tempdir)

        coding = {item["surface"]: item for item in summary["surfaces"]}["local_coding_capability"]
        self.assertEqual(coding["confidence_label"], "thin_local_sample")
        self.assertEqual(coding["score_version"], "local_coding_score_v2")
        self.assertTrue(coding["score_ready"])
        self.assertEqual(coding["score_failed_gates"], [])
        self.assertEqual(coding["score_confidence_basis"]["calibration_status"], "not_psychometrically_calibrated")

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
        self.assertIsNone(by_surface["local_coding_capability"]["score"])
        self.assertEqual(by_surface["local_coding_capability"]["score_observed"], 0.75)
        self.assertFalse(by_surface["local_coding_capability"]["score_ready"])
        self.assertIn("insufficient_scored_components", by_surface["local_coding_capability"]["score_failed_gates"])
        self.assertEqual(summary["capability_artifacts"][0]["artifact_kind"], "benchmark_summary")
        self.assertEqual(summary["capability_artifacts"][0]["path"], "artifacts/capability/evalplus_humaneval/summary.json")

    def test_summary_keeps_humaneval_and_mbpp_artifacts_distinct(self):
        execution = self._execution(
            {
                "evalplus_humaneval": self._write_capability_run(
                    "evalplus_humaneval",
                    surface="local_coding_capability",
                    state="scored",
                    score=0.75,
                    task_states=["scored", "scored"],
                    lane="reference",
                    grade="sampled_reference",
                    confidence_label="sampled_reference",
                ),
                "evalplus_mbpp": self._write_capability_run(
                    "evalplus_mbpp",
                    surface="local_coding_capability",
                    state="scored",
                    score=0.5,
                    task_states=["scored", "scored"],
                    lane="reference",
                    grade="sampled_reference",
                    confidence_label="sampled_reference",
                ),
            }
        )

        summary = build_capability_summary_artifact(self._request(), execution, self.tempdir)

        self.assertEqual(validate_capability_summary_artifact(summary), [])
        by_surface = {item["surface"]: item for item in summary["surfaces"]}
        coding = by_surface["local_coding_capability"]
        self.assertEqual(coding["state"], "scored")
        self.assertEqual(coding["lane"], "reference")
        self.assertEqual(coding["confidence_label"], "sampled_reference")
        self.assertEqual(coding["task_count"], 4)
        self.assertEqual(
            [item["benchmark_id"] for item in coding["capability_artifacts"]],
            ["evalplus_humaneval", "evalplus_mbpp"],
        )
        self.assertEqual(
            [item["benchmark_id"] for item in summary["capability_artifacts"]],
            ["evalplus_humaneval", "evalplus_mbpp"],
        )

    def test_summary_indexes_quant_fidelity_reference_artifact(self):
        execution = self._execution(
            {
                "perplexity_reference_v1": self._write_capability_run(
                    "perplexity_reference_v1",
                    surface="quant_fidelity",
                    state="scored",
                    score=3.25,
                    task_states=["scored"],
                    lane="reference",
                    grade="sampled_reference",
                    confidence_label="sampled_reference",
                )
            }
        )

        summary = build_capability_summary_artifact(self._request(), execution, self.tempdir)

        self.assertEqual(validate_capability_summary_artifact(summary), [])
        by_surface = {item["surface"]: item for item in summary["surfaces"]}
        quant = by_surface["quant_fidelity"]
        self.assertEqual(quant["state"], "scored")
        self.assertEqual(quant["lane"], "reference")
        self.assertEqual(quant["confidence_label"], "sampled_reference")
        self.assertEqual(quant["score"], 3.25)
        self.assertEqual(quant["capability_artifacts"][0]["benchmark_id"], "perplexity_reference_v1")

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

    def _write_capability_run(
        self,
        benchmark_id,
        surface,
        state,
        score,
        task_states,
        lane="decision",
        grade="thin_local_sample",
        confidence_label="thin_local_sample",
        repetitions=1,
        task_metrics=None,
    ):
        benchmark_dir = os.path.join(self.tempdir, "artifacts", "capability", benchmark_id)
        path = os.path.join(benchmark_dir, "capability_run.json")
        tasks = []
        task_metrics = task_metrics or [{} for _ in task_states]
        for index, task_state in enumerate(task_states):
            metrics = task_metrics[index] if index < len(task_metrics) else {}
            tasks.append(
                {
                    "task_id": "%s_%d" % (benchmark_id, index),
                    "task_family": "fixture",
                    "state": task_state,
                    "score": metrics.get("score") if "score" in metrics else (1.0 if task_state == "scored" else None),
                    "error_class": None if task_state == "scored" else "generation_failed",
                    "latency_ms": metrics.get("latency_ms"),
                    "time_to_first_token_ms": metrics.get("time_to_first_token_ms"),
                    "tokens_per_second": metrics.get("tokens_per_second"),
                }
            )
        payload = {
            "artifact_spec_version": "0.1.0",
            "artifact_kind": "capability_run",
            "capability_run_id": "caprun_%s" % benchmark_id,
            "created_at": "2026-05-08T12:00:00Z",
            "runner": {"name": "infergrade-runner", "version": "0.2.11-dev"},
            "evidence": {
                "lane": lane,
                "surface": surface,
                "grade": grade,
                "experimental": True,
                "confidence_label": confidence_label,
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
                "repetitions": repetitions,
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
