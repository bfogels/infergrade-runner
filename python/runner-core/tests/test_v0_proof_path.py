import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, "python/runner-core/src")

from infergrade.models import RunRequest
from infergrade.runner import run_infergrade


class V0ProofPathTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="infergrade-v0-proof-")

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_tinyllama_native_decision_suite_writes_report_and_selection_summary(self):
        output_dir = os.path.join(self.tempdir, "tinyllama-native-decision")
        request = RunRequest(
            model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
            backend="llama.cpp",
            tier="canary",
            use_case="general_assistant",
            execution_mode="local_native",
            capability_suite_ids=["chat_instruction_following"],
            benchmark_group_ids=["deployment_chat"],
            benchmark_check_ids=["interactive_chat_v1"],
            quant_artifact="hf://TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf",
            output_dir=output_dir,
            simulate=True,
        )

        with patch(
            "infergrade.adapters.llama_cpp.LlamaCppAdapter.runtime_metadata",
            return_value={
                "container_image": None,
                "container_runtime": None,
                "container_command": None,
                "native_binary": "/usr/bin/llama-cli",
                "native_server_binary": "/usr/bin/llama-server",
            },
        ):
            result = run_infergrade(request)

        self.assertEqual(result["result_count"], 1)
        self.assertTrue(os.path.exists(os.path.join(output_dir, "manifest.json")))
        self.assertTrue(os.path.exists(os.path.join(output_dir, "report.md")))
        self.assertEqual(result["report_path"], os.path.join(output_dir, "report.md"))

        with open(os.path.join(output_dir, "summary.json"), "r", encoding="utf-8") as handle:
            summary = json.load(handle)
        self.assertEqual(summary["model_family"], "TinyLlama")
        self.assertEqual(summary["benchmark_scope"]["scope"], "decision")
        self.assertEqual(summary["benchmark_scope"]["scope_label"], "Decision suite")
        self.assertEqual(summary["benchmark_scope"]["metadata_confidence"], "unknown")
        self.assertEqual(summary["benchmark_check_ids"], ["interactive_chat_v1"])

        with open(os.path.join(output_dir, "manifest.json"), "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["files"]["report"], "report.md")

        with open(os.path.join(output_dir, "results", "interactive_chat_v1.json"), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        selection = payload["configuration"]["benchmark_selection"]
        self.assertEqual(selection["benchmark_scope"]["scope"], "decision")
        self.assertEqual(selection["benchmark_check_ids"], ["interactive_chat_v1"])
        self.assertEqual(payload["execution"]["execution_mode"], "local_native")

        with open(os.path.join(output_dir, "report.md"), "r", encoding="utf-8") as handle:
            report = handle.read()
        self.assertIn("TinyLlama-1.1B-Chat-v1.0", report)
        self.assertIn("Decision suite", report)
        self.assertIn("Metadata confidence: unknown", report)
        self.assertIn("interactive_chat_v1", report)
        self.assertIn("local_native", report)


if __name__ == "__main__":
    unittest.main()
