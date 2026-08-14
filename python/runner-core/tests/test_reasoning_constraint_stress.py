import hashlib
import json
import sys
import unittest
from collections import Counter, defaultdict

sys.path.insert(0, "python/runner-core/src")

from infergrade.reasoning_constraint_stress import (
    CATEGORY_ORDER,
    FIXTURE_REVISION,
    reasoning_constraint_stress_cases,
)


class ReasoningConstraintStressFixtureTests(unittest.TestCase):
    def test_fixture_is_pinned_balanced_and_tier_prefixes_span_categories(self):
        cases = reasoning_constraint_stress_cases()

        self.assertEqual(FIXTURE_REVISION, "2026-08-reasoning-constraint-stress-v1")
        self.assertEqual(len(cases), 48)
        self.assertEqual(len({case["case_id"] for case in cases}), 48)
        self.assertEqual(len({case["task_id"] for case in cases}), 48)
        self.assertEqual(Counter(case["category"] for case in cases), {item: 8 for item in CATEGORY_ORDER})
        self.assertEqual(
            Counter(case["structural_tier"] for case in cases),
            {"foundation": 6, "intermediate": 6, "hard": 12, "stress": 24},
        )
        self.assertEqual([case["category"] for case in cases[:6]], list(CATEGORY_ORDER))
        self.assertEqual(
            Counter(case["category"] for case in cases[:24]),
            {item: 4 for item in CATEGORY_ORDER},
        )
        self.assertEqual(
            hashlib.sha256(
                json.dumps(cases, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "57de9422faaf62b22c2e21427f63553b0267928cd4e5b0a69165744be90a1cec",
        )

    def test_expected_answers_are_pinned_independently_by_category(self):
        answers = defaultdict(list)
        for case in reasoning_constraint_stress_cases():
            self.assertEqual(len(case["expected_answers"]), 1)
            self.assertRegex(case["expected_answers"][0], r"^-?\d+$")
            answers[case["category"]].append(case["expected_answers"][0])

        self.assertEqual(answers["state_tracking"], ["26", "32", "42", "42", "46", "62", "50", "77"])
        self.assertEqual(answers["graph_planning"], ["9", "8", "9", "16", "11", "13", "12", "15"])
        self.assertEqual(answers["modular_reasoning"], ["10", "2", "13", "16", "13", "22", "7", "42"])
        self.assertEqual(answers["set_reasoning"], ["48", "22", "35", "25", "85", "13", "82", "35"])
        self.assertEqual(answers["dependency_planning"], ["12", "14", "20", "20", "24", "25", "29", "29"])
        self.assertEqual(answers["arrangement_counting"], ["30", "12", "60", "42", "320", "44", "320", "76"])


if __name__ == "__main__":
    unittest.main()
