"""Read-only, generated content identity for the reasoning v2 successor.

The content pack is intentionally not a benchmark adapter.  It materializes a
stable set of prompts and expected terminal integers so that a later protocol
review can inspect coverage, oracle correctness, and selection identity before
any model or runtime is allowed to consume it.

The generator uses domain-separated SHA-256 bytes rather than a process-global
PRNG.  This keeps every case reproducible across Python versions and makes the
generator, seed, complete fixture, and tier prefixes independently auditable.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from copy import deepcopy
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from infergrade.reasoning_constraint_stress_v2 import (
    FINAL_ANSWER_MARKER,
    FINAL_ANSWER_PARSER_ID,
    MAX_INTEGER_DIGITS,
    SCORING_POLICY,
    parse_final_answer,
)
from infergrade.selection_identity import (
    SORTED_JSON_STRING_ARRAY_SHA256_V1,
    selection_digest,
)


BENCHMARK_ID = "reasoning_constraint_stress_v2_content_v1"
FIXTURE_REVISION = "2026-08-reasoning-constraint-stress-v2-content-v1"
GENERATOR_ID = "sha256_domain_separated_case_generator_v1"
GENERATOR_REVISION = "reasoning_constraint_stress_v2_content_generator_v2"
GENERATOR_ALGORITHM = "sha256_counter_u32_v1"
GENERATOR_SEED = (
    "infergrade/reasoning-constraint-stress-v2-content/"
    "2026-08-19-leakage-safe-v48"
)
GENERATOR_SEED_SHA256 = hashlib.sha256(GENERATOR_SEED.encode("utf-8")).hexdigest()
SELECTION_DIGEST_ALGORITHM = SORTED_JSON_STRING_ARRAY_SHA256_V1
parse_content_answer = parse_final_answer

FAMILY_ORDER = (
    "state_reconciliation",
    "shortest_route_cost",
    "dag_critical_path",
    "set_cardinality",
    "constrained_arrangement_count",
)
STRUCTURAL_LEVEL_ORDER = ("foundation", "intermediate", "hard", "stress")
VARIANT_ORDER = ("alpha", "beta")
TIER_PREFIX_COUNTS = {"canary": 5, "standard": 20, "gold": 40}

# These are deliberately separate from the computed values below.  A future
# generator edit must update a reviewable identity lock rather than silently
# changing the catalog identity at import time.
LOCKED_GENERATOR_SEED_SHA256 = "c95c18927496271777648a50697a6e70282c7546cde1fbb631f2cf9e338d808c"
LOCKED_FIXTURE_SHA256 = "f75fb65fd199e28491b8ee463f90bac2b9127955ea258a981ddc7c1814bb471c"
LOCKED_FULL_SELECTION_SHA256 = "b6e0b39132c16c0b19c17bc79daa7626226ea200fc8e575b890edf4d69deae60"
LOCKED_TIER_SELECTION_DIGESTS = {
    "canary": "8bc58abb5d89aed795af1c84c9ee55784a269fee299ee998c8a8524a5452599a",
    "standard": "aad415f333b13f309511208e291bf87b0f84906aa7964bec3a239b851d0cc7ae",
    "gold": "b6e0b39132c16c0b19c17bc79daa7626226ea200fc8e575b890edf4d69deae60",
}
LOCKED_TIER_COVERAGE = {
    "canary": {
        "case_count": 5,
        "family_counts": {
            "state_reconciliation": 1,
            "shortest_route_cost": 1,
            "dag_critical_path": 1,
            "set_cardinality": 1,
            "constrained_arrangement_count": 1,
        },
        "structural_level_counts": {"foundation": 5},
        "variant_counts": {"alpha": 5},
    },
    "standard": {
        "case_count": 20,
        "family_counts": {
            "state_reconciliation": 4,
            "shortest_route_cost": 4,
            "dag_critical_path": 4,
            "set_cardinality": 4,
            "constrained_arrangement_count": 4,
        },
        "structural_level_counts": {
            "foundation": 5,
            "intermediate": 5,
            "hard": 5,
            "stress": 5,
        },
        "variant_counts": {"alpha": 10, "beta": 10},
    },
    "gold": {
        "case_count": 40,
        "family_counts": {
            "state_reconciliation": 8,
            "shortest_route_cost": 8,
            "dag_critical_path": 8,
            "set_cardinality": 8,
            "constrained_arrangement_count": 8,
        },
        "structural_level_counts": {
            "foundation": 10,
            "intermediate": 10,
            "hard": 10,
            "stress": 10,
        },
        "variant_counts": {"alpha": 20, "beta": 20},
    },
}


def _digest_bytes(*parts: object) -> bytes:
    payload = "|".join(str(part) for part in (GENERATOR_SEED,) + parts).encode("utf-8")
    return hashlib.sha256(payload).digest()


def _u32(*parts: object, counter: int = 0) -> int:
    digest = _digest_bytes(*parts, counter)
    return int.from_bytes(digest[:4], "big")


def _bounded(*parts: object, low: int, high: int, counter: int = 0) -> int:
    if low > high:
        raise ValueError("invalid generator range")
    return low + (_u32(*parts, counter=counter) % (high - low + 1))


def _case_key(family: str, level_index: int, variant_index: int) -> str:
    return "%s/%s/%s" % (
        family,
        STRUCTURAL_LEVEL_ORDER[level_index],
        VARIANT_ORDER[variant_index],
    )


def _state_apply(
    x: int,
    y: int,
    z: int,
    operations: Sequence[Tuple[Any, ...]],
) -> Tuple[int, int, int]:
    for operation in operations:
        kind = operation[0]
        if kind == "assign_x_sum":
            x = y + z + int(operation[1])
        elif kind == "assign_y_mix":
            y = int(operation[1]) * x - z + int(operation[2])
        elif kind == "assign_z_product_mod":
            z = (x * y + int(operation[2])) % int(operation[1])
        elif kind == "rotate_left":
            x, y, z = y, z, x
        elif kind == "x_add_scaled_y":
            x = x + int(operation[1]) * y
        elif kind == "y_add_scaled_z":
            y = y + int(operation[1]) * z
        elif kind == "z_subtract_scaled_x":
            z = z - int(operation[1]) * x
        else:
            raise ValueError("unknown state operation")
    return x, y, z


def _state_target(state: Tuple[int, int, int]) -> int:
    x, y, z = state
    return 3 * x - 2 * y + z


def _state_spec(level_index: int, variant_index: int) -> Dict[str, Any]:
    x = _bounded("state", level_index, variant_index, "x", low=-18, high=24)
    y = _bounded("state", level_index, variant_index, "y", low=-16, high=26)
    z = _bounded("state", level_index, variant_index, "z", low=-12, high=20)
    operation_count = 4 + 2 * level_index
    operation_kinds = (
        "assign_x_sum",
        "assign_z_product_mod",
        "assign_y_mix",
        "rotate_left",
        "x_add_scaled_y",
        "y_add_scaled_z",
        "z_subtract_scaled_x",
    )
    operations: List[Tuple[Any, ...]] = []
    for operation_index in range(operation_count):
        kind = operation_kinds[operation_index % len(operation_kinds)]
        offset = _bounded(
            "state", level_index, variant_index, kind, operation_index, "offset", low=-9, high=11
        )
        coefficient = _bounded(
            "state", level_index, variant_index, kind, operation_index, "coefficient", low=1, high=3
        )
        if kind == "assign_x_sum":
            operations.append((kind, offset))
        elif kind == "assign_y_mix":
            operations.append((kind, coefficient, offset))
        elif kind == "assign_z_product_mod":
            modulus = _bounded(
                "state", level_index, variant_index, kind, operation_index, "modulus", low=17, high=43
            )
            operations.append((kind, modulus, offset))
        elif kind == "rotate_left":
            operations.append((kind,))
        else:
            operations.append((kind, coefficient))
    spec = {"x": x, "y": y, "z": z, "operations": tuple(operations)}
    forward = _state_target(_state_apply(x, y, z, spec["operations"]))
    reverse = _state_target(_state_apply(x, y, z, tuple(reversed(spec["operations"]))))
    collapsed = x + y
    if forward == reverse or forward == collapsed:
        repair = (
            "assign_y_mix",
            2 + variant_index,
            13 + level_index,
        )
        spec["operations"] = spec["operations"] + (repair,)
    return spec


def _state_answer(spec: Mapping[str, Any]) -> int:
    return _state_target(
        _state_apply(
            int(spec["x"]),
            int(spec["y"]),
            int(spec["z"]),
            spec["operations"],
        )
    )


def _state_independent_answer(spec: Mapping[str, Any]) -> int:
    # This implementation intentionally does not call _state_apply.
    values = {"x": int(spec["x"]), "y": int(spec["y"]), "z": int(spec["z"])}
    for operation in spec["operations"]:
        kind = operation[0]
        if kind == "assign_x_sum":
            values["x"] = values["y"] + values["z"] + int(operation[1])
        elif kind == "assign_y_mix":
            values["y"] = int(operation[1]) * values["x"] - values["z"] + int(operation[2])
        elif kind == "assign_z_product_mod":
            values["z"] = (values["x"] * values["y"] + int(operation[2])) % int(operation[1])
        elif kind == "rotate_left":
            values = {"x": values["y"], "y": values["z"], "z": values["x"]}
        elif kind == "x_add_scaled_y":
            values["x"] += int(operation[1]) * values["y"]
        elif kind == "y_add_scaled_z":
            values["y"] += int(operation[1]) * values["z"]
        elif kind == "z_subtract_scaled_x":
            values["z"] -= int(operation[1]) * values["x"]
        else:
            raise AssertionError("unknown state operation")
    return 3 * values["x"] - 2 * values["y"] + values["z"]


def _state_prompt(spec: Mapping[str, Any]) -> str:
    descriptions = []
    for operation in spec["operations"]:
        kind = operation[0]
        if kind == "assign_x_sum":
            descriptions.append("set X to current Y + current Z %+d" % int(operation[1]))
        elif kind == "assign_y_mix":
            descriptions.append(
                "set Y to %d times current X - current Z %+d"
                % (int(operation[1]), int(operation[2]))
            )
        elif kind == "assign_z_product_mod":
            descriptions.append(
                "set Z to (current X times current Y %+d) modulo %d"
                % (int(operation[2]), int(operation[1]))
            )
        elif kind == "rotate_left":
            descriptions.append("simultaneously set (X,Y,Z) to (current Y,current Z,current X)")
        elif kind == "x_add_scaled_y":
            descriptions.append("add %d times current Y to X" % int(operation[1]))
        elif kind == "y_add_scaled_z":
            descriptions.append("add %d times current Z to Y" % int(operation[1]))
        else:
            descriptions.append("subtract %d times current X from Z" % int(operation[1]))
    return (
        "Three registers start at X=%d, Y=%d, Z=%d. Each operation uses the state produced by "
        "the preceding operation. Apply in order: %s. Compute final 3X - 2Y + Z, explain the "
        "state changes, and finish with %s <signed integer>."
        % (
            spec["x"],
            spec["y"],
            spec["z"],
            "; then ".join(descriptions),
            FINAL_ANSWER_MARKER,
        )
    )


def _route_spec(level_index: int, variant_index: int) -> Dict[str, Any]:
    node_count = 4 + 2 * level_index
    nodes = tuple(chr(ord("A") + index) for index in range(node_count))
    edges: List[Tuple[str, str, int]] = []
    for index in range(node_count - 1):
        edges.append(
            (
                nodes[index],
                nodes[index + 1],
                _bounded("route", level_index, variant_index, "chain", index, low=3, high=15),
            )
        )
    # Skip edges keep the graph a shortest-route problem rather than a simple
    # sum while preserving a DAG and a guaranteed A-to-target path.
    for span in range(2, min(node_count, 3 + level_index)):
        for left in range(node_count - span):
            if (left + span + variant_index) % 2 and span > 2:
                continue
            edges.append(
                (
                    nodes[left],
                    nodes[left + span],
                    _bounded(
                        "route",
                        level_index,
                        variant_index,
                        "skip",
                        span,
                        left,
                        low=4,
                        high=21 + 3 * level_index,
                    ),
                )
            )
    return {"nodes": nodes, "edges": tuple(edges), "start": nodes[0], "target": nodes[-1]}


def _route_answer(spec: Mapping[str, Any]) -> int:
    distances = {node: None for node in spec["nodes"]}
    distances[spec["start"]] = 0
    for node in spec["nodes"]:
        if distances[node] is None:
            continue
        for left, right, weight in spec["edges"]:
            if left == node:
                candidate = distances[node] + weight
                if distances[right] is None or candidate < distances[right]:
                    distances[right] = candidate
    return int(distances[spec["target"]])


def _route_independent_answer(spec: Mapping[str, Any]) -> int:
    outgoing: Dict[str, List[Tuple[str, int]]] = {node: [] for node in spec["nodes"]}
    for left, right, weight in spec["edges"]:
        outgoing[left].append((right, weight))

    def paths(node: str) -> Iterable[int]:
        if node == spec["target"]:
            yield 0
            return
        for child, weight in outgoing[node]:
            for remainder in paths(child):
                yield weight + remainder

    return min(paths(spec["start"]))


def _route_prompt(spec: Mapping[str, Any]) -> str:
    edge_text = ", ".join("%s->%s costs %d" % edge for edge in spec["edges"])
    return (
        "A directed route network has edges %s. What is the minimum total cost from %s to %s? "
        "Show the route reasoning and finish with %s <integer>."
        % (edge_text, spec["start"], spec["target"], FINAL_ANSWER_MARKER)
    )


def _dag_spec(level_index: int, variant_index: int) -> Dict[str, Any]:
    layer_widths = (
        (2, 2, 1),
        (3, 3, 2, 1),
        (3, 4, 3, 2, 1),
        (4, 5, 4, 3, 2, 1),
    )[level_index]
    layers = tuple(
        tuple("L%dT%d" % (layer_index, task_index) for task_index in range(width))
        for layer_index, width in enumerate(layer_widths)
    )
    dependencies: Dict[str, set[str]] = {
        name: set() for layer in layers for name in layer
    }
    for layer_index in range(1, len(layers)):
        parents = layers[layer_index - 1]
        children = layers[layer_index]
        # Cover every parent and child.  All edges cross exactly one layer, so
        # no direct edge is transitively redundant; secondary assignments make
        # joins explicit rather than creating disguised serial chains.
        for parent_index, parent in enumerate(parents):
            child = children[(parent_index + variant_index + layer_index) % len(children)]
            dependencies[child].add(parent)
        for child_index, child in enumerate(children):
            primary = parents[(child_index + variant_index) % len(parents)]
            dependencies[child].add(primary)
            if len(parents) > 1:
                secondary = parents[
                    (child_index + variant_index + layer_index + 1) % len(parents)
                ]
                dependencies[child].add(secondary)
    tasks = {}
    for layer_index, layer in enumerate(layers):
        for task_index, name in enumerate(layer):
            tasks[name] = {
                "duration": _bounded(
                    "dag",
                    level_index,
                    variant_index,
                    "duration",
                    layer_index,
                    task_index,
                    low=2,
                    high=13 + 2 * level_index,
                ),
                "dependencies": tuple(sorted(dependencies[name])),
            }
    return {"tasks": tasks, "layers": layers}


def _dag_answer(spec: Mapping[str, Any]) -> int:
    finish: Dict[str, int] = {}
    for name, task in spec["tasks"].items():
        finish[name] = int(task["duration"]) + max(
            (finish[parent] for parent in task["dependencies"]),
            default=0,
        )
    return max(finish.values())


def _dag_independent_answer(spec: Mapping[str, Any]) -> int:
    tasks = spec["tasks"]

    def path_length(name: str) -> int:
        parents = tasks[name]["dependencies"]
        if not parents:
            return int(tasks[name]["duration"])
        return int(tasks[name]["duration"]) + max(path_length(parent) for parent in parents)

    return max(path_length(name) for name in tasks)


def _dag_prompt(spec: Mapping[str, Any]) -> str:
    task_text = "; ".join(
        "%s takes %d time units and depends on %s"
        % (name, task["duration"], ", ".join(task["dependencies"]) or "nothing")
        for name, task in spec["tasks"].items()
    )
    return (
        "Tasks in a DAG may start when all dependencies finish: %s. What is the earliest project "
        "completion time? Explain the critical path and finish with %s <integer>."
        % (task_text, FINAL_ANSWER_MARKER)
    )


def _set_spec(level_index: int, variant_index: int) -> Dict[str, Any]:
    set_count = 3 + level_index
    universe = 40 + level_index * 19 + variant_index * 11
    membership = []
    for element in range(universe):
        mask = 0
        for set_index in range(set_count):
            if _u32("set", level_index, variant_index, element, set_index) % 3:
                mask |= 1 << set_index
        membership.append(mask)
    query = ("union", "exactly_one", "none", "at_least_two")[level_index]
    return {"set_count": set_count, "universe": universe, "membership": tuple(membership), "query": query}


def _set_intersection_counts(spec: Mapping[str, Any]) -> Dict[int, int]:
    set_count = int(spec["set_count"])
    return {
        mask: sum(1 for membership in spec["membership"] if membership & mask == mask)
        for mask in range(1, 1 << set_count)
    }


def _set_answer(spec: Mapping[str, Any]) -> int:
    membership = spec["membership"]
    query = spec["query"]
    if query == "union":
        return sum(bool(mask) for mask in membership)
    if query == "none":
        return sum(mask == 0 for mask in membership)
    if query == "exactly_one":
        return sum(bin(mask).count("1") == 1 for mask in membership)
    return sum(bin(mask).count("1") >= 2 for mask in membership)


def _set_independent_answer(spec: Mapping[str, Any]) -> int:
    counts = _set_intersection_counts(spec)
    by_size = {
        size: sum(count for mask, count in counts.items() if bin(mask).count("1") == size)
        for size in range(1, int(spec["set_count"]) + 1)
    }
    union = sum(
        (1 if size % 2 else -1) * count for size, count in by_size.items()
    )
    if spec["query"] == "union":
        return union
    if spec["query"] == "none":
        return int(spec["universe"]) - union
    if spec["query"] == "exactly_one":
        return sum(
            (1 if size % 2 else -1) * size * count
            for size, count in by_size.items()
        )
    return sum(
        ((-1) ** size) * (size - 1) * count
        for size, count in by_size.items()
        if size >= 2
    )


def _set_prompt(spec: Mapping[str, Any]) -> str:
    counts = _set_intersection_counts(spec)
    labels = tuple(chr(ord("A") + index) for index in range(spec["set_count"]))
    facts = ["|%s|=%d" % (labels[index], counts[1 << index]) for index in range(spec["set_count"])]
    for size in range(2, spec["set_count"] + 1):
        for mask in range(1, 1 << spec["set_count"]):
            if bin(mask).count("1") != size:
                continue
            name = "∩".join(labels[index] for index in range(spec["set_count"]) if mask & (1 << index))
            facts.append("|%s|=%d" % (name, counts[mask]))
    query = {
        "union": "at least one set",
        "exactly_one": "exactly one set",
        "none": "none of the sets",
        "at_least_two": "at least two sets",
    }[spec["query"]]
    return (
        "In a universe of %d items, the set intersections are %s. How many items belong to %s? "
        "Reason from the inclusion-exclusion information and finish with %s <integer>."
        % (spec["universe"], ", ".join(facts), query, FINAL_ANSWER_MARKER)
    )


def _arrangement_spec(level_index: int, variant_index: int) -> Dict[str, Any]:
    item_count = 5 + level_index
    items = tuple(chr(ord("A") + index) for index in range(item_count))
    target = tuple(
        sorted(
            items,
            key=lambda item: _digest_bytes("arrangement", level_index, variant_index, "order", item),
        )
    )
    candidates: List[Tuple[Any, ...]] = []
    for left_index in range(item_count):
        for right_index in range(left_index + 1, item_count):
            if left_index + 1 < right_index:
                candidates.append(("before", target[left_index], target[right_index]))
    for index in range(item_count - 1):
        candidates.append(("adjacent", target[index], target[index + 1]))
    for index in range(item_count):
        candidates.append(("fixed", target[index], index + 1))
    for left_index in range(item_count):
        for right_index in range(left_index + 2, item_count):
            candidates.append(("not_adjacent", target[left_index], target[right_index]))
    candidates = sorted(
        candidates,
        key=lambda item: _digest_bytes("arrangement", level_index, variant_index, "constraint", *item),
    )
    constraint_count = 2 + level_index * 2 + variant_index
    constraints = []
    seen = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        constraints.append(candidate)
        if len(constraints) == constraint_count:
            break
    return {"items": items, "target": target, "constraints": tuple(constraints)}


def _arrangement_valid(order: Sequence[str], constraints: Sequence[Tuple[Any, ...]]) -> bool:
    positions = {item: index + 1 for index, item in enumerate(order)}
    for constraint in constraints:
        kind = constraint[0]
        if kind == "before" and not positions[constraint[1]] < positions[constraint[2]]:
            return False
        if kind == "adjacent" and abs(positions[constraint[1]] - positions[constraint[2]]) != 1:
            return False
        if kind == "fixed" and positions[constraint[1]] != constraint[2]:
            return False
        if kind == "not_adjacent" and abs(positions[constraint[1]] - positions[constraint[2]]) == 1:
            return False
    return True


def _arrangement_answer(spec: Mapping[str, Any]) -> int:
    items = tuple(spec["items"])
    constraints = tuple(spec["constraints"])
    item_indexes = {item: index for index, item in enumerate(items)}
    full_mask = (1 << len(items)) - 1

    @lru_cache(maxsize=None)
    def count(mask: int, last_index: int) -> int:
        if mask == full_mask:
            return 1
        position = bin(mask).count("1") + 1
        total = 0
        for candidate_index, candidate in enumerate(items):
            candidate_bit = 1 << candidate_index
            if mask & candidate_bit:
                continue
            admissible = True
            for constraint in constraints:
                kind = constraint[0]
                left, right = constraint[1], constraint[2]
                if kind == "fixed":
                    if (candidate == left) != (position == int(right)):
                        admissible = False
                        break
                    continue
                other = right if candidate == left else left
                other_index = item_indexes[other]
                other_present = bool(mask & (1 << other_index))
                if kind == "before" and candidate == right and not other_present:
                    admissible = False
                    break
                if kind == "adjacent":
                    if candidate in (left, right) and other_present and last_index != other_index:
                        admissible = False
                        break
                    if candidate not in (left, right) and last_index in (
                        item_indexes[left],
                        item_indexes[right],
                    ):
                        last_item = items[last_index]
                        counterpart = right if last_item == left else left
                        if not (mask & (1 << item_indexes[counterpart])):
                            admissible = False
                            break
                if (
                    kind == "not_adjacent"
                    and candidate in (left, right)
                    and last_index == other_index
                ):
                    admissible = False
                    break
            if admissible:
                total += count(mask | candidate_bit, candidate_index)
        return total

    return count(0, -1)


def _arrangement_independent_answer(spec: Mapping[str, Any]) -> int:
    constraints = spec["constraints"]

    def independently_valid(order: Sequence[str]) -> bool:
        for constraint in constraints:
            kind = constraint[0]
            left = order.index(constraint[1])
            if kind == "fixed":
                if left + 1 != int(constraint[2]):
                    return False
                continue
            right = order.index(constraint[2])
            if kind == "before" and left >= right:
                return False
            if kind == "adjacent" and abs(left - right) != 1:
                return False
            if kind == "not_adjacent" and abs(left - right) == 1:
                return False
        return True

    count = 0

    def visit(prefix: Tuple[str, ...], remaining: Tuple[str, ...]) -> None:
        nonlocal count
        if not remaining:
            if independently_valid(prefix):
                count += 1
            return
        for item in remaining:
            visit(prefix + (item,), tuple(candidate for candidate in remaining if candidate != item))

    visit((), tuple(spec["items"]))
    return count


def _arrangement_prompt(spec: Mapping[str, Any]) -> str:
    descriptions = []
    for constraint in spec["constraints"]:
        kind = constraint[0]
        if kind == "before":
            descriptions.append("%s is before %s" % constraint[1:])
        elif kind == "adjacent":
            descriptions.append("%s is adjacent to %s" % constraint[1:])
        elif kind == "fixed":
            descriptions.append("%s is in position %d" % constraint[1:])
        else:
            descriptions.append("%s is not adjacent to %s" % constraint[1:])
    return (
        "Arrange %s in a line, using each item exactly once. Constraints: %s. How many valid "
        "arrangements exist? Show concise counting reasoning and finish with %s <integer>."
        % (", ".join(spec["items"]), "; ".join(descriptions), FINAL_ANSWER_MARKER)
    )


_BUILDERS = {
    FAMILY_ORDER[0]: (_state_spec, _state_answer, _state_prompt),
    FAMILY_ORDER[1]: (_route_spec, _route_answer, _route_prompt),
    FAMILY_ORDER[2]: (_dag_spec, _dag_answer, _dag_prompt),
    FAMILY_ORDER[3]: (_set_spec, _set_answer, _set_prompt),
    FAMILY_ORDER[4]: (_arrangement_spec, _arrangement_answer, _arrangement_prompt),
}
_INDEPENDENT_ORACLES = {
    FAMILY_ORDER[0]: _state_independent_answer,
    FAMILY_ORDER[1]: _route_independent_answer,
    FAMILY_ORDER[2]: _dag_independent_answer,
    FAMILY_ORDER[3]: _set_independent_answer,
    FAMILY_ORDER[4]: _arrangement_independent_answer,
}


def _build_case(family: str, level_index: int, variant_index: int) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    spec_builder, answer_builder, prompt_builder = _BUILDERS[family]
    spec = spec_builder(level_index, variant_index)
    answer = int(answer_builder(spec))
    level = STRUCTURAL_LEVEL_ORDER[level_index]
    variant = VARIANT_ORDER[variant_index]
    family_slug = family.replace("_", "-")
    return (
        {
            "case_id": "reasoning-v2-content-%s-%s-%s" % (family_slug, level, variant),
            "task_id": "%s/%s/%s/%s" % (BENCHMARK_ID, family, level, variant),
            "category": family,
            "structural_level": level,
            "variant": variant,
            "prompt": prompt_builder(spec),
            "expected_answers": [str(answer)],
        },
        spec,
    )


_CASE_ROWS: List[Dict[str, Any]] = []
_CASE_SPECS: Dict[str, Dict[str, Any]] = {}
# Alternating variants across two passes makes every prefix reviewable: canary
# covers all five families, standard covers every structural level and both
# variants, and gold completes both variants for every family/level cell.
for pass_index in range(len(VARIANT_ORDER)):
    for level_index in range(len(STRUCTURAL_LEVEL_ORDER)):
        variant_index = (level_index + pass_index) % len(VARIANT_ORDER)
        for family in FAMILY_ORDER:
            case, spec = _build_case(family, level_index, variant_index)
            _CASE_ROWS.append(case)
            _CASE_SPECS[case["task_id"]] = spec


def reasoning_constraint_stress_v2_content_cases() -> List[Dict[str, Any]]:
    """Return fresh copies of the planned 40-case content fixture."""
    return deepcopy(_CASE_ROWS)


def _fixture_digest(cases: Sequence[Mapping[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(list(cases), sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


FIXTURE_SHA256 = _fixture_digest(_CASE_ROWS)
FULL_FIXTURE_SHA256 = FIXTURE_SHA256
FULL_SELECTION_SHA256 = selection_digest(
    (case["task_id"] for case in _CASE_ROWS), SELECTION_DIGEST_ALGORITHM
)
TIER_SELECTION_DIGESTS = {
    tier: selection_digest(
        (case["task_id"] for case in _CASE_ROWS[:count]), SELECTION_DIGEST_ALGORITHM
    )
    for tier, count in TIER_PREFIX_COUNTS.items()
}
TIER_COVERAGE = {
    tier: {
        "case_count": count,
        "family_counts": dict(Counter(case["category"] for case in _CASE_ROWS[:count])),
        "structural_level_counts": dict(
            Counter(case["structural_level"] for case in _CASE_ROWS[:count])
        ),
        "variant_counts": dict(Counter(case["variant"] for case in _CASE_ROWS[:count])),
    }
    for tier, count in TIER_PREFIX_COUNTS.items()
}


def independent_oracle_answers() -> Dict[str, str]:
    """Return answers from independent family oracles keyed by task id."""
    answers = {}
    for case in _CASE_ROWS:
        family = case["category"]
        answers[case["task_id"]] = str(_INDEPENDENT_ORACLES[family](_CASE_SPECS[case["task_id"]]))
    return answers


def tier_selection_metadata() -> Dict[str, Dict[str, Any]]:
    """Return immutable identity metadata for the three prefix selections."""
    return {
        tier: {
            "case_count": TIER_PREFIX_COUNTS[tier],
            "selection_digest_algorithm": SELECTION_DIGEST_ALGORITHM,
            "selection_sha256": TIER_SELECTION_DIGESTS[tier],
            "coverage": deepcopy(TIER_COVERAGE[tier]),
        }
        for tier in TIER_PREFIX_COUNTS
    }


__all__ = [
    "BENCHMARK_ID",
    "FAMILY_ORDER",
    "FIXTURE_REVISION",
    "FIXTURE_SHA256",
    "FULL_FIXTURE_SHA256",
    "FULL_SELECTION_SHA256",
    "GENERATOR_ALGORITHM",
    "GENERATOR_ID",
    "GENERATOR_REVISION",
    "GENERATOR_SEED",
    "GENERATOR_SEED_SHA256",
    "LOCKED_FIXTURE_SHA256",
    "LOCKED_FULL_SELECTION_SHA256",
    "LOCKED_GENERATOR_SEED_SHA256",
    "LOCKED_TIER_COVERAGE",
    "LOCKED_TIER_SELECTION_DIGESTS",
    "FINAL_ANSWER_MARKER",
    "FINAL_ANSWER_PARSER_ID",
    "MAX_INTEGER_DIGITS",
    "parse_content_answer",
    "SCORING_POLICY",
    "SELECTION_DIGEST_ALGORITHM",
    "STRUCTURAL_LEVEL_ORDER",
    "TIER_COVERAGE",
    "TIER_PREFIX_COUNTS",
    "TIER_SELECTION_DIGESTS",
    "VARIANT_ORDER",
    "independent_oracle_answers",
    "reasoning_constraint_stress_v2_content_cases",
    "tier_selection_metadata",
]
