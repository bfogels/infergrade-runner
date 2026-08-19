"""Pinned synthetic constraint-reasoning stress fixtures."""

from itertools import permutations
from typing import Any, Dict, List, Sequence, Tuple


FIXTURE_REVISION = "2026-08-reasoning-constraint-stress-v1"
SCORING_POLICY = "deterministic_exact_answer_category_metrics_v1"
CATEGORY_ORDER = (
    "state_tracking",
    "graph_planning",
    "modular_reasoning",
    "set_reasoning",
    "dependency_planning",
    "arrangement_counting",
)
STRUCTURAL_TIER_BY_ROUND = (
    "foundation",
    "intermediate",
    "hard",
    "stress",
    "hard",
    "stress",
    "stress",
    "stress",
)


_STATE_DEFINITIONS = (
    (8, 5, (("add_x", 7), ("move_xy", 4), ("mul_y", 2), ("sub_x", 3))),
    (11, 4, (("mul_x", 2), ("add_y", 9), ("move_yx", 5), ("sub_y", 3))),
    (6, 13, (("swap", 0), ("move_xy", 5), ("mul_x", 3), ("add_y", 7))),
    (17, 9, (("sub_x", 4), ("move_xy", 6), ("mul_y", 2), ("move_yx", 3), ("add_x", 5))),
    (23, 7, (("move_xy", 8), ("mul_x", 2), ("add_y", 6), ("swap", 0), ("sub_y", 5))),
    (14, 19, (("move_yx", 7), ("mul_y", 3), ("sub_x", 6), ("move_xy", 9), ("add_x", 11))),
    (31, 12, (("sub_x", 9), ("mul_y", 2), ("move_yx", 8), ("swap", 0), ("move_xy", 7), ("add_y", 4))),
    (18, 27, (("mul_x", 2), ("move_xy", 11), ("sub_y", 5), ("swap", 0), ("move_yx", 6), ("mul_y", 2))),
)


_GRAPH_DEFINITIONS = (
    (("A", "B", 4), ("A", "C", 9), ("B", "C", 2), ("B", "D", 7), ("C", "D", 3)),
    (("A", "B", 8), ("A", "C", 5), ("B", "D", 4), ("C", "D", 9), ("C", "E", 3), ("E", "D", 2)),
    (("A", "B", 6), ("A", "C", 2), ("B", "D", 5), ("C", "D", 8), ("C", "E", 4), ("E", "F", 3), ("F", "D", 1)),
    (("A", "B", 3), ("A", "C", 10), ("B", "C", 4), ("B", "E", 9), ("C", "D", 2), ("D", "E", 2), ("E", "F", 5), ("D", "F", 9)),
    (("A", "B", 7), ("A", "C", 4), ("B", "D", 2), ("C", "D", 6), ("C", "E", 5), ("D", "F", 8), ("E", "F", 2), ("B", "E", 10)),
    (("A", "B", 5), ("A", "C", 11), ("B", "D", 6), ("B", "E", 3), ("C", "E", 2), ("D", "F", 4), ("E", "F", 7), ("E", "G", 5), ("G", "F", 1)),
    (("A", "B", 9), ("A", "C", 3), ("B", "D", 4), ("C", "D", 7), ("C", "E", 6), ("D", "F", 5), ("E", "F", 2), ("E", "G", 4), ("G", "H", 3), ("H", "F", 1)),
    (("A", "B", 4), ("A", "C", 12), ("B", "D", 7), ("B", "E", 5), ("C", "E", 1), ("D", "F", 3), ("E", "F", 9), ("E", "G", 4), ("G", "H", 2), ("H", "F", 2), ("D", "G", 8)),
)


_MODULAR_DEFINITIONS = (
    (5, 3, 2, 17, 8),
    (7, 5, 4, 23, 10),
    (11, 4, 7, 29, 12),
    (9, 8, 5, 31, 14),
    (13, 6, 11, 37, 16),
    (17, 9, 8, 41, 18),
    (19, 11, 13, 47, 21),
    (23, 14, 17, 53, 24),
)


_SET_DEFINITIONS = (
    (100, 45, 38, 30, 18, 12, 10, 5, "exactly_one"),
    (120, 60, 50, 40, 25, 20, 15, 8, "neither"),
    (80, 35, 32, 28, 14, 12, 10, 4, "exactly_one"),
    (150, 70, 65, 55, 30, 25, 20, 10, "neither"),
    (200, 90, 85, 75, 40, 35, 30, 15, "exactly_one"),
    (96, 48, 44, 36, 22, 16, 14, 7, "neither"),
    (180, 88, 77, 69, 36, 31, 27, 12, "exactly_one"),
    (240, 120, 105, 96, 52, 45, 39, 20, "neither"),
)


