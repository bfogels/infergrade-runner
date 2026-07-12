import unittest

from infergrade.memory_fit import estimate_memory_fit, standard_context_estimates


class MemoryFitTests(unittest.TestCase):
    def setUp(self):
        self.architecture = {
            "layer_count": 32, "embedding_length": 4096,
            "attention_head_count": 32, "attention_head_count_kv": 8,
            "kv_element_bytes": 2,
        }

    def test_standard_context_allocation_estimates_are_monotonic_not_fit_proof(self):
        estimates = standard_context_estimates(model_weights_bytes=4 * 1024**3, architecture=self.architecture)
        ordered = [estimates[str(tokens)] for tokens in (2048, 8192, 32768)]
        self.assertTrue(all(item["status"] == "estimated" for item in ordered))
        self.assertTrue(all(item["support_proof"] is False for item in ordered))
        self.assertTrue(all(item["fit_verdict"] == "not_evaluated" for item in ordered))
        kv = [item["components"]["kv_cache"]["estimate_bytes"] for item in ordered]
        required = [item["required_memory"]["estimate_range_high_bytes"] for item in ordered]
        self.assertEqual(kv, sorted(kv))
        self.assertEqual(required, sorted(required))
        self.assertTrue(all(item["required_memory"]["upper_bound_bytes"] is None for item in ordered))

    def test_missing_architecture_is_unknown_even_with_exact_weights(self):
        estimate = estimate_memory_fit(context_tokens=8192, model_weights_bytes=4 * 1024**3)
        self.assertEqual(estimate["status"], "unknown")
        self.assertIsNone(estimate["required_memory"]["estimate_range_low_bytes"])
        self.assertEqual(estimate["components"]["model_weights"]["source"], "artifact_exact")
        self.assertEqual(estimate["components"]["kv_cache"]["source"], "unknown")

    def test_runtime_allocations_are_reported_not_measured_and_non_additive(self):
        estimate = estimate_memory_fit(
            context_tokens=2048, model_weights_bytes=4 * 1024**3,
            model_buffer_bytes=5 * 1024**3,
            runtime_reported_kv_cache_bytes=256 * 1024**2,
        )
        self.assertEqual(estimate["components"]["model_buffer"]["source"], "runtime_reported")
        self.assertEqual(estimate["components"]["kv_cache"]["source"], "runtime_reported")
        self.assertEqual(estimate["residency_semantics"]["non_additive_component_groups"], [["model_weights", "model_buffer"]])
        self.assertLess(estimate["required_memory"]["estimate_range_low_bytes"], 7 * 1024**3)

    def test_device_vram_peak_is_not_combined_or_a_fit_verdict(self):
        estimate = estimate_memory_fit(
            context_tokens=2048, model_weights_bytes=4 * 1024**3,
            runtime_reported_kv_cache_bytes=256 * 1024**2,
            peak_memory_bytes=5 * 1024**3,
            peak_memory_measurement_method="nvidia_smi_total_used_delta",
        )
        self.assertEqual(estimate["components"]["observed_peak"]["memory_domain"], "device_vram")
        self.assertFalse(estimate["residency_semantics"]["observed_peak_aggregated"])
        self.assertTrue(estimate["residency_semantics"]["device_vram_fit_prohibited"])
        self.assertEqual(estimate["required_memory"]["memory_domain"], "unified_or_combined_memory")
        self.assertEqual(estimate["fit_verdict_reason"], "device_vram_is_not_combined_system_memory")

    def test_process_and_container_domains_remain_separate(self):
        process = estimate_memory_fit(context_tokens=2048, peak_memory_bytes=GIB, peak_memory_measurement_method="process_rss")
        container = estimate_memory_fit(context_tokens=2048, peak_memory_bytes=GIB, peak_memory_measurement_method="container_cgroup_v2_peak")
        self.assertEqual(process["components"]["observed_peak"]["memory_domain"], "process_memory")
        self.assertEqual(container["components"]["observed_peak"]["memory_domain"], "container_memory")
        self.assertTrue(process["residency_semantics"]["domain_compatibility_required"])

    def test_zero_and_invalid_values_are_rejected(self):
        for kwargs in (
            {"context_tokens": 0},
            {"context_tokens": True},
            {"context_tokens": 2048.0},
            {"context_tokens": "2048"},
            {"context_tokens": 2048, "model_weights_bytes": 0},
            {"context_tokens": 2048, "model_weights_bytes": True},
            {"context_tokens": 2048, "model_weights_bytes": 1.5},
        ):
            with self.assertRaises(ValueError):
                estimate_memory_fit(**kwargs)

    def test_invalid_architecture_shape_is_rejected(self):
        with self.assertRaises(ValueError):
            estimate_memory_fit(context_tokens=2048, architecture="not-an-object")


GIB = 1024**3


if __name__ == "__main__":
    unittest.main()
