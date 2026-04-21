import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.demo_evidence import DEMO_SOURCE_ORIGIN, tinyllama_demo_quant_ladder_results
from infergrade.reports import render_bundle_report


class DemoEvidenceTests(unittest.TestCase):
    def test_demo_quant_ladder_renders_standalone_report(self):
        results = tinyllama_demo_quant_ladder_results()
        manifest = {
            "bundle_id": "demo_tinyllama_assistant_quant_ladder",
            "created_at": "2026-04-21T00:00:00Z",
            "files": {"report": "report.md"},
            "demo_evidence": True,
        }
        summary = {
            "bundle_id": manifest["bundle_id"],
            "result_count": len(results),
            "simulated": True,
            "source_bundle_origin": DEMO_SOURCE_ORIGIN,
        }

        report = render_bundle_report(manifest, summary, {"valid": True}, results)

        self.assertIn("TinyLlama", report)
        self.assertIn("Decision suite", report)
        self.assertIn("interactive_chat_v1", report)
        self.assertIn("24.00", report)
        self.assertEqual(results[0]["provenance"]["source_bundle_origin"], DEMO_SOURCE_ORIGIN)


if __name__ == "__main__":
    unittest.main()
