import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

RUNNER_CORE_SRC = os.path.join(ROOT_DIR, "python", "runner-core", "src")
if RUNNER_CORE_SRC not in sys.path:
    sys.path.insert(0, RUNNER_CORE_SRC)


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

    def test_ifeval_tier_sampling_is_order_independent_and_covers_instruction_types(self):
        fake_nltk = types.SimpleNamespace(data=_FakeNltkData({"punkt", "punkt_tab"}))
        fake_nltk.download = lambda *_args, **_kwargs: True
        fake_instruction_module = types.SimpleNamespace(
            evaluation_lib=types.SimpleNamespace()
        )
        module_path = os.path.join(ROOT_DIR, "containers", "capability-ifeval", "runner.py")
        with mock.patch.dict(
            sys.modules,
            {
                "nltk": fake_nltk,
                "instruction_following_eval": fake_instruction_module,
            },
        ):
            module = _load_module("ifeval_sampling_test_module", module_path)

        inputs = [
            types.SimpleNamespace(key="prefix-a", instruction_id_list=["type-a"]),
            types.SimpleNamespace(key="prefix-a-2", instruction_id_list=["type-a"]),
            types.SimpleNamespace(key="later-b", instruction_id_list=["type-b"]),
            types.SimpleNamespace(key="later-c", instruction_id_list=["type-c"]),
        ]
        forward = module._sample_inputs(inputs, 3)
        reverse = module._sample_inputs(list(reversed(inputs)), 3)

        self.assertEqual({item.key for item in forward}, {item.key for item in reverse})
        self.assertEqual(
            {instruction for item in forward for instruction in item.instruction_id_list},
            {"type-a", "type-b", "type-c"},
        )
        self.assertNotEqual(
            {item.key for item in forward},
            {item.key for item in inputs[:3]},
        )

    def test_ifeval_prepare_records_tier_coverage_and_selection_identity(self):
        inputs = [
            types.SimpleNamespace(
                key="case-%d" % index,
                instruction_id_list=["type-%d" % (index % 3)],
                prompt="prompt-%d" % index,
                kwargs=[{}],
            )
            for index in range(6)
        ]
        fake_nltk = types.SimpleNamespace(data=_FakeNltkData({"punkt", "punkt_tab"}))
        fake_nltk.download = lambda *_args, **_kwargs: True
        fake_instruction_module = types.SimpleNamespace(
            evaluation_lib=types.SimpleNamespace(
                read_prompt_list=lambda _path: inputs,
            )
        )
        module_path = os.path.join(ROOT_DIR, "containers", "capability-ifeval", "runner.py")
        with mock.patch.dict(
            sys.modules,
            {
                "nltk": fake_nltk,
                "instruction_following_eval": fake_instruction_module,
            },
        ):
            module = _load_module("ifeval_prepare_metadata_test_module", module_path)

        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.object(module, "_ensure_nltk_tokenizers"):
                module.prepare(tempdir, limit=3)
            with open(
                os.path.join(tempdir, "benchmark_metadata.json"),
                encoding="utf-8",
            ) as handle:
                metadata = json.load(handle)

        self.assertEqual(
            metadata["sample_policy"],
            "greedy_instruction_coverage_3_sha256_v1",
        )
        self.assertEqual(metadata["instruction_type_count"], 3)
        self.assertEqual(metadata["full_instruction_type_count"], 3)
        self.assertEqual(metadata["instruction_type_coverage_fraction"], 1.0)
        self.assertEqual(len(metadata["selection_sha256"]), 64)

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

    def test_evalplus_tier_sampling_is_hash_ranked_and_order_independent(self):
        fake_evalplus_data = types.SimpleNamespace(
            get_human_eval_plus=lambda: {},
            get_mbpp_plus=lambda: {},
            write_jsonl=lambda *args, **kwargs: None,
        )
        fake_mbpp = types.SimpleNamespace(
            mbpp_serialize_inputs=lambda _task_id, inputs: inputs
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
            module = _load_module("evalplus_sampling_test_module", module_path)

        items = [
            (
                "HumanEval/%d" % index,
                {"task_id": "HumanEval/%d" % index},
            )
            for index in range(20)
        ]
        forward = module._sample_items("humaneval", items, 5)
        reverse = module._sample_items("humaneval", list(reversed(items)), 5)

        self.assertEqual([item[0] for item in forward], [item[0] for item in reverse])
        self.assertNotEqual(
            {item[0] for item in forward},
            {item[0] for item in items[:5]},
        )
        self.assertEqual(
            module._sample_policy("humaneval", 5),
            "humaneval_sha256_rank_5_from_evalplus_revision_v1",
        )

    def test_evalplus_runner_extracts_task_failure_classes(self):
        fake_evalplus_data = types.SimpleNamespace(
            get_human_eval_plus=lambda: {},
            get_mbpp_plus=lambda: {},
            write_jsonl=lambda *args, **kwargs: None,
        )
        fake_mbpp = types.SimpleNamespace(mbpp_serialize_inputs=lambda task_id, inputs: inputs)
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
            module = _load_module("evalplus_runner_status_test_module", module_path)

        self.assertEqual(
            module._case_result_for_task(
                "HumanEval/0",
                [{"base_status": "pass", "plus_status": "pass"}],
            )["failure_class"],
            None,
        )
        passing = module._case_result_for_task(
            "HumanEval/0",
            [{"base_status": "pass", "plus_status": "pass"}],
        )
        self.assertTrue(passing["base_passed"])
        self.assertTrue(passing["plus_passed"])
        self.assertTrue(passing["passed"])
        self.assertEqual(
            module._case_result_for_task(
                "HumanEval/1",
                [{"base_status": "pass", "plus_status": "fail"}],
            )["failure_class"],
            "test_failed",
        )
        self.assertEqual(
            module._case_result_for_task(
                "HumanEval/2",
                [{"base_status": "timeout", "plus_status": "timeout"}],
            )["failure_class"],
            "timeout",
        )
        self.assertEqual(
            module._case_result_for_task("HumanEval/3", [{"base_status": "fail"}])["plus_passed"],
            False,
        )

    def test_evalplus_primary_metric_preserves_zero_plus_score(self):
        fake_evalplus_data = types.SimpleNamespace(
            get_human_eval_plus=lambda: {},
            get_mbpp_plus=lambda: {},
            write_jsonl=lambda *args, **kwargs: None,
        )
        fake_mbpp = types.SimpleNamespace(mbpp_serialize_inputs=lambda task_id, inputs: inputs)
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
            module = _load_module("evalplus_runner_metric_test_module", module_path)

        results = {"pass_at_k": {"base": {"pass@1": 1.0}, "plus": {"pass@1": 0.0}}}
        self.assertEqual(module._primary_plus_metric_value(results), 0.0)
        self.assertEqual(module._rounded_metric_or_zero(results, "base", "pass@1"), 1.0)
        self.assertEqual(module._rounded_metric_or_zero(results, "plus", "pass@1"), 0.0)

    def test_evalplus_evaluate_applies_subset_override_to_imported_dataset_module(self):
        calls = []
        fake_humaneval = types.SimpleNamespace(HUMANEVAL_OVERRIDE_PATH=None)

        def fake_write_jsonl(path, rows, drop_builtin=False):
            with open(path, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")

        def fake_evaluate(**kwargs):
            calls.append(kwargs)
            self.assertEqual(fake_humaneval.HUMANEVAL_OVERRIDE_PATH, os.path.join(kwargs["samples"].rsplit("/", 1)[0], "humaneval_override.jsonl"))
            with open(kwargs["output_file"], "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "eval": {"HumanEval/0": [{"base_status": "pass", "plus_status": "pass"}]},
                        "pass_at_k": {"base": {"pass@1": 1.0}, "plus": {"pass@1": 1.0}},
                    },
                    handle,
                )

        fake_evalplus_data = types.SimpleNamespace(
            get_human_eval_plus=lambda: {},
            get_mbpp_plus=lambda: {},
            write_jsonl=fake_write_jsonl,
        )
        fake_mbpp = types.SimpleNamespace(MBPP_OVERRIDE_PATH=None, mbpp_serialize_inputs=lambda _task_id, inputs: inputs)
        fake_evalplus_evaluate = types.SimpleNamespace(evaluate=fake_evaluate)
        fake_evalplus = types.ModuleType("evalplus")
        fake_data_package = types.ModuleType("evalplus.data")
        fake_data_package.get_human_eval_plus = fake_evalplus_data.get_human_eval_plus
        fake_data_package.get_mbpp_plus = fake_evalplus_data.get_mbpp_plus
        fake_data_package.write_jsonl = fake_write_jsonl
        module_path = os.path.join(ROOT_DIR, "containers", "capability-evalplus", "runner.py")
        with mock.patch.dict(
            sys.modules,
            {
                "evalplus": fake_evalplus,
                "evalplus.data": fake_data_package,
                "evalplus.data.humaneval": fake_humaneval,
                "evalplus.data.mbpp": fake_mbpp,
                "evalplus.evaluate": fake_evalplus_evaluate,
            },
        ):
            module = _load_module("evalplus_runner_subset_override_test_module", module_path)
            with tempfile.TemporaryDirectory() as tempdir:
                fake_write_jsonl(
                    os.path.join(tempdir, "humaneval_override.jsonl"),
                    [{"task_id": "HumanEval/0", "prompt": "def f():\n", "entry_point": "f"}],
                )
                fake_write_jsonl(
                    os.path.join(tempdir, "predictions.jsonl"),
                    [{"task_id": "HumanEval/0", "completion": "    return 1"}],
                )
                module.evaluate("humaneval", tempdir)

        self.assertEqual(len(calls), 1)

    def test_evalplus_rejects_incomplete_subset_predictions_before_scoring(self):
        with self.assertRaisesRegex(ValueError, "missing=HumanEval/1"):
            # This validation is intentionally independent of EvalPlus imports.
            fake_evalplus_data = types.SimpleNamespace(
                get_human_eval_plus=lambda: {},
                get_mbpp_plus=lambda: {},
                write_jsonl=lambda *args, **kwargs: None,
            )
            fake_mbpp = types.SimpleNamespace(mbpp_serialize_inputs=lambda _task_id, inputs: inputs)
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
                module = _load_module("evalplus_runner_coverage_test_module", module_path)
            module._validate_prediction_coverage(
                [{"task_id": "HumanEval/0"}],
                [{"task_id": "HumanEval/0"}, {"task_id": "HumanEval/1"}],
            )

    def test_evalplus_applies_mbpp_subset_override_to_imported_dataset_module(self):
        fake_mbpp = types.SimpleNamespace(MBPP_OVERRIDE_PATH=None, mbpp_serialize_inputs=lambda _task_id, inputs: inputs)
        fake_evalplus_data = types.SimpleNamespace(
            get_human_eval_plus=lambda: {},
            get_mbpp_plus=lambda: {},
            write_jsonl=lambda *args, **kwargs: None,
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
            module = _load_module("evalplus_runner_mbpp_override_test_module", module_path)
            module._configure_dataset_override("mbpp", "/work/mbpp_override.jsonl")

        self.assertEqual(fake_mbpp.MBPP_OVERRIDE_PATH, "/work/mbpp_override.jsonl")

    def test_evalplus_dockerfile_pins_upstream_revision(self):
        dockerfile_path = os.path.join(ROOT_DIR, "containers", "capability-evalplus", "Dockerfile")
        with open(dockerfile_path, "r", encoding="utf-8") as handle:
            dockerfile = handle.read()
        runner_path = os.path.join(ROOT_DIR, "containers", "capability-evalplus", "runner.py")
        with open(runner_path, "r", encoding="utf-8") as handle:
            runner = handle.read()

        self.assertIn("26d6d00bb1fd0fa37f39c99d5290da67891d1c5e", dockerfile)
        self.assertIn('EVALPLUS_REVISION = "26d6d00bb1fd0fa37f39c99d5290da67891d1c5e"', runner)

    def test_mmlu_pro_prepares_sampled_cases_and_scores_accuracy(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "runner.py")
        module = _load_module("mmlu_pro_runner_test_module", module_path)
        rows = [
            {
                "question_id": 1,
                "question": "What is 2 + 2?",
                "options": ["1", "2", "3", "4"],
                "answer": "D",
                "answer_index": 3,
                "category": "math",
                "src": "fixture",
            },
            {
                "question_id": 2,
                "question": "Which letter starts banana?",
                "options": ["A", "B", "C", "D"],
                "answer": "B",
                "answer_index": 1,
                "category": "other",
                "src": "fixture",
            },
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            data_path = os.path.join(tempdir, "mmlu_pro_fixture.jsonl")
            with open(data_path, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write("%s\n" % json.dumps(row))
            module.prepare(tempdir, limit=2, data_path=data_path)
            cases_path = os.path.join(tempdir, "cases.jsonl")
            with open(cases_path, "r", encoding="utf-8") as handle:
                cases = [json.loads(line) for line in handle if line.strip()]
            self.assertEqual([case["task_id"] for case in cases], ["mmlu_pro/1", "mmlu_pro/2"])
            self.assertIn("Final answer letter", cases[0]["prompt"])
            self.assertEqual(cases[0]["answer"], "D")

            predictions_path = os.path.join(tempdir, "predictions.jsonl")
            with open(predictions_path, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"task_id": "mmlu_pro/1", "completion": "The answer is D."}) + "\n")
                handle.write(json.dumps({"task_id": "mmlu_pro/2", "completion": "A"}) + "\n")
            module.evaluate(tempdir)
            with open(os.path.join(tempdir, "summary.json"), "r", encoding="utf-8") as handle:
                summary = json.load(handle)

        self.assertEqual(summary["benchmark_id"], "mmlu_pro_reference_v1")
        self.assertEqual(summary["primary_metric"], {"name": "accuracy", "value": 0.5})
        self.assertEqual(summary["metrics"]["correct_count"], 1)
        self.assertEqual(summary["metrics"]["total_count"], 2)
        self.assertEqual(summary["category_metrics"]["math"]["accuracy"], 1.0)
        self.assertEqual(summary["category_metrics"]["other"]["accuracy"], 0.0)

    def test_mmlu_pro_sample_is_order_independent_within_categories(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "runner.py")
        module = _load_module("mmlu_pro_sampling_test_module", module_path)
        rows = [
            {"question_id": index, "category": "cat-%d" % (index % 2)}
            for index in range(12)
        ]

        forward = module._sample_rows(rows, 6)
        reverse = module._sample_rows(list(reversed(rows)), 6)

        self.assertEqual(
            {item["question_id"] for item in forward},
            {item["question_id"] for item in reverse},
        )
        self.assertEqual({item["category"] for item in forward}, {"cat-0", "cat-1"})

    def test_mmlu_pro_scores_25_letters_with_llama_cpp_terminal_markers(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "runner.py")
        module = _load_module("mmlu_pro_terminal_marker_test_module", module_path)
        with tempfile.TemporaryDirectory() as tempdir:
            cases = []
            predictions = []
            for index in range(25):
                letter = module.LETTERS[index % len(module.LETTERS)]
                task_id = "mmlu_pro/%s" % index
                cases.append(
                    {
                        "case_id": task_id,
                        "task_id": task_id,
                        "category": "fixture",
                        "answer": letter,
                    }
                )
                predictions.append(
                    {"task_id": task_id, "completion": "%s [end of text]" % letter}
                )
            with open(os.path.join(tempdir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                for case in cases:
                    handle.write(json.dumps(case) + "\n")
            with open(os.path.join(tempdir, "predictions.jsonl"), "w", encoding="utf-8") as handle:
                for prediction in predictions:
                    handle.write(json.dumps(prediction) + "\n")

            module.evaluate(tempdir)
            with open(os.path.join(tempdir, "summary.json"), "r", encoding="utf-8") as handle:
                summary = json.load(handle)

        self.assertEqual(summary["metrics"]["total_count"], 25)
        self.assertEqual(summary["metrics"]["invalid_count"], 0)
        self.assertEqual(summary["metrics"]["correct_count"], 25)
        self.assertEqual(summary["primary_metric"], {"name": "accuracy", "value": 1.0})
        self.assertEqual(summary["scoring_policy"], "exact_multiple_choice_letter_accuracy_v4")

    def test_mmlu_pro_case_results_feed_distribution_gate_from_jsonl(self):
        from infergrade.capabilities import CAPABILITY_BENCHMARKS, _multiple_choice_output_shape_gate

        module_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "runner.py")
        module = _load_module("mmlu_pro_gate_integration_test_module", module_path)
        cases = []
        predictions = []
        for index in range(60):
            task_id = "mmlu_pro/%d" % index
            cases.append(
                {
                    "case_id": task_id,
                    "task_id": task_id,
                    "category": "fixture",
                    "answer": module.LETTERS[index % len(module.LETTERS)],
                }
            )
            predictions.append(
                {
                    "case_id": task_id,
                    "task_id": task_id,
                    "generation_status": "completed",
                    "completion": "A" if index < 50 else "B",
                }
            )

        with tempfile.TemporaryDirectory() as tempdir:
            for filename, rows in (("cases.jsonl", cases), ("predictions.jsonl", predictions)):
                with open(os.path.join(tempdir, filename), "w", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(json.dumps(row) + "\n")

            module.evaluate(tempdir)
            with open(os.path.join(tempdir, "summary.json"), "r", encoding="utf-8") as handle:
                summary = json.load(handle)
            with open(os.path.join(tempdir, "predictions.jsonl"), "r", encoding="utf-8") as handle:
                persisted_predictions = [json.loads(line) for line in handle if line.strip()]

        self.assertEqual(summary["metrics"]["total_count"], 60)
        self.assertEqual(summary["case_results"][0]["expected"], "A")
        self.assertEqual(summary["case_results"][0]["predicted"], "A")
        self.assertEqual(summary["case_results"][-1]["expected"], "J")
        self.assertEqual(summary["case_results"][-1]["predicted"], "B")

        gate = _multiple_choice_output_shape_gate(
            CAPABILITY_BENCHMARKS["mmlu_pro_reference_v1"],
            persisted_predictions,
            summary,
        )

        self.assertEqual(gate["status"], "blocked")
        self.assertIn("response_distribution_collapse", gate["reason_codes"])
        self.assertEqual(gate["valid_answer_count"], 60)
        self.assertEqual(gate["predicted_label_counts"], {"A": 50, "B": 10})

    def test_mmlu_pro_terminal_normalization_does_not_hide_extra_output(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "runner.py")
        module = _load_module("mmlu_pro_strict_terminal_marker_test_module", module_path)

        self.assertEqual(module._prediction_letter("B [end of text]"), "B")
        self.assertEqual(module._prediction_letter("<think>\n\n</think>\n\nB [end of text]"), "B")
        self.assertIsNone(module._prediction_letter("<think>reasoning</think>\nB [end of text]"))
        self.assertIsNone(module._prediction_letter("B extra output [end of text]"))
        self.assertIsNone(module._prediction_letter("[end of text] B"))
        self.assertEqual(
            module._prediction_letter("Reasoning remains visible. Final answer letter: B"),
            "B",
        )

    def test_mmlu_pro_all_malformed_completed_predictions_score_zero(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "runner.py")
        module = _load_module("mmlu_pro_all_invalid_test_module", module_path)
        with tempfile.TemporaryDirectory() as tempdir:
            with open(os.path.join(tempdir, "cases.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"case_id": "mmlu_pro/1", "task_id": "mmlu_pro/1", "category": "fixture", "answer": "B"}) + "\n")
            with open(os.path.join(tempdir, "predictions.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"task_id": "mmlu_pro/1", "completion": "not an answer"}) + "\n")
            module.evaluate(tempdir)
            with open(os.path.join(tempdir, "summary.json"), "r", encoding="utf-8") as handle:
                summary = json.load(handle)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["primary_metric"]["value"], 0.0)
        self.assertEqual(summary["metrics"]["accuracy"], 0.0)
        self.assertEqual(summary["metrics"]["malformed_output_count"], 1)

    def test_mmlu_pro_mixed_format_validity_is_completed_and_keeps_strict_denominator(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "runner.py")
        module = _load_module("mmlu_pro_partial_test_module", module_path)
        cases = [
            {"case_id": "mmlu_pro/1", "task_id": "mmlu_pro/1", "category": "fixture", "answer": "B"},
            {"case_id": "mmlu_pro/2", "task_id": "mmlu_pro/2", "category": "fixture", "answer": "C"},
        ]
        predictions = [
            {"task_id": "mmlu_pro/1", "completion": "B"},
            {"task_id": "mmlu_pro/2", "completion": "not an answer"},
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            for filename, rows in (("cases.jsonl", cases), ("predictions.jsonl", predictions)):
                with open(os.path.join(tempdir, filename), "w", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(json.dumps(row) + "\n")
            module.evaluate(tempdir)
            with open(os.path.join(tempdir, "summary.json"), "r", encoding="utf-8") as handle:
                summary = json.load(handle)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["primary_metric"]["value"], 0.5)
        self.assertEqual(summary["metrics"]["invalid_count"], 1)

    def test_mmlu_pro_generation_failure_is_excluded_from_scored_denominator(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "runner.py")
        module = _load_module("mmlu_pro_generation_failure_test_module", module_path)
        cases = [
            {"case_id": "mmlu_pro/1", "task_id": "mmlu_pro/1", "category": "fixture", "answer": "B"},
            {"case_id": "mmlu_pro/2", "task_id": "mmlu_pro/2", "category": "fixture", "answer": "C"},
        ]
        predictions = [
            {"task_id": "mmlu_pro/1", "completion": "B", "generation_status": "completed"},
            {"task_id": "mmlu_pro/2", "completion": "", "generation_status": "failed"},
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            for filename, rows in (("cases.jsonl", cases), ("predictions.jsonl", predictions)):
                with open(os.path.join(tempdir, filename), "w", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(json.dumps(row) + "\n")
            module.evaluate(tempdir)
            with open(os.path.join(tempdir, "summary.json"), "r", encoding="utf-8") as handle:
                summary = json.load(handle)
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["primary_metric"]["value"], 1.0)
        self.assertEqual(summary["metrics"]["total_count"], 1)

    def test_mmlu_pro_dockerfile_pins_official_dataset_revision(self):
        dockerfile_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "Dockerfile")
        with open(dockerfile_path, "r", encoding="utf-8") as handle:
            dockerfile = handle.read()
        build_script_path = os.path.join(ROOT_DIR, "containers", "capability-mmlu-pro", "build_snapshot.py")
        with open(build_script_path, "r", encoding="utf-8") as handle:
            build_script = handle.read()

        self.assertIn("TIGER-Lab/MMLU-Pro", build_script)
        self.assertIn("54611cde22c74cca43dd78732198de6abe971398", dockerfile)
        self.assertIn("build_snapshot.py", dockerfile)

    def test_bfcl_prepare_round_robins_categories_and_preserves_claim_boundary(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-bfcl", "runner.py")
        module = _load_module("bfcl_runner_prepare_test_module", module_path)
        rows = []
        for index in range(3):
            for category in ("multiple", "parallel", "irrelevance"):
                rows.append(
                    {
                        "id": "%s_%d" % (category, index),
                        "category": category,
                        "question": [[{"role": "user", "content": "fixture request"}]],
                        "function": [{"name": "fixture.call", "parameters": {"type": "dict", "properties": {}}}],
                        "ground_truth": None if category == "irrelevance" else [{"fixture.call": {}}],
                    }
                )
        metadata = {
            "upstream_revision": "fixture-revision",
            "upstream_version": "BFCL_v4",
            "snapshot_sha256": "fixture-sha",
        }
        with tempfile.TemporaryDirectory() as tempdir:
            data_path = os.path.join(tempdir, "snapshot.jsonl")
            metadata_path = os.path.join(tempdir, "snapshot_metadata.json")
            with open(data_path, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")
            with open(metadata_path, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle)
            with mock.patch.object(module, "DEFAULT_METADATA_PATH", metadata_path):
                module.prepare(tempdir, limit=3, data_path=data_path)
            with open(os.path.join(tempdir, "cases.jsonl"), encoding="utf-8") as handle:
                cases = [json.loads(line) for line in handle]
            with open(os.path.join(tempdir, "benchmark_metadata.json"), encoding="utf-8") as handle:
                benchmark_metadata = json.load(handle)

        self.assertEqual({case["category"] for case in cases}, {"multiple", "parallel", "irrelevance"})
        self.assertEqual(
            {
                row["id"]
                for row in module._sample_rows(rows, 3)
            },
            {
                row["id"]
                for row in module._sample_rows(list(reversed(rows)), 3)
            },
        )
        self.assertTrue(all("Return only a JSON array" in case["prompt"] for case in cases))
        self.assertIn("official BFCL V4 leaderboard score", benchmark_metadata["claim_boundary"]["cannot_claim"])
        self.assertEqual(benchmark_metadata["prompt_format"], "infergrade_json_tool_calls_v1")
        self.assertEqual(benchmark_metadata["sample_policy"], "category_round_robin_3_v2")
        self.assertEqual(len(benchmark_metadata["selection_sha256"]), 64)

    def test_bfcl_strict_scorer_handles_optional_parallel_and_relevance_cases(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-bfcl", "runner.py")
        module = _load_module("bfcl_runner_scorer_test_module", module_path)
        parallel_case = {
            "case_id": "bfcl_v4/parallel_1",
            "task_id": "bfcl_v4/parallel_1",
            "category": "parallel",
            "function": [{"name": "music.play"}],
            "ground_truth": [
                {"music.play": {"artist": ["Taylor Swift"], "duration": [20], "shuffle": ["", True]}},
                {"music.play": {"artist": ["Maroon 5"], "duration": [15], "shuffle": ["", True]}},
            ],
        }
        calls = (
            '[{"name":"music.play","arguments":{"artist":"Maroon 5","duration":15}},'
            '{"name":"music.play","arguments":{"artist":"taylor   swift","duration":20,"shuffle":true}}]'
        )
        self.assertTrue(module._score_case(parallel_case, calls)["correct"])
        self.assertFalse(module._score_case(parallel_case, calls.replace("20", "21"))["correct"])
        self.assertTrue(module._score_case(parallel_case, "```json\n%s\n```" % calls)["malformed"])
        self.assertTrue(
            module._score_case(
                {**parallel_case, "category": "irrelevance", "ground_truth": None},
                "[] [end of text]",
            )["correct"]
        )
        self.assertFalse(
            module._score_case(
                {**parallel_case, "category": "live_relevance", "ground_truth": None},
                "[]",
            )["correct"]
        )
        self.assertTrue(
            module._score_case(
                {**parallel_case, "category": "live_relevance", "ground_truth": None},
                '[{"name":"music.play","arguments":{}}]',
            )["correct"]
        )

    def test_bfcl_evaluate_reports_selection_argument_and_malformed_signals(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-bfcl", "runner.py")
        module = _load_module("bfcl_runner_evaluate_test_module", module_path)
        cases = [
            {
                "case_id": "bfcl_v4/simple_1",
                "task_id": "bfcl_v4/simple_1",
                "category": "simple_python",
                "function": [{"name": "weather.get"}],
                "ground_truth": [{"weather.get": {"city": ["Boston"]}}],
            },
            {
                "case_id": "bfcl_v4/simple_2",
                "task_id": "bfcl_v4/simple_2",
                "category": "simple_python",
                "function": [{"name": "weather.get"}],
                "ground_truth": [{"weather.get": {"city": ["Boston"]}}],
            },
            {
                "case_id": "bfcl_v4/irrelevance_1",
                "task_id": "bfcl_v4/irrelevance_1",
                "category": "irrelevance",
                "function": [{"name": "weather.get"}],
                "ground_truth": None,
            },
        ]
        predictions = [
            {"task_id": "bfcl_v4/simple_1", "completion": '[{"name":"weather.get","arguments":{"city":"Boston"}}]'},
            {"task_id": "bfcl_v4/simple_2", "completion": '[{"name":"weather.get","arguments":{"city":"Chicago"}}]'},
            {"task_id": "bfcl_v4/irrelevance_1", "completion": "not-json"},
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            for filename, rows in (("cases.jsonl", cases), ("predictions.jsonl", predictions)):
                with open(os.path.join(tempdir, filename), "w", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(json.dumps(row) + "\n")
            module.evaluate(tempdir)
            with open(os.path.join(tempdir, "summary.json"), encoding="utf-8") as handle:
                summary = json.load(handle)

        self.assertEqual(summary["primary_metric"], {"name": "accuracy", "value": 0.333333})
        self.assertEqual(summary["metrics"]["function_selection_accuracy"], 0.666667)
        self.assertEqual(summary["metrics"]["malformed_output_count"], 1)
        self.assertEqual(summary["case_results"][1]["error_type"], "argument_mismatch")
        self.assertIn("official BFCL V4 leaderboard score", summary["claim_boundary"]["cannot_claim"])

    def test_bfcl_snapshot_builder_pins_upstream_files_and_license(self):
        dockerfile_path = os.path.join(ROOT_DIR, "containers", "capability-bfcl", "Dockerfile")
        build_script_path = os.path.join(ROOT_DIR, "containers", "capability-bfcl", "build_snapshot.py")
        license_path = os.path.join(ROOT_DIR, "containers", "capability-bfcl", "LICENSE.upstream")
        with open(dockerfile_path, encoding="utf-8") as handle:
            dockerfile = handle.read()
        with open(build_script_path, encoding="utf-8") as handle:
            build_script = handle.read()
        with open(license_path, encoding="utf-8") as handle:
            license_notice = handle.read()

        revision = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
        self.assertIn(revision, dockerfile)
        self.assertIn(revision, build_script)
        self.assertIn("source_file_sha256", build_script)
        self.assertIn("c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4", build_script)
        self.assertIn("Apache License 2.0", license_notice)
        self.assertIn("not official BFCL leaderboard scores", " ".join(license_notice.split()))

        build_module = _load_module("bfcl_snapshot_builder_test_module", build_script_path)
        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.dict(os.environ, {"BFCL_UPSTREAM_REVISION": "drifted"}, clear=False):
                with self.assertRaisesRegex(ValueError, "hash-verified source manifest"):
                    build_module.build(__import__("pathlib").Path(tempdir))

    def test_gpqa_diamond_prepare_and_strict_scoring(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-gpqa", "runner.py")
        module = _load_module("gpqa_runner_test_module", module_path)
        fieldnames = [
            "Question",
            "Correct Answer",
            "Incorrect Answer 1",
            "Incorrect Answer 2",
            "Incorrect Answer 3",
            "Record ID",
            "High-level domain",
        ]
        with tempfile.TemporaryDirectory() as tempdir:
            data_path = os.path.join(tempdir, "gpqa_diamond.csv")
            with open(data_path, "w", newline="", encoding="utf-8") as handle:
                writer = __import__("csv").DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for index in range(198):
                    writer.writerow(
                        {
                            "Question": "Synthetic question %d?" % index,
                            "Correct Answer": "correct-%d" % index,
                            "Incorrect Answer 1": "wrong-a-%d" % index,
                            "Incorrect Answer 2": "wrong-b-%d" % index,
                            "Incorrect Answer 3": "wrong-c-%d" % index,
                            "Record ID": "fixture-%03d" % index,
                            "High-level domain": ("physics", "chemistry", "biology")[index % 3],
                        }
                    )
            module.prepare(tempdir, limit=3, data_path=data_path)
            with open(os.path.join(tempdir, "cases.jsonl"), encoding="utf-8") as handle:
                cases = [json.loads(line) for line in handle]
            predictions = [
                {"task_id": cases[0]["task_id"], "completion": cases[0]["answer"]},
                {"task_id": cases[1]["task_id"], "completion": "not an answer"},
                {"task_id": cases[2]["task_id"], "completion": "", "generation_status": "failed"},
            ]
            with open(os.path.join(tempdir, "predictions.jsonl"), "w", encoding="utf-8") as handle:
                for prediction in predictions:
                    handle.write(json.dumps(prediction) + "\n")
            module.evaluate(tempdir)
            with open(os.path.join(tempdir, "summary.json"), encoding="utf-8") as handle:
                summary = json.load(handle)
            full_rows = module._load_rows(data_path)
            forward_sample_ids = {
                row["Record ID"] for row in module._sample_rows(full_rows, 3)
            }
            reverse_sample_ids = {
                row["Record ID"]
                for row in module._sample_rows(list(reversed(full_rows)), 3)
            }
        self.assertEqual(len(cases), 3)
        self.assertEqual(forward_sample_ids, reverse_sample_ids)
        self.assertEqual(summary["primary_metric"]["value"], 0.5)
        self.assertEqual(summary["metrics"]["malformed_output_count"], 1)
        self.assertEqual(summary["metrics"]["total_count"], 2)

    def test_gpqa_dockerfile_pins_archive_identity_and_dataset_license(self):
        container_dir = os.path.join(ROOT_DIR, "containers", "capability-gpqa")
        with open(os.path.join(container_dir, "Dockerfile"), encoding="utf-8") as handle:
            dockerfile = handle.read()
        with open(os.path.join(container_dir, "build_snapshot.py"), encoding="utf-8") as handle:
            build_script = handle.read()
        with open(os.path.join(container_dir, "LICENSE.dataset"), encoding="utf-8") as handle:
            license_text = handle.read()
        self.assertIn("56686c06f5e19865c153de0fdb11be3890014df7", dockerfile)
        self.assertIn("461ae7329f15a3e35f8184d2dac24b990f34fdf12f366ca4062d8e6638cd08dc", dockerfile)
        self.assertIn("dataset/gpqa_diamond.csv", build_script)
        self.assertIn("Creative Commons Attribution 4.0", license_text)

    def test_longbench_v2_prepares_balanced_tiers_and_scores_slice_metrics(self):
        container_dir = os.path.join(ROOT_DIR, "containers", "capability-longbench-v2")
        runner = _load_module("longbench_v2_runner_test_module", os.path.join(container_dir, "runner.py"))
        builder = _load_module("longbench_v2_builder_test_module", os.path.join(container_dir, "build_snapshot.py"))
        grouped = {}
        for domain in builder.DOMAINS:
            for difficulty in builder.DIFFICULTIES:
                grouped[(domain, difficulty)] = [
                    {
                        "_id": "%s-%s-%d" % (domain, difficulty, index),
                        "domain": domain,
                        "sub_domain": "fixture",
                        "difficulty": difficulty,
                        "length": "short",
                        "context": "fixture context " * (20 + index),
                        "question": "Which fixture answer is correct?",
                        "choice_A": "alpha",
                        "choice_B": "beta",
                        "choice_C": "gamma",
                        "choice_D": "delta",
                        "answer": "B",
                    }
                    for index in range(2)
                ]
        grouped[("Long Structured Data Understanding", "easy")] = grouped[
            ("Long Structured Data Understanding", "easy")
        ][:1]
        rows = builder._selection_order(grouped)
        with tempfile.TemporaryDirectory() as tempdir:
            snapshot_path = os.path.join(tempdir, "snapshot.jsonl")
            with open(snapshot_path, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            selection_sha = runner._selection_digest(rows)
            with open(snapshot_path, "rb") as handle:
                snapshot_sha = __import__("hashlib").sha256(handle.read()).hexdigest()
            metadata_path = os.path.join(tempdir, "snapshot_metadata.json")
            with open(metadata_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "dataset": "fixture/LongBench-v2",
                        "dataset_revision": "fixture-revision",
                        "dataset_sha256": "fixture-source-sha",
                        "dataset_license": "Apache-2.0",
                        "selection_sha256": selection_sha,
                        "snapshot_sha256": snapshot_sha,
                    },
                    handle,
                )
            runner.EXPECTED_SELECTION_SHA256 = selection_sha
            runner.EXPECTED_SNAPSHOT_SHA256 = snapshot_sha
            for limit, expected_domains, expected_strata in ((6, 6, 6), (12, 6, 12), (23, 6, 12)):
                output_dir = os.path.join(tempdir, "tier-%d" % limit)
                os.makedirs(output_dir)
                runner.prepare(output_dir, limit=limit, data_path=snapshot_path, metadata_path=metadata_path)
                with open(os.path.join(output_dir, "cases.jsonl"), encoding="utf-8") as handle:
                    cases = [json.loads(line) for line in handle]
                self.assertEqual(len(cases), limit)
                self.assertEqual(len({case["category"] for case in cases}), expected_domains)
                self.assertEqual(
                    len({(case["category"], case["difficulty"]) for case in cases}),
                    expected_strata,
                )
            predictions = []
            for index, case in enumerate(cases[:12]):
                completion = "B" if index == 0 else ("not an answer" if index == 1 else "A")
                predictions.append({"task_id": case["task_id"], "completion": completion})
            output_dir = os.path.join(tempdir, "tier-12")
            with open(os.path.join(output_dir, "predictions.jsonl"), "w", encoding="utf-8") as handle:
                for prediction in predictions:
                    handle.write(json.dumps(prediction) + "\n")
            runner.evaluate(output_dir)
            with open(os.path.join(output_dir, "summary.json"), encoding="utf-8") as handle:
                summary = json.load(handle)
        self.assertEqual(summary["metrics"]["total_count"], 12)
        self.assertEqual(summary["metrics"]["correct_count"], 1)
        self.assertEqual(summary["metrics"]["malformed_output_count"], 1)
        self.assertEqual(set(summary["category_metrics"]), set(builder.DOMAINS))
        self.assertEqual(set(summary["difficulty_metrics"]), {"easy", "hard"})
        self.assertEqual(set(summary["length_metrics"]), {"short"})
        self.assertEqual(set(summary["context_bucket_metrics"]), {"16384"})
        self.assertIn("official LongBench v2 leaderboard score", summary["claim_boundary"]["cannot_claim"])

    def test_longbench_v2_snapshot_identity_and_license_are_pinned(self):
        container_dir = os.path.join(ROOT_DIR, "containers", "capability-longbench-v2")
        with open(os.path.join(container_dir, "Dockerfile"), encoding="utf-8") as handle:
            dockerfile = handle.read()
        with open(os.path.join(container_dir, "build_snapshot.py"), encoding="utf-8") as handle:
            build_script = handle.read()
        with open(os.path.join(container_dir, "LICENSE.dataset"), encoding="utf-8") as handle:
            license_text = handle.read()
        self.assertIn("2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9", dockerfile)
        self.assertIn("15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2", dockerfile)
        self.assertIn("1a5f48517a31dc80083700955b92d9524cba2d863448209956e2cf1b423079a3", build_script)
        self.assertIn("677ac38dc799b0bbe61816f1d0c245bb93f01dd535a71ecfde6fa619d3eb86db", build_script)
        self.assertIn("Apache-2.0", license_text)

    def test_livecodebench_selection_balances_platform_difficulty_and_month(self):
        container_dir = os.path.join(ROOT_DIR, "containers", "capability-livecodebench")
        builder = _load_module(
            "livecodebench_builder_selection_test_module",
            os.path.join(container_dir, "build_snapshot.py"),
        )
        rows = []
        for platform in builder.PLATFORMS:
            for difficulty in builder.DIFFICULTIES:
                for month in ("2025-04", "2025-03", "2025-02", "2025-01"):
                    for item_index in range(2):
                        rows.append(
                            {
                                "question_id": "%s-%s-%s-%d" % (
                                    platform,
                                    difficulty,
                                    month,
                                    item_index,
                                ),
                                "platform": platform,
                                "difficulty": difficulty,
                                "contest_date": "%s-01T00:00:00" % month,
                            }
                        )

        forward = builder._selection_order(rows)
        reverse = builder._selection_order(list(reversed(rows)))

        self.assertEqual(
            [row["question_id"] for row in forward],
            [row["question_id"] for row in reverse],
        )
        self.assertEqual(len(forward), 48)
        for block_index in range(4):
            block = forward[block_index * 6 : (block_index + 1) * 6]
            self.assertEqual(
                {(row["platform"], row["difficulty"]) for row in block},
                {
                    (platform, difficulty)
                    for platform in builder.PLATFORMS
                    for difficulty in builder.DIFFICULTIES
                },
            )
            self.assertEqual(
                {row["contest_date"][:7] for row in block},
                {("2025-04", "2025-03", "2025-02", "2025-01")[block_index]},
            )

    def test_livecodebench_private_test_decoder_rejects_pickle_globals(self):
        container_dir = os.path.join(ROOT_DIR, "containers", "capability-livecodebench")
        builder = _load_module(
            "livecodebench_builder_pickle_test_module",
            os.path.join(container_dir, "build_snapshot.py"),
        )
        pickle_module = __import__("pickle")
        encoded = __import__("base64").b64encode(
            __import__("zlib").compress(pickle_module.dumps(os.system))
        ).decode("ascii")

        with self.assertRaisesRegex(ValueError, "decoded safely"):
            builder._private_tests(encoded)

    def test_livecodebench_prepare_hides_tests_and_sandbox_scores_both_interfaces(self):
        container_dir = os.path.join(ROOT_DIR, "containers", "capability-livecodebench")
        runner = _load_module(
            "livecodebench_runner_sandbox_test_module",
            os.path.join(container_dir, "runner.py"),
        )
        rows = []
        for index in range(48):
            rows.append(
                {
                    "question_id": "fixture-%02d" % index,
                    "question_title": "Fixture %d" % index,
                    "question_content": "Double the input.",
                    "platform": "atcoder" if index % 2 == 0 else "leetcode",
                    "contest_id": "fixture",
                    "contest_date": "2025-%02d-01T00:00:00" % (1 + index % 4),
                    "difficulty": ("easy", "medium", "hard")[index % 3],
                    "starter_code": "",
                    "function_name": None,
                    "tests": [
                        {
                            "input": "3\n",
                            "output": "fixture-hidden-output",
                            "testtype": "stdin",
                        }
                    ],
                }
            )
        source_metadata = {
            "dataset": "fixture/livecodebench",
            "dataset_file": "fixture.jsonl",
            "dataset_revision": "fixture-revision",
            "dataset_sha256": "fixture-source-sha",
            "upstream_code_revision": "fixture-code-revision",
            "dataset_license_status": "blocked_pending_upstream_metadata_review",
            "snapshot_sha256": "fixture-snapshot-sha",
        }
        with tempfile.TemporaryDirectory() as tempdir:
            with mock.patch.object(
                runner, "_verified_snapshot", return_value=(rows, source_metadata)
            ):
                runner.prepare(tempdir, limit=6)
            cases_text = __import__("pathlib").Path(tempdir, "cases.jsonl").read_text(
                encoding="utf-8"
            )
            metadata_text = __import__("pathlib").Path(
                tempdir, "benchmark_metadata.json"
            ).read_text(encoding="utf-8")
        self.assertNotIn("fixture-hidden-output", cases_text)
        self.assertNotIn("fixture-hidden-output", metadata_text)
        self.assertNotIn('"tests"', cases_text)

        with mock.patch.object(runner, "_drop_and_limit_child", lambda: None):
            stdin_result = runner._run_test(
                "print(int(input()) * 2)\n",
                {"function_name": None},
                {"input": "3\n", "output": "6", "testtype": "stdin"},
                2.0,
            )
            functional_result = runner._run_test(
                "class Solution:\n    def add(self, values: List[int]):\n        return sum(values)\n",
                {"function_name": "add"},
                {"input": "[2, 3]", "output": "5", "testtype": "functional"},
                2.0,
            )
        self.assertEqual(stdin_result, {"status": "ok", "result": "6\n"})
        self.assertEqual(functional_result, {"status": "ok", "result": 5})

    def test_livecodebench_source_identity_is_pinned_but_release_wiring_is_blocked(self):
        container_dir = os.path.join(ROOT_DIR, "containers", "capability-livecodebench")
        dockerfile = __import__("pathlib").Path(container_dir, "Dockerfile").read_text(
            encoding="utf-8"
        )
        build_script = __import__("pathlib").Path(
            container_dir, "build_snapshot.py"
        ).read_text(encoding="utf-8")
        notice = __import__("pathlib").Path(
            container_dir, "SOURCE-NOTICE.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("0fe84c3912ea0c4d4a78037083943e8f0c4dd505", dockerfile)
        self.assertIn("bb4c364f71921c4495a6ad15abe1a927350b720009f4933e2e71f8af0f6fd1f5", dockerfile)
        self.assertIn("caafbae85c53215efdeb6299e22a6fb46aca158d94b124fbf73212b312cd0f5c", build_script)
        self.assertIn("ff6f7d15528d110e1bb6846336dcc312feba11395202672eddb3df7c7bbc69e0", build_script)
        self.assertIn("must not be published", notice)
        for relative_path in (
            ".github/workflows/publish-containers.yml",
            "scripts/build_release_images.sh",
            "scripts/export_release_images.sh",
            "scripts/verify_release_images.py",
        ):
            text = __import__("pathlib").Path(ROOT_DIR, relative_path).read_text(
                encoding="utf-8"
            )
            self.assertNotIn("infergrade-livecodebench", text)

    def test_livecodebench_timeout_cleanup_fails_explicitly_without_kill_capability(self):
        module_path = os.path.join(
            ROOT_DIR, "containers", "capability-livecodebench", "runner.py"
        )
        runner = _load_module(
            "livecodebench_runner_kill_capability_test_module", module_path
        )
        process = types.SimpleNamespace(pid=1234)
        with mock.patch.object(runner.os, "killpg", side_effect=PermissionError()):
            with self.assertRaisesRegex(RuntimeError, "CAP_KILL"):
                runner._kill_process_group(process)

    def test_repository_edit_prepare_hides_tests_and_scores_a_valid_patch(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-repo-edit", "runner.py")
        module = _load_module("repository_edit_runner_test_module", module_path)
        module.FIXTURE_PATH = __import__("pathlib").Path(
            ROOT_DIR, "containers", "capability-repo-edit", "fixtures.json"
        )
        with tempfile.TemporaryDirectory() as tempdir:
            module.prepare(tempdir, limit=2)
            with open(os.path.join(tempdir, "cases.jsonl"), encoding="utf-8") as handle:
                cases = [json.loads(line) for line in handle]
        self.assertEqual(len(cases), 2)
        self.assertNotIn("tests", cases[0])
        self.assertIn("Return only one unified diff", cases[0]["prompt"])

        fixture = {
            "task_id": "simple",
            "category": "repair",
            "issue": "Return 2.",
            "editable_files": ["answer.py"],
            "files": {"answer.py": "def answer():\n    return 1\n"},
            "tests": {
                "tests/test_answer.py": (
                    "import unittest\nfrom answer import answer\n\n"
                    "class AnswerTests(unittest.TestCase):\n"
                    "    def test_answer(self):\n        self.assertEqual(answer(), 2)\n"
                )
            },
        }
        patch = "--- a/answer.py\n+++ b/answer.py\n@@ -1,2 +1,2 @@\n def answer():\n-    return 1\n+    return 2\n"
        with mock.patch.object(module, "_drop_to_unprivileged_user", lambda: None):
            scored = module._score_patch(fixture, patch)
        self.assertTrue(scored["passed"])
        self.assertIsNone(scored["failure_class"])

    def test_repository_edit_fixture_loader_rejects_revision_and_path_drift(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-repo-edit", "runner.py")
        module = _load_module("repository_edit_runner_fixture_test_module", module_path)
        base = {
            "fixture_revision": module.FIXTURE_REVISION,
            "fixtures": [
                {
                    "task_id": "safe",
                    "category": "repair",
                    "issue": "Fix it.",
                    "editable_files": ["answer.py"],
                    "files": {"answer.py": "VALUE = 1\n"},
                    "tests": {"tests/test_answer.py": "import unittest\n"},
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tempdir:
            fixture_path = __import__("pathlib").Path(tempdir, "fixtures.json")
            fixture_path.write_text(json.dumps({**base, "fixture_revision": "drifted"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "revision"):
                module._load_fixtures(fixture_path)
            unsafe = json.loads(json.dumps(base))
            unsafe["fixtures"][0]["tests"] = {"../test_answer.py": "import unittest\n"}
            fixture_path.write_text(json.dumps(unsafe), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "safe relative POSIX"):
                module._load_fixtures(fixture_path)

    def test_repository_edit_rejects_paths_outside_the_editable_fixture(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-repo-edit", "runner.py")
        module = _load_module("repository_edit_runner_path_test_module", module_path)
        unsafe = "--- a/../tests/test_hidden.py\n+++ b/../tests/test_hidden.py\n@@ -1 +1 @@\n-x\n+y\n"
        self.assertEqual(module._validate_patch_paths(unsafe, ["answer.py"]), "unsafe_patch_path")
        other = "--- a/other.py\n+++ b/other.py\n@@ -1 +1 @@\n-x\n+y\n"
        self.assertEqual(module._validate_patch_paths(other, ["answer.py"]), "non_editable_path")

    def test_repository_edit_does_not_accept_an_early_zero_exit_as_passing_tests(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-repo-edit", "runner.py")
        module = _load_module("repository_edit_runner_receipt_test_module", module_path)
        fixture = {
            "task_id": "early_exit",
            "category": "repair",
            "issue": "Return 2.",
            "editable_files": ["answer.py"],
            "files": {"answer.py": "def answer():\n    return 1\n"},
            "tests": {
                "tests/test_answer.py": (
                    "import unittest\nfrom answer import answer\n\n"
                    "class AnswerTests(unittest.TestCase):\n"
                    "    def test_answer(self):\n        self.assertEqual(answer(), 2)\n"
                )
            },
        }
        patch = (
            "--- a/answer.py\n+++ b/answer.py\n@@ -1,2 +1,4 @@\n"
            "+import os\n+\n def answer():\n-    return 1\n+    os._exit(0)\n"
        )
        with mock.patch.object(module, "_drop_to_unprivileged_user", lambda: None):
            scored = module._score_patch(fixture, patch)
        self.assertFalse(scored["passed"])
        self.assertEqual(scored["failure_class"], "test_protocol_failed")

    def test_repository_edit_evaluate_separates_malformed_patch_from_test_failure(self):
        module_path = os.path.join(ROOT_DIR, "containers", "capability-repo-edit", "runner.py")
        module = _load_module("repository_edit_runner_evaluate_test_module", module_path)
        module.FIXTURE_PATH = __import__("pathlib").Path(
            ROOT_DIR, "containers", "capability-repo-edit", "fixtures.json"
        )
        with tempfile.TemporaryDirectory() as tempdir:
            module.prepare(tempdir, limit=2)
            with open(os.path.join(tempdir, "cases.jsonl"), encoding="utf-8") as handle:
                cases = [json.loads(line) for line in handle]
            with open(os.path.join(tempdir, "predictions.jsonl"), "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"task_id": cases[0]["task_id"], "completion": "not a patch"}) + "\n")
                handle.write(
                    json.dumps(
                        {
                            "task_id": cases[1]["task_id"],
                            "completion": "--- a/config.py\n+++ b/config.py\n@@ -99 +99 @@\n-never present\n+still absent\n",
                        }
                    )
                    + "\n"
                )
            with mock.patch.object(module, "_drop_to_unprivileged_user", lambda: None):
                module.evaluate(tempdir)
            with open(os.path.join(tempdir, "summary.json"), encoding="utf-8") as handle:
                summary = json.load(handle)
        self.assertEqual(summary["metrics"]["malformed_patch_count"], 1)
        self.assertEqual(summary["metrics"]["patch_apply_failure_count"], 1)
        self.assertEqual(summary["primary_metric"]["value"], 0.0)
        self.assertTrue(all("failure_detail" not in item for item in summary["case_results"]))


if __name__ == "__main__":
    unittest.main()
