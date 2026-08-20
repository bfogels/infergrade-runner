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
        self.assertEqual(ontology["quantization"]["quantization_id"], "gguf:q4_k_m")
        self.assertEqual(ontology["artifact"]["source"]["publisher"], "Qwen")
        self.assertEqual(ontology["artifact"]["source"]["publisher_id"], "huggingface:qwen")

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
        self.assertEqual(ontology["quantization"]["canonicalization_status"], "unknown")
        self.assertIsNone(ontology["quantization"]["quantization_id"])

    def test_quant_aliases_share_one_canonical_identity(self):
        expected_status = {
            "Q4KM.gguf": "alias",
            "Q4_K_M.gguf": "exact",
            "q_4_k_m.gguf": "alias",
            "q4-k-m.gguf": "alias",
            "q4.k.m.gguf": "alias",
        }
        for alias, status in expected_status.items():
            with self.subTest(alias=alias):
                request = RunRequest(
                    model="Qwen/Qwen3-8B",
                    backend="llama.cpp",
                    tier="canary",
                    quant_artifact="hf://PearsonKyle/Qwen3-8B-GGUF/%s" % alias,
                    quant_artifact_filename=alias,
                )
                ontology = build_ontology(request, adapter_version="test")
                self.assertEqual("q4_k_m", ontology["quantization"]["quantization_scheme"])
                self.assertEqual("gguf:q4_k_m", ontology["quantization"]["quantization_id"])
                self.assertEqual(status, ontology["quantization"]["canonicalization_status"])

    def test_generic_and_specific_quant_schemes_remain_distinct(self):
        identities = {}
        for label in ("Q4.gguf", "Q4_0.gguf", "Q4_K_M.gguf", "IQ4_XS.gguf", "TQ1_0.gguf"):
            request = RunRequest(
                model="Qwen/Qwen3-8B",
                backend="llama.cpp",
                tier="canary",
                quant_artifact="hf://publisher/model/%s" % label,
                quant_artifact_filename=label,
            )
            identities[label] = build_ontology(request, adapter_version="test")["quantization"]["quantization_id"]
        self.assertEqual(
            {"gguf:q4", "gguf:q4_0", "gguf:q4_k_m", "gguf:iq4_xs", "gguf:tq1_0"},
            set(identities.values()),
        )

    def test_int4_is_format_qualified_for_vllm(self):
        identities = set()
        for model in ("RedHatAI/Qwen-INT4", "RedHatAI/Qwen-GPTQ-INT4", "RedHatAI/Qwen-AWQ-INT4"):
            request = RunRequest(
                model=model,
                backend="vllm",
                tier="canary",
                quant_artifact="hf://%s/model-INT4.safetensors" % model,
                quant_artifact_filename="model-INT4.safetensors",
            )
            identities.add(build_ontology(request, adapter_version="test")["quantization"]["quantization_id"])
        self.assertEqual({"safetensors:int4", "gptq:int4", "awq:int4"}, identities)

    def test_conflicting_recognized_hint_fails_closed(self):
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="hf://publisher/model/model-Q5_K_M.gguf",
            quant_artifact_filename="model-Q5_K_M.gguf",
            ontology_hints={"quantization_scheme": "Q4KM"},
        )
        quantization = build_ontology(request, adapter_version="test")["quantization"]
        self.assertEqual("q4_k_m", quantization["quantization_scheme"])
        self.assertEqual("conflict", quantization["canonicalization_status"])
        self.assertIsNone(quantization["quantization_id"])

    def test_conflicting_explicit_format_hint_fails_closed(self):
        for filename, explicit_format in (
            ("model-Q4_K_M.gguf", "safetensors"),
            ("model-INT4.safetensors", "gguf"),
        ):
            request = RunRequest(
                model="Qwen/Qwen3-8B",
                backend="vllm",
                tier="canary",
                quant_artifact=filename,
                quant_artifact_filename=filename,
                ontology_hints={"quantization_format": explicit_format},
            )
            quantization = build_ontology(request, adapter_version="test")["quantization"]
            self.assertEqual("conflict", quantization["canonicalization_status"])
            self.assertIsNone(quantization["quantization_id"])

    def test_artifact_source_distinguishes_publishers_even_for_same_bytes(self):
        source_ids = []
        artifact_ids = []
        for publisher in ("PearsonKyle", "RedHatAI"):
            request = RunRequest(
                model="Qwen/Qwen3-8B",
                backend="llama.cpp",
                tier="canary",
                quant_artifact="hf://%s/Qwen3-8B-GGUF/model-Q4_K_M.gguf" % publisher,
                quant_artifact_filename="model-Q4_K_M.gguf",
                quant_artifact_sha256="a" * 64,
            )
            artifact = build_ontology(request, adapter_version="test")["artifact"]
            source_ids.append(artifact["artifact_source_id"])
            artifact_ids.append(artifact["artifact_id"])
            self.assertEqual("huggingface:%s" % publisher.lower(), artifact["source"]["publisher_id"])
        self.assertEqual(2, len(set(source_ids)))
        self.assertEqual(2, len(set(artifact_ids)))

    def test_local_same_path_and_bytes_still_bind_publisher_into_subject(self):
        artifact_ids = []
        subject_ids = []
        for publisher in ("PearsonKyle", "RedHatAI"):
            request = RunRequest(
                model="Qwen/Qwen3-27B",
                backend="vllm",
                tier="canary",
                quant_artifact="/models/qwen-int4",
                quant_artifact_filename="model-INT4.safetensors",
                quant_artifact_sha256="a" * 64,
                quant_artifact_source={"provider": "huggingface", "publisher": publisher},
            )
            ontology = build_ontology(request, adapter_version="test")
            artifact_ids.append(ontology["artifact"]["artifact_id"])
            subject_ids.append(ontology["benchmark_subject"]["subject_id"])
        self.assertEqual(2, len(set(artifact_ids)))
        self.assertEqual(2, len(set(subject_ids)))

    def test_explicit_source_supports_local_vllm_artifact(self):
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            backend="vllm",
            tier="canary",
            quant_artifact="/models/qwen-int4",
            quant_artifact_filename="model-INT4.safetensors",
            quant_artifact_source={
                "provider": "huggingface",
                "repository_id": "RedHatAI/Qwen-INT4",
            },
        )
        artifact = build_ontology(request, adapter_version="test")["artifact"]
        self.assertEqual("huggingface:redhatai", artifact["source"]["publisher_id"])
        self.assertTrue(artifact["artifact_source_id"].startswith("src_"))

    def test_source_provider_aliases_and_case_share_canonical_identity(self):
        source_ids = []
        for provider, repository_id in (
            ("HF", "RedHatAI/Qwen-INT4"),
            ("Hugging Face", "redhatai/qwen-int4"),
            ("huggingface", "REDHATAI/QWEN-INT4"),
        ):
            request = RunRequest(
                model="Qwen/Qwen3-8B",
                backend="vllm",
                tier="canary",
                quant_artifact="/models/qwen-int4",
                quant_artifact_filename="model-INT4.safetensors",
                quant_artifact_source={
                    "provider": provider,
                    "repository_id": repository_id,
                    "publisher_id": "incorrect:untrusted-redundant-value",
                },
            )
            artifact = build_ontology(request, adapter_version="test")["artifact"]
            source_ids.append(artifact["artifact_source_id"])
            self.assertEqual("huggingface", artifact["source"]["provider"])
            self.assertEqual("huggingface:redhatai", artifact["source"]["publisher_id"])
        self.assertEqual(1, len(set(source_ids)))

    def test_local_artifact_does_not_guess_publisher_from_model_family(self):
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="/models/model-Q4_K_M.gguf",
            quant_artifact_filename="model-Q4_K_M.gguf",
        )
        source = build_ontology(request, adapter_version="test")["artifact"]["source"]
        self.assertIsNone(source["publisher"])
        self.assertIsNone(source["publisher_id"])

    def test_relative_local_artifact_does_not_look_like_huggingface_repo(self):
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="models/model-Q4_K_M.gguf",
            quant_artifact_filename="model-Q4_K_M.gguf",
        )
        source = build_ontology(request, adapter_version="test")["artifact"]["source"]
        self.assertIsNone(source["provider"])
        self.assertIsNone(source["publisher"])

    def test_unknown_letter_suffix_does_not_merge_into_known_quant(self):
        for filename in ("model-Q4_K_M_FOO.gguf", "model-Q4_K_M_NL.gguf"):
            request = RunRequest(
                model="Qwen/Qwen3-8B",
                backend="llama.cpp",
                tier="canary",
                quant_artifact=filename,
                quant_artifact_filename=filename,
            )
            quantization = build_ontology(request, adapter_version="test")["quantization"]
            self.assertIsNone(quantization["quantization_id"])
            self.assertEqual("unknown", quantization["canonicalization_status"])

    def test_numeric_shard_suffix_preserves_known_quant(self):
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            backend="llama.cpp",
            tier="canary",
            quant_artifact="model-Q4_K_M_00001-of-00002.gguf",
            quant_artifact_filename="model-Q4_K_M_00001-of-00002.gguf",
        )
        quantization = build_ontology(request, adapter_version="test")["quantization"]
        self.assertEqual("gguf:q4_k_m", quantization["quantization_id"])

    def test_huggingface_repository_overrides_conflicting_publisher_display(self):
        request = RunRequest(
            model="Qwen/Qwen3-8B",
            backend="vllm",
            tier="canary",
            quant_artifact="/models/qwen-int4",
            quant_artifact_filename="model-INT4.safetensors",
            quant_artifact_source={
                "provider": "huggingface",
                "repository_id": "RedHatAI/Qwen-INT4",
                "publisher": "evil-publisher",
            },
        )
        source = build_ontology(request, adapter_version="test")["artifact"]["source"]
        self.assertEqual("RedHatAI", source["publisher"])
        self.assertEqual("huggingface:redhatai", source["publisher_id"])

    def test_vllm_repo_reference_infers_quant_and_artifact_publisher(self):
        request = RunRequest(
            model="RedHatAI/Qwen3-27B-INT4",
            backend="vllm",
            tier="canary",
        )
        ontology = build_ontology(request, adapter_version="test")
        self.assertEqual("safetensors:int4", ontology["quantization"]["quantization_id"])
        self.assertEqual("quantized", ontology["quantization"]["quantization_status"])
        self.assertEqual("RedHatAI", ontology["artifact"]["source"]["publisher"])
        self.assertEqual("huggingface:redhatai", ontology["artifact"]["source"]["publisher_id"])


if __name__ == "__main__":
    unittest.main()
