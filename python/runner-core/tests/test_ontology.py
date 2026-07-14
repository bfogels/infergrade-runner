import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.models import RunRequest
from infergrade.ontology import build_ontology


class OntologyTests(unittest.TestCase):
    def test_qwen_model_name_is_not_mistaken_for_quantization_scheme(self):
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            backend="llama_cpp",
            tier="tier_1",
            quant_artifact="hf://Qwen/Qwen3-8B-GGUF/Qwen_Qwen3-8B-Q4_K_M.gguf",
            quant_artifact_filename="Qwen_Qwen3-8B-Q4_K_M.gguf",
        )

        ontology = build_ontology(request, adapter_version="test")

        self.assertEqual(ontology["quantization"]["quantization_scheme"], "q4_k_m")
        self.assertEqual(ontology["quantization"]["weight_precision_bits"], 4.0)

    def test_qwen2_filename_resolves_trailing_compound_quantization_scheme(self):
        request = RunRequest(
            model="Qwen/Qwen2.5-7B-Instruct",
            backend="llama_cpp",
            tier="tier_1",
            quant_artifact="hf://example/Qwen2.5-7B-Instruct-GGUF/qwen2.5-7b-instruct-q5_k_m.gguf",
            quant_artifact_filename="qwen2.5-7b-instruct-q5_k_m.gguf",
        )

        ontology = build_ontology(request, adapter_version="test")

        self.assertEqual(ontology["quantization"]["quantization_scheme"], "q5_k_m")

    def test_explicit_quantization_scheme_hint_remains_authoritative(self):
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            backend="llama_cpp",
            tier="tier_1",
            quant_artifact="model-Q4_K_M.gguf",
            ontology_hints={"quantization_scheme": "reviewed_q4"},
        )

        ontology = build_ontology(request, adapter_version="test")

        self.assertEqual(ontology["quantization"]["quantization_scheme"], "reviewed_q4")


if __name__ == "__main__":
    unittest.main()
