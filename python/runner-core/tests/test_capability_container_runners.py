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
        self.assertEqual(len(cases), 3)
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


if __name__ == "__main__":
    unittest.main()
