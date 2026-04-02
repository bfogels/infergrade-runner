import sys
import unittest

sys.path.insert(0, "python/runner-core/src")

from infergrade.templates import build_run_request_template


class TemplateTests(unittest.TestCase):
    def test_standard_template_defaults_use_case(self):
        payload = build_run_request_template(tier="standard")
        self.assertEqual(payload["run"]["use_case"], "general_assistant")
        self.assertEqual(payload["runtime"]["backend_image"], "infergrade-llama-cpp:0.1.0-alpha")
        self.assertEqual(
            payload["artifacts"]["quantized_weights"]["uri"],
            "hf://bartowski/Qwen2.5-7B-Instruct-GGUF/Qwen2.5-7B-Instruct-Q4_K_M.gguf",
        )


if __name__ == "__main__":
    unittest.main()
