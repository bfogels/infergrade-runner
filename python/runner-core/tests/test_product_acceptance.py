import importlib.util
import json
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts" / "run_product_acceptance.py"


def load_module():
    spec = importlib.util.spec_from_file_location("run_product_acceptance", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProductAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_checked_in_product_invariants_pass(self):
        checks = self.module.source_checks()
        self.assertTrue(checks)
        self.assertEqual([item for item in checks if item["status"] != "pass"], [])

    def test_manual_lanes_keep_physical_and_model_proof_explicit(self):
        lanes = {item["id"]: item for item in self.module.MANUAL_LANES}
        self.assertEqual(lanes["windows_nvidia_execution"]["status"], "manual_required")
        self.assertEqual(lanes["linux_nvidia_execution"]["status"], "manual_required")
        self.assertEqual(lanes["specialized_runtime_model_canaries"]["status"], "manual_required")
        self.assertIn("archive and version receipts alone", lanes["specialized_runtime_model_canaries"]["evidence"])

    def test_skip_commands_writes_a_truthful_evidence_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "acceptance.json"
            exit_code = self.module.main(["--skip-commands", "--output", str(output)])
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["autonomous_status"], "pass")
        self.assertEqual(payload["commands"], [])
        self.assertIn("do not prove real model compatibility", payload["claim_boundary"])


if __name__ == "__main__":
    unittest.main()