_DEPENDENCY_DEFINITIONS = (
    {"A": (3, ()), "B": (4, ("A",)), "C": (2, ("A",)), "D": (5, ("B", "C"))},
    {"A": (2, ()), "B": (6, ()), "C": (4, ("A",)), "D": (3, ("A", "B")), "E": (5, ("C", "D"))},
    {"A": (5, ()), "B": (3, ("A",)), "C": (7, ("A",)), "D": (4, ("B",)), "E": (2, ("B", "C")), "F": (6, ("D", "E"))},
    {"A": (4, ()), "B": (8, ()), "C": (3, ("A",)), "D": (6, ("A",)), "E": (5, ("B", "C")), "F": (2, ("D",)), "G": (7, ("E", "F"))},
    {"A": (6, ()), "B": (4, ("A",)), "C": (5, ("A",)), "D": (3, ("B",)), "E": (8, ("B", "C")), "F": (2, ("C",)), "G": (5, ("D", "E", "F"))},
    {"A": (3, ()), "B": (7, ()), "C": (4, ("A",)), "D": (5, ("A", "B")), "E": (6, ("C",)), "F": (2, ("C", "D")), "G": (8, ("E", "F")), "H": (3, ("D", "G"))},
    {"A": (8, ()), "B": (3, ("A",)), "C": (6, ("A",)), "D": (4, ("B",)), "E": (7, ("B", "C")), "F": (5, ("C",)), "G": (2, ("D", "E")), "H": (6, ("E", "F", "G"))},
    {"A": (5, ()), "B": (9, ()), "C": (4, ("A",)), "D": (7, ("A", "B")), "E": (3, ("B",)), "F": (6, ("C", "D")), "G": (8, ("D", "E")), "H": (2, ("F",)), "I": (5, ("F", "G", "H"))},
)


_ARRANGEMENT_DEFINITIONS = (
    ("ABCDE", (("before", "A", "B"), ("before", "C", "D"))),
    ("ABCDE", (("before", "A", "B"), ("before", "B", "C"), ("not_adjacent", "D", "E"))),
    ("ABCDEF", (("adjacent", "A", "B"), ("before", "C", "D"), ("before", "E", "F"))),
    ("ABCDEF", (("fixed", "A", 2), ("before", "B", "C"), ("not_adjacent", "D", "E"))),
    ("ABCDEFG", (("before", "A", "D"), ("before", "B", "D"), ("adjacent", "E", "F"), ("not_adjacent", "A", "C"))),
    ("ABCDEFG", (("fixed", "G", 4), ("before", "A", "B"), ("before", "B", "C"), ("not_adjacent", "D", "E"), ("before", "F", "D"))),
    ("ABCDEFGH", (("adjacent", "A", "B"), ("adjacent", "C", "D"), ("before", "E", "F"), ("not_adjacent", "G", "H"), ("before", "A", "E"))),
    ("ABCDEFGH", (("fixed", "H", 5), ("before", "A", "C"), ("before", "B", "C"), ("adjacent", "D", "E"), ("not_adjacent", "F", "G"), ("before", "C", "F"))),
)


def _state_case(index: int) -> Tuple[str, int]:
    x, y, operations = _STATE_DEFINITIONS[index]
    descriptions = []
    for operation, amount in operations:
        if operation == "add_x":
            x += amount
            descriptions.append("add %d to x" % amount)
        elif operation == "add_y":
            y += amount
            descriptions.append("add %d to y" % amount)
        elif operation == "sub_x":
            x -= amount
            descriptions.append("subtract %d from x" % amount)
        elif operation == "sub_y":
            y -= amount
            descriptions.append("subtract %d from y" % amount)
        elif operation == "move_xy":
            x -= amount
            y += amount
            descriptions.append("move %d from x to y" % amount)
        elif operation == "move_yx":
            y -= amount
            x += amount
            descriptions.append("move %d from y to x" % amount)
        elif operation == "mul_x":
            x *= amount
            descriptions.append("multiply x by %d" % amount)
        elif operation == "mul_y":
            y *= amount
            descriptions.append("multiply y by %d" % amount)
        elif operation == "swap":
            x, y = y, x
            descriptions.append("swap x and y")
        else:
            raise ValueError("Unknown state operation: %s" % operation)
    initial_x, initial_y, _ = _STATE_DEFINITIONS[index]
    prompt = (
        "Answer only the integer. Start with x=%d and y=%d. In order: %s. What is x+y at the end?"
        % (initial_x, initial_y, "; then ".join(descriptions))
    )
    return prompt, x + y


def _shortest_path_case(index: int) -> Tuple[str, int]:
    edges = _GRAPH_DEFINITIONS[index]
    nodes = sorted({node for left, right, _ in edges for node in (left, right)})
    start, target = nodes[0], nodes[-1]
    distances = {node: float("inf") for node in nodes}
    distances[start] = 0
    unvisited = set(nodes)
    while unvisited:
        current = min(unvisited, key=lambda node: distances[node])
        unvisited.remove(current)
        for left, right, weight in edges:
            if current not in {left, right}:
                continue
            neighbor = right if current == left else left
            distances[neighbor] = min(distances[neighbor], distances[current] + weight)
    edge_text = ", ".join("%s-%s:%d" % edge for edge in edges)
    prompt = (
        "Answer only the integer. An undirected weighted graph has edges %s. What is the minimum total cost from %s to %s?"
        % (edge_text, start, target)
    )
    return prompt, int(distances[target])


