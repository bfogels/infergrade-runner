import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.analysis import recommend, summarize_bundle
from infergrade.models import RunRequest
from infergrade.runner import run_infergrade


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="infergrade-analysis-")

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_summary_and_recommendation_work_for_generated_bundle(self):
        bundle_dir = os.path.join(self.tempdir, "bundle")
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama.cpp",
            tier="standard",
            use_case="general_assistant",
            output_dir=bundle_dir,
            simulate=True,
        )
        run_infergrade(request)
        summary = summarize_bundle(bundle_dir)
        self.assertEqual(summary["result_count"], 1)
        self.assertEqual(summary["checkpoints"], ["Qwen2.5-7B-Instruct"])
        recommendation = recommend([bundle_dir], use_case="general_assistant")
        self.assertEqual(recommendation["input_count"], 1)
        self.assertEqual(recommendation["frontier_count"], 1)


if __name__ == "__main__":
    unittest.main()
