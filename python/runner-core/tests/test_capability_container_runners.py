import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeNltkData(object):
    def __init__(self, installed):
        self.installed = installed
        self.path = []

    def find(self, resource_path):
        if resource_path == "tokenizers/punkt" and "punkt" in self.installed:
            return resource_path
        if resource_path == "tokenizers/punkt_tab/english" and "punkt_tab" in self.installed:
            return resource_path
        raise LookupError(resource_path)


class CapabilityContainerRunnerTests(unittest.TestCase):
    def test_ifeval_ensures_punkt_and_punkt_tab(self):
        installed = set()
        fake_nltk = types.SimpleNamespace(data=_FakeNltkData(installed))
        downloads = []

        def fake_download(package_name, download_dir=None, quiet=False):
            downloads.append((package_name, download_dir, quiet))
            installed.add(package_name)
            return True

        fake_nltk.download = fake_download
        fake_eval_lib = types.SimpleNamespace()
        fake_instruction_module = types.SimpleNamespace(evaluation_lib=fake_eval_lib)
        module_path = os.path.join(ROOT_DIR, "containers", "capability-ifeval", "runner.py")
        with mock.patch.dict(
            sys.modules,
            {
                "nltk": fake_nltk,
                "instruction_following_eval": fake_instruction_module,
            },
        ):
            module = _load_module("ifeval_runner_test_module", module_path)
            with tempfile.TemporaryDirectory() as tempdir:
                module._ensure_nltk_tokenizers(tempdir)

        self.assertEqual([item[0] for item in downloads], ["punkt", "punkt_tab"])
        self.assertIn("punkt", installed)
        self.assertIn("punkt_tab", installed)

    def test_ifeval_dockerfile_packages_official_input_data(self):
        dockerfile_path = os.path.join(ROOT_DIR, "containers", "capability-ifeval", "Dockerfile")
        with open(dockerfile_path, "r", encoding="utf-8") as handle:
            dockerfile = handle.read()

        self.assertIn("instruction_following_eval/data/input_data.jsonl", dockerfile)
        self.assertIn("ceea2f13fd823c3493d6e6f232f334d083671c94", dockerfile)

    def test_evalplus_mbpp_tasks_are_serialized_before_jsonl_write(self):
        fake_evalplus_data = types.SimpleNamespace(
            get_human_eval_plus=lambda: {},
            get_mbpp_plus=lambda: {},
            write_jsonl=lambda *args, **kwargs: None,
        )
        fake_mbpp = types.SimpleNamespace(
            mbpp_serialize_inputs=lambda task_id, inputs: [["serialized:%s" % value[0]] for value in inputs]
        )
        fake_evalplus_evaluate = types.SimpleNamespace(evaluate=lambda *args, **kwargs: None)
        module_path = os.path.join(ROOT_DIR, "containers", "capability-evalplus", "runner.py")
        with mock.patch.dict(
            sys.modules,
            {
                "evalplus": types.SimpleNamespace(),
                "evalplus.data": fake_evalplus_data,
                "evalplus.data.mbpp": fake_mbpp,
                "evalplus.evaluate": fake_evalplus_evaluate,
            },
        ):
            module = _load_module("evalplus_runner_test_module", module_path)

        task = {
            "task_id": "Mbpp/252",
            "prompt": "Write a function.",
            "entry_point": "f",
            "base_input": [[complex(1, 2)]],
            "plus_input": [[complex(3, 4)]],
        }
        normalized = module._jsonl_ready_task("mbpp", task)
        self.assertEqual(normalized["base_input"], [["serialized:(1+2j)"]])
        self.assertEqual(normalized["plus_input"], [["serialized:(3+4j)"]])
        self.assertNotIn(complex(1, 2), normalized["base_input"][0])

    def test_evalplus_humaneval_tasks_are_preserved(self):
        fake_evalplus_data = types.SimpleNamespace(
            get_human_eval_plus=lambda: {},
            get_mbpp_plus=lambda: {},
            write_jsonl=lambda *args, **kwargs: None,
        )
        fake_mbpp = types.SimpleNamespace(mbpp_serialize_inputs=lambda task_id, inputs: self.fail("unexpected MBPP serializer"))
        fake_evalplus_evaluate = types.SimpleNamespace(evaluate=lambda *args, **kwargs: None)
        module_path = os.path.join(ROOT_DIR, "containers", "capability-evalplus", "runner.py")
        with mock.patch.dict(
            sys.modules,
            {
                "evalplus": types.SimpleNamespace(),
                "evalplus.data": fake_evalplus_data,
                "evalplus.data.mbpp": fake_mbpp,
                "evalplus.evaluate": fake_evalplus_evaluate,
            },
        ):
            module = _load_module("evalplus_runner_humaneval_test_module", module_path)

        task = {
            "task_id": "HumanEval/0",
            "prompt": "Write a function.",
            "entry_point": "f",
            "base_input": [[1]],
            "plus_input": [[2]],
        }
        self.assertEqual(module._jsonl_ready_task("humaneval", task), task)


if __name__ == "__main__":
    unittest.main()