def _modular_case(index: int) -> Tuple[str, int]:
    start, multiplier, increment, modulus, steps = _MODULAR_DEFINITIONS[index]
    value = start
    for _ in range(steps):
        value = (multiplier * value + increment) % modulus
    prompt = (
        "Answer only the integer. Let x0=%d and x(n+1)=(%d*x(n)+%d) mod %d. What is x%d?"
        % (start, multiplier, increment, modulus, steps)
    )
    return prompt, value


def _set_case(index: int) -> Tuple[str, int]:
    universe, a, b, c, ab, ac, bc, abc, query = _SET_DEFINITIONS[index]
    union = a + b + c - ab - ac - bc + abc
    exactly_one = a + b + c - 2 * (ab + ac + bc) + 3 * abc
    answer = exactly_one if query == "exactly_one" else universe - union
    question = "exactly one of A, B, and C" if query == "exactly_one" else "none of A, B, and C"
    prompt = (
        "Answer only the integer. In a universe of %d items, |A|=%d, |B|=%d, |C|=%d, "
        "|A∩B|=%d, |A∩C|=%d, |B∩C|=%d, and |A∩B∩C|=%d. How many items are in %s?"
        % (universe, a, b, c, ab, ac, bc, abc, question)
    )
    return prompt, answer


def _dependency_case(index: int) -> Tuple[str, int]:
    tasks = _DEPENDENCY_DEFINITIONS[index]
    memo: Dict[str, int] = {}

    def finish(task_name: str) -> int:
        if task_name not in memo:
            duration, dependencies = tasks[task_name]
            memo[task_name] = duration + max([finish(item) for item in dependencies] or [0])
        return memo[task_name]

    answer = max(finish(name) for name in tasks)
    task_text = "; ".join(
        "%s takes %d and depends on %s"
        % (name, duration, ",".join(dependencies) if dependencies else "nothing")
        for name, (duration, dependencies) in tasks.items()
    )
    prompt = (
        "Answer only the integer. Tasks may run in parallel once all dependencies finish. %s. "
        "What is the earliest project completion time?" % task_text
    )
    return prompt, answer


def _arrangement_case(index: int) -> Tuple[str, int]:
    item_text, constraints = _ARRANGEMENT_DEFINITIONS[index]
    items = tuple(item_text)

    def valid(order: Sequence[str]) -> bool:
        positions = {item: position + 1 for position, item in enumerate(order)}
        for constraint in constraints:
            kind = constraint[0]
            if kind == "before" and not positions[constraint[1]] < positions[constraint[2]]:
                return False
            if kind == "adjacent" and abs(positions[constraint[1]] - positions[constraint[2]]) != 1:
                return False
            if kind == "not_adjacent" and abs(positions[constraint[1]] - positions[constraint[2]]) == 1:
                return False
            if kind == "fixed" and positions[constraint[1]] != constraint[2]:
                return False
        return True

    answer = sum(1 for order in permutations(items) if valid(order))
    descriptions = []
    for constraint in constraints:
        if constraint[0] == "before":
            descriptions.append("%s is before %s" % (constraint[1], constraint[2]))
        elif constraint[0] == "adjacent":
            descriptions.append("%s is adjacent to %s" % (constraint[1], constraint[2]))
        elif constraint[0] == "not_adjacent":
            descriptions.append("%s is not adjacent to %s" % (constraint[1], constraint[2]))
        elif constraint[0] == "fixed":
            descriptions.append("%s is in position %d" % (constraint[1], constraint[2]))
    prompt = (
        "Answer only the integer. Arrange %s in a line, using each exactly once. Constraints: %s. "
        "How many valid arrangements are there?"
        % (", ".join(items), "; ".join(descriptions))
    )
    return prompt, answer


_BUILDERS = (
    ("state_tracking", _state_case),
    ("graph_planning", _shortest_path_case),
    ("modular_reasoning", _modular_case),
    ("set_reasoning", _set_case),
    ("dependency_planning", _dependency_case),
    ("arrangement_counting", _arrangement_case),
)


def reasoning_constraint_stress_cases() -> List[Dict[str, Any]]:
    """Return 48 interleaved cases so every tier spans every category."""
    cases = []
    for round_index in range(8):
        for category, builder in _BUILDERS:
            prompt, answer = builder(round_index)
            case_number = round_index + 1
            cases.append(
                {
                    "case_id": "reasoning-stress-%s-%02d" % (category.replace("_", "-"), case_number),
                    "task_id": "reasoning_constraint_stress_v1/%s-%02d" % (category.replace("_", "-"), case_number),
                    "category": category,
                    # Structural tier describes fixture complexity only. It is
                    # not an empirical model-difficulty claim.
                    "structural_tier": STRUCTURAL_TIER_BY_ROUND[round_index],
                    "prompt": prompt,
                    "expected_answers": [str(answer)],
                }
            )
    return cases
