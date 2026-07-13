import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.benchmark_catalog import check_index, load_capability_catalog


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
SCRIPT_PATH = os.path.join(ROOT_DIR, "scripts", "plan_local_evidence_dogfood.py")


def load_dogfood_module():
    spec = importlib.util.spec_from_file_location("plan_local_evidence_dogfood", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LocalEvidenceDogfoodTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.mkdtemp(prefix="infergrade-dogfood-test-")
        self.module = load_dogfood_module()

    def tearDown(self):
        shutil.rmtree(self.tempdir)

    def test_lane_plans_reference_declared_catalog_checks(self):
        catalog_checks = check_index(load_capability_catalog())
        lane_check_ids = [
            check_id
            for lane in self.module.LANE_PLANS
            for check_id in lane["benchmark_check_ids"]
        ]

        self.assertEqual([], [check_id for check_id in lane_check_ids if check_id not in catalog_checks])
        self.assertIn("mmlu_pro_reference_v1", lane_check_ids)
        self.assertIn("evalplus_humaneval", lane_check_ids)
        self.assertIn("evalplus_mbpp", lane_check_ids)
        self.assertIn("perplexity_reference_v1", lane_check_ids)

    def test_generate_plan_writes_distinct_requests_and_token_free_commands(self):
        model_path = os.path.join(self.tempdir, "tiny-model.Q4_K_M.gguf")
        with open(model_path, "wb") as handle:
            handle.write(b"dogfood-model")
        expected_sha = hashlib.sha256(b"dogfood-model").hexdigest()
        matrix = {
            "matrix_id": "unit-test-dogfood",
            "hardware_label": "unit-test-machine",
            "models": [
                {
                    "slot": "small_fast",
                    "model_family": "TinyTest",
                    "checkpoint": "TinyTest-1B-Instruct",
                    "gguf_path": model_path,
                    "quantization_scheme": "Q4_K_M",
                    "source_uri": "hf://example/tiny-test/tiny-model.Q4_K_M.gguf",
                    "source_revision": "unit-test-revision",
                    "include_lanes": [
                        "local_core_decision",
                        "mmlu_pro_sampled_reference",
                        "evalplus_humaneval_reference",
                        "evalplus_mbpp_reference",
                        "quant_fidelity_reference",
                    ],
                }
            ],
        }

        result = self.module.generate_plan(matrix, self.path("plans"), compute_sha256=True)

        self.assertEqual(result["request_count"], 5)
        manifest = self.read_json(result["manifest_path"])
        self.assertEqual(manifest["artifact_kind"], "local_evidence_dogfood_plan")
        provenance = manifest["models"][0]["provenance"]
        self.assertEqual(provenance["artifact_sha256"], expected_sha)
        lane_ids = [item["lane_id"] for item in manifest["models"][0]["lanes"]]
        self.assertEqual(
            lane_ids,
            [
                "local_core_decision",
                "mmlu_pro_sampled_reference",
                "evalplus_humaneval_reference",
                "evalplus_mbpp_reference",
                "quant_fidelity_reference",
            ],
        )
        request_paths = [
            os.path.join(os.path.dirname(result["manifest_path"]), item["request_path"])
            for item in manifest["models"][0]["lanes"]
        ]
        requests = [self.read_json(path) for path in request_paths]
        self.assertTrue(all(item["metadata"]["evidence_source"] == "agent_dogfood" for item in requests))
        by_checks = {
            tuple(payload["run"]["benchmark_check_ids"]): payload
            for payload in requests
        }
        self.assertIn(("mmlu_pro_reference_v1",), by_checks)
        self.assertIn(("evalplus_humaneval",), by_checks)
        self.assertIn(("evalplus_mbpp",), by_checks)
        self.assertIn(("perplexity_reference_v1",), by_checks)
        self.assertEqual(by_checks[("evalplus_mbpp",)]["run"]["use_case"], "agentic_coding")
        self.assertEqual(by_checks[("perplexity_reference_v1",)]["run"]["capability_suite_ids"], ["quant_fidelity"])

        with open(result["commands_path"], "r", encoding="utf-8") as handle:
            commands_text = handle.read()
        with open(result["upload_commands_path"], "r", encoding="utf-8") as handle:
            upload_text = handle.read()
        combined = commands_text + "\n" + upload_text + "\n" + json.dumps(manifest, sort_keys=True)
        for forbidden in ("PAIRING_CODE_PROVIDED_OUT_OF_BAND", "pair-code", "runner_token", "Authorization:", "INFERGRADE_HUB_TOKEN"):
            self.assertNotIn(forbidden, combined)
        self.assertIn("python3 -m infergrade run --request-file", commands_text)
        self.assertIn("python3 -m infergrade upload-bundle", upload_text)

    def test_generate_plan_uses_source_uri_when_local_gguf_is_not_present(self):
        matrix = {
            "matrix_id": "remote-source-dogfood",
            "models": [
                {
                    "slot": "downloaded_small",
                    "model_family": "TinyTest",
                    "checkpoint": "TinyTest-Download",
                    "gguf_path": os.path.join(self.tempdir, "missing.gguf"),
                    "quantization_scheme": "Q4_K_M",
                    "source_uri": "hf://example/tiny-test/missing.gguf",
                    "source_revision": "unit-test-revision",
                    "include_lanes": ["local_core_decision"],
                }
            ],
        }

        result = self.module.generate_plan(matrix, self.path("remote-plans"), compute_sha256=True)

        manifest = self.read_json(result["manifest_path"])
        self.assertFalse(manifest["models"][0]["provenance"]["gguf_exists"])
        self.assertEqual(
            manifest["models"][0]["provenance"]["artifact_uri_for_request"],
            "hf://example/tiny-test/missing.gguf",
        )
        self.assertEqual(manifest["models"][0]["provenance"]["gguf_filename"], "missing.gguf")
        request_path = os.path.join(
            os.path.dirname(result["manifest_path"]),
            manifest["models"][0]["lanes"][0]["request_path"],
        )
        request = self.read_json(request_path)
        self.assertEqual(request["artifacts"]["quantized_weights"]["uri"], "hf://example/tiny-test/missing.gguf")
        self.assertEqual(request["artifacts"]["quantized_weights"]["filename"], "missing.gguf")

    def test_generate_plan_preserves_explicit_generation_policy(self):
        matrix = {
            "matrix_id": "direct-answer-policy",
            "models": [{
                "slot": "qwen3",
                "model_family": "Qwen3",
                "checkpoint": "Qwen3-4B",
                "source_uri": "hf://Qwen/Qwen3-4B-GGUF/Qwen3-4B-Q4_K_M.gguf",
                "quantization_scheme": "Q4_K_M",
                "generation_preset": "deterministic_direct_answer_v1",
                "include_lanes": ["local_core_decision"],
            }],
        }
        result = self.module.generate_plan(matrix, self.path("policy-plans"), compute_sha256=False)
        manifest = self.read_json(result["manifest_path"])
        request_path = os.path.join(
            os.path.dirname(result["manifest_path"]),
            manifest["models"][0]["lanes"][0]["request_path"],
        )
        request = self.read_json(request_path)
        self.assertEqual(request["overrides"]["generation_preset"], "deterministic_direct_answer_v1")

    def test_placeholder_revision_is_not_emitted_as_provenance(self):
        provenance = self.module.model_provenance(
            {
                "slot": "placeholder_revision",
                "source_uri": "hf://example/tiny-test/model.gguf",
                "source_revision": "pinned-or-unspecified",
                "artifact_sha256": "replace-me",
            },
            compute_sha256=False,
        )

        self.assertEqual(provenance["gguf_filename"], "model.gguf")
        self.assertIsNone(provenance["source_revision"])
        self.assertIsNone(provenance["artifact_sha256"])

    def test_model_requires_local_path_or_source_uri(self):
        with self.assertRaises(ValueError) as raised:
            self.module.model_provenance({"slot": "missing_artifact"}, compute_sha256=False)

        self.assertIn("must set gguf_path or source_uri", str(raised.exception))

    def test_init_matrix_template_does_not_contain_real_secret_material(self):
        template_path = self.path("matrix.template.json")

        result = self.module.write_template(template_path)

        self.assertEqual(result["template_path"], template_path)
        with open(template_path, "r", encoding="utf-8") as handle:
            text = handle.read()
        self.assertNotIn("PAIRING_CODE_PROVIDED_OUT_OF_BAND", text)
        self.assertNotIn("INFERGRADE_HUB_TOKEN", text)

    def path(self, *parts):
        return os.path.join(self.tempdir, *parts)

    def read_json(self, path):
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)


if __name__ == "__main__":
    unittest.main()
