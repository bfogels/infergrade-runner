import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.models import RunRequest
from infergrade.benchmark_catalog import normalize_request_selection
from infergrade.progress import initialize_progress
from infergrade.runner import _planned_capability_benchmarks


class ProgressTests(unittest.TestCase):
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
