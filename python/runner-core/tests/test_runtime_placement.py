import json
import os
import tempfile
import unittest
from types import SimpleNamespace

from infergrade.runtime_placement import parse_runtime_placement, record_runtime_placement


class RuntimePlacementTests(unittest.TestCase):
    def test_partial_offload_and_actual_context(self):
        receipt = parse_runtime_placement(
            "load_tensors: offloaded 12/33 layers to GPU\n"
            "load_tensors: CUDA0 model buffer size = 2 GiB\n"
            "load_tensors: CPU_Mapped model buffer size = 300 MiB\n"
            "llama_kv_cache: CUDA0 KV buffer size = 128 MiB\n"
            "llama_context: n_ctx = 8192\nllama_context: n_ctx_per_seq = 4096\n",
            ["llama-server", "--fit", "on", "-c", "4096"],
        )
        self.assertEqual(receipt["layer_placement"], "partial_layer_offload")
        self.assertEqual(receipt["gpu_devices_with_positive_model_buffers"], ["CUDA0"])
        self.assertEqual(receipt["requested_context_tokens"], 4096)
        self.assertEqual(receipt["observed_context_tokens"], 8192)
        self.assertEqual(receipt["observed_context_per_sequence_tokens"], 4096)
        self.assertEqual(receipt["allocations"][1]["bytes"], 128 * 1024**2)

    def test_dual_gpu_requires_positive_model_allocations(self):
        logs = ("ggml_cuda_init: found CUDA0 and CUDA1\n"
                "load_tensors: offloaded 33/33 layers to GPU\n"
                "load_tensors: CUDA0 model buffer size = 4 GiB\n"
                "llama_kv_cache: CUDA1 KV buffer size = 4 MiB\n")
        command = ["llama-server", "--device", "CUDA0,CUDA1", "--split-mode", "layer", "--tensor-split", "1,1"]
        first = parse_runtime_placement(logs, command)
        self.assertEqual(first["requested_devices"], ["CUDA0", "CUDA1"])
        self.assertEqual(first["requested_tensor_split"], "1,1")
        self.assertEqual(first["gpu_devices_with_positive_model_buffers"], ["CUDA0"])
        second = parse_runtime_placement(logs + "load_tensors: CUDA1 model buffer size = 4 GiB\n", command)
        self.assertEqual(second["gpu_devices_with_positive_model_buffers"], ["CUDA0", "CUDA1"])

    def test_all_layers_does_not_erase_cpu_or_unified_memory(self):
        receipt = parse_runtime_placement(
            "0.00.121.629 I load_tensors: offloaded 6/6 layers to GPU\n"
            "0.00.121.630 I load_tensors: CPU_Mapped model buffer size = 0.12 MiB\n"
            "0.00.121.630 I load_tensors: MTL0_Mapped model buffer size = 0.99 MiB\n"
            "0.00.122.024 I llama_kv_cache: MTL0 KV buffer size = 2.50 MiB\n", [],
        )
        self.assertEqual(receipt["layer_placement"], "all_reported_layers_offloaded")
        self.assertEqual(receipt["gpu_devices_with_positive_model_buffers"], ["MTL0"])
        self.assertTrue(any(item["device"] == "CPU_Mapped" for item in receipt["allocations"]))
        self.assertIn("does not prove zero CPU/RAM", receipt["claim_boundary"])

    def test_unknown_zero_and_contradictory_evidence(self):
        self.assertEqual(parse_runtime_placement("", [])["layer_placement"], "unknown")
        zero = parse_runtime_placement("load_tensors: offloaded 0/33 layers to GPU", [])
        self.assertEqual(zero["layer_placement"], "no_reported_layers_offloaded")
        conflict = parse_runtime_placement(
            "load_tensors: offloaded 12/33 layers to GPU\nload_tensors: offloaded 33/33 layers to GPU\n"
            "llama_context: n_ctx = 4096\nllama_context: n_ctx = 8192", [],
        )
        self.assertEqual(conflict["layer_placement"], "unknown")
        self.assertIsNone(conflict["observed_context_tokens"])
        self.assertIn("contradictory_layer_evidence", conflict["reason_codes"])
        invalid = parse_runtime_placement("load_tensors: offloaded 35/33 layers to GPU", [])
        self.assertIsNone(invalid["offloaded_layers"])

    def test_payloads_and_arbitrary_output_are_not_options_or_markers(self):
        receipt = parse_runtime_placement(
            "offloaded 33/33 layers\nCUDA0 model buffer size = 4 GiB\nn_ctx = 4096",
            ["llama-cli", "--model", "/secret/model.gguf", "--prompt", "--fit", "--fit", "off"],
        )
        self.assertEqual(receipt["fit_argument"], "off")
        self.assertEqual(receipt["layer_placement"], "unknown")
        self.assertIsNone(receipt["gpu_devices_with_positive_model_buffers"])
        self.assertNotIn("secret", json.dumps(receipt))
        shell = parse_runtime_placement("", ["docker", "sh", "-lc", "llama-perplexity -m /secret -p --fit --fit on -c 128"])
        self.assertEqual(shell["fit_argument"], "on")
        self.assertEqual(shell["requested_context_tokens"], 128)

    def test_bounded_allocation_evidence(self):
        logs = "\n".join("load_tensors: CUDA%d model buffer size = 1 MiB" % i for i in range(200))
        receipt = parse_runtime_placement(logs, [])
        self.assertEqual(len(receipt["allocations"]), 128)
        self.assertTrue(receipt["allocation_evidence_truncated"])
        self.assertIn("allocation_evidence_truncated", receipt["reason_codes"])

    def test_oversized_or_malformed_device_buffers_are_ignored(self):
        receipt = parse_runtime_placement(
            "load_tensors: CUDA" + "1" * 10000 + " model buffer size = 1 MiB\n"
            "load_tensors: CUDA0 model buffer size = .. MiB\n"
            "load_tensors: CUDA0 model buffer size = 0 MiB\n", [],
        )
        self.assertIsNone(receipt["gpu_devices_with_positive_model_buffers"])
        self.assertLess(len(json.dumps(receipt)), 2000)

    def test_invocations_persist_separately_and_context_partitions_identity(self):
        with tempfile.TemporaryDirectory() as root:
            request = SimpleNamespace(output_dir=root, runtime_selector={"accelerator": {"api": "cuda"}})
            first = record_runtime_placement(request, ["--fit", "on"], "llama_context: n_ctx = 4096", "capability_server")
            repeated = record_runtime_placement(request, ["--fit", "on"], "llama_context: n_ctx = 4096", "capability_server")
            larger = record_runtime_placement(request, ["--fit", "on"], "llama_context: n_ctx = 8192", "capability_server")
            self.assertNotEqual(first["invocation_id"], repeated["invocation_id"])
            self.assertEqual(first["placement_fingerprint"], repeated["placement_fingerprint"])
            self.assertNotEqual(first["placement_fingerprint"], larger["placement_fingerprint"])
            self.assertEqual(len(first["placement_fingerprint"]), 64)
            path = os.path.join(root, "artifacts", "runtime-placement", first["invocation_id"] + ".json")
            with open(path) as handle:
                self.assertEqual(json.load(handle), first)


if __name__ == "__main__":
    unittest.main()
