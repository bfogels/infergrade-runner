"""Runner-owned identity checks for the prompt-free LongBench selection."""

import hashlib
import json
from copy import deepcopy
from importlib import resources
from typing import Any, Dict, List

from infergrade.selection_identity import selection_digest


BENCHMARK_ID = "longbench_v2_local_reference_v1"
DATASET = "zai-org/LongBench-v2"
DATASET_REVISION = "2b48e494f2c7a2f0af81aae178e05c7e1dde0fe9"
DATASET_SHA256 = "15d61c22d92c96900b3c4948b6aeea218d3214b676a65df48e7b8555604c7fe2"
SNAPSHOT_SHA256 = "677ac38dc799b0bbe61816f1d0c245bb93f01dd535a71ecfde6fa619d3eb86db"
RAW_SELECTION_SHA256 = "1a5f48517a31dc80083700955b92d9524cba2d863448209956e2cf1b423079a3"
PUBLIC_PROJECTION_SHA256 = "b2a920e6f20e2a725f48d402d6a6ca8cc142e0447866d67673da2f0f54704327"
MANIFEST_PACKAGE = "infergrade.audit_manifests"
MANIFEST_FILENAME = "longbench_v2_selection_manifest.json"
MANIFEST_ARTIFACT_KIND = "longbench_selection_manifest"
RECEIPT_ARTIFACT_KIND = "longbench_selection_receipt"
ARTIFACT_SPEC_VERSION = "0.1.0"
SELECTION_DIGEST_ALGORITHM = "sorted_utf8_newline_sha256_v1"
SELECTION_DIGEST_CONVENTION = (
    "sha256 of sorted raw LongBench _id values joined by one UTF-8 newline, "
    "with no trailing newline"
)
TIER_NAMES = ("canary", "standard", "gold")
TIER_PREFIX_COUNTS = {"canary": 6, "standard": 12, "gold": 23}
_PROMPT_FIELDS = {
    "answer",
    "choice_A",
    "choice_B",
    "choice_C",
    "choice_D",
    "context",
    "prompt",
    "question",
}
_MANIFEST_METADATA_FIELDS = (
    "benchmark_id",
    "dataset",
    "dataset_revision",
    "dataset_sha256",
    "snapshot_sha256",
    "dataset_license",
    "source_case_count",
    "source_short_case_count",
    "source_context_fit_case_count",
    "maximum_estimated_context_tokens",
    "domain_count",
    "difficulty_count",
    "length_scope",
    "selection_policy",
    "selection_digest_algorithm",
    "selection_digest_convention",
)
_MANIFEST_FIELDS = frozenset(
    {
        "artifact_kind",
        "artifact_spec_version",
        "benchmark_id",
        "case_count",
        "dataset",
        "dataset_license",
        "dataset_revision",
        "dataset_sha256",
        "difficulties",
        "difficulty_count",
        "domain_count",
        "domains",
        "length_scope",
        "maximum_estimated_context_tokens",
        "selection_digest_algorithm",
        "selection_digest_convention",
        "selection_policy",
        "selection_projection",
        "selection_sha256",
        "selected_ids",
        "snapshot_sha256",
        "source_case_count",
        "source_context_fit_case_count",
        "source_short_case_count",
        "tier_prefix_counts",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "artifact_kind",
        "artifact_spec_version",
        *_MANIFEST_METADATA_FIELDS,
        "tier",
        "case_count",
        "selected_ids",
        "prepared_ids",
        "selection_projection",
        "selection_sha256",
    }
)
_TIER_SAMPLE_POLICIES = {
    "canary": "short_domain_balanced_difficulty_mixed_6_v1",
    "standard": "short_domain_difficulty_balanced_12_v1",
    "gold": "short_domain_difficulty_balanced_23_v1",
}
_BENCHMARK_METADATA_FIELDS = frozenset(
    {
        "benchmark_id",
        "display_name",
        "case_count",
        "category_count",
        "difficulty_count",
        "length_scope",
        "minimum_context_word_count",
        "maximum_context_word_count",
        "context_bucket_counts",
        "dataset",
        "dataset_revision",
        "dataset_sha256",
        "dataset_license",
        "snapshot_sha256",
        "sample_policy",
        "selection_digest_algorithm",
        "selection_digest_convention",
        "selection_sha256",
    }
)


def load_longbench_selection_manifest() -> Dict[str, Any]:
    """Load and validate the immutable package manifest."""
    with resources.open_text(MANIFEST_PACKAGE, MANIFEST_FILENAME, encoding="utf-8") as handle:
        manifest = json.load(handle)
    _validate_manifest(manifest)
    return deepcopy(manifest)


def longbench_tier_ids(tier: str) -> List[str]:
    """Return the exact raw ``_id`` prefix allowed for a Runner tier."""
    manifest = load_longbench_selection_manifest()
    _validate_tier(tier, manifest)
    return list(manifest["selected_ids"][: manifest["tier_prefix_counts"][tier]])


def verify_longbench_selection_receipt(
    receipt: Any,
    prepared_cases: List[Dict[str, Any]],
    tier: str,
    benchmark_metadata: Any = None,
) -> Dict[str, Any]:
    """Compare an untrusted container receipt and prepared cases to the manifest."""
    manifest = load_longbench_selection_manifest()
    _validate_tier(tier, manifest)
    if not isinstance(receipt, dict):
        raise ValueError("LongBench selection receipt must be an object")
    if set(receipt) != _RECEIPT_FIELDS:
        raise ValueError("LongBench selection receipt fields are not allowlisted")
    _reject_prompt_fields(receipt, "receipt")
    if receipt.get("artifact_kind") != RECEIPT_ARTIFACT_KIND:
        raise ValueError("LongBench selection receipt artifact kind mismatch")
    if receipt.get("artifact_spec_version") != ARTIFACT_SPEC_VERSION:
        raise ValueError("LongBench selection receipt artifact version mismatch")

    for field in _MANIFEST_METADATA_FIELDS:
        if receipt.get(field) != manifest.get(field):
            raise ValueError("LongBench selection receipt metadata mismatch: %s" % field)
    if receipt.get("tier") != tier:
        raise ValueError("LongBench selection receipt tier mismatch")

    expected_count = int(manifest["tier_prefix_counts"][tier])
    expected_ids = list(manifest["selected_ids"][:expected_count])
    expected_projection = list(manifest["selection_projection"][:expected_count])
    selected_ids = _required_string_list(receipt, "selected_ids")
    prepared_ids = _required_string_list(receipt, "prepared_ids")
    if len(selected_ids) != expected_count:
        raise ValueError("LongBench selection receipt case count mismatch")
    if len(prepared_ids) != expected_count:
        raise ValueError("LongBench selection receipt prepared ID count mismatch")
    _check_ids(selected_ids, manifest["selected_ids"], "selected IDs")
    _check_ids(prepared_ids, manifest["selected_ids"], "prepared IDs")
    if selected_ids != expected_ids:
        raise ValueError("LongBench selection receipt selected ID order mismatch")
    if prepared_ids != expected_ids:
        raise ValueError("LongBench selection receipt prepared IDs mismatch")

    projection = receipt.get("selection_projection")
    if projection != expected_projection:
        raise ValueError("LongBench selection receipt selection projection mismatch")
    if receipt.get("case_count") != expected_count:
        raise ValueError("LongBench selection receipt case count metadata mismatch")
    expected_digest = selection_digest(expected_ids, SELECTION_DIGEST_ALGORITHM)
    if receipt.get("selection_sha256") != expected_digest:
        raise ValueError("LongBench selection receipt selection digest mismatch")

    if not isinstance(prepared_cases, list) or len(prepared_cases) != expected_count:
        raise ValueError("LongBench prepared case count mismatch")
    prepared_case_ids = []
    prepared_projection = []
    for index, case in enumerate(prepared_cases):
        if not isinstance(case, dict):
            raise ValueError("LongBench prepared case %d must be an object" % index)
        raw_id = str(case.get("question_id") or "").strip()
        if not raw_id:
            task_id = str(case.get("task_id") or "")
            prefix = "longbench_v2/"
            raw_id = task_id[len(prefix) :] if task_id.startswith(prefix) else ""
        prepared_case_ids.append(raw_id)
        prepared_projection.append(
            {
                "_id": raw_id,
                "domain": str(case.get("category") or ""),
                "sub_domain": str(case.get("sub_domain") or ""),
                "difficulty": str(case.get("difficulty") or ""),
                "length": str(case.get("length") or ""),
            }
        )
    _check_ids(prepared_case_ids, manifest["selected_ids"], "prepared case IDs")
    if prepared_case_ids != expected_ids:
        raise ValueError("LongBench prepared case IDs mismatch selection receipt")
    expected_task_ids = ["longbench_v2/%s" % raw_id for raw_id in expected_ids]
    actual_task_ids = [str(case.get("task_id") or "") for case in prepared_cases]
    if actual_task_ids != expected_task_ids:
        raise ValueError("LongBench prepared task IDs mismatch selection receipt")
    if prepared_projection != expected_projection:
        raise ValueError("LongBench prepared case metadata mismatch selection receipt")
    if benchmark_metadata is not None:
        _verify_benchmark_metadata(
            benchmark_metadata,
            manifest,
            receipt,
            prepared_cases,
            expected_projection,
            tier,
            expected_count,
            expected_digest,
        )
    return {
        "benchmark_id": BENCHMARK_ID,
        "tier": tier,
        "case_count": expected_count,
        "selection_sha256": expected_digest,
    }


def _validate_tier(tier: str, manifest: Dict[str, Any]) -> None:
    if tier not in TIER_NAMES or tier not in manifest.get("tier_prefix_counts", {}):
        raise ValueError("Unsupported LongBench tier: %s" % tier)


def _required_string_list(payload: Dict[str, Any], field: str) -> List[str]:
    value = payload.get(field)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError("LongBench selection receipt %s must be a string array" % field)
    return list(value)


def _check_ids(ids: List[str], known_ids: List[str], label: str) -> None:
    if len(ids) != len(set(ids)):
        raise ValueError("LongBench %s contain duplicate IDs" % label)
    unknown = sorted(set(ids) - set(known_ids))
    if unknown:
        raise ValueError("LongBench %s contain unknown IDs" % label)


def _verify_benchmark_metadata(
    metadata: Any,
    manifest: Dict[str, Any],
    receipt: Dict[str, Any],
    prepared_cases: List[Dict[str, Any]],
    expected_projection: List[Dict[str, str]],
    tier: str,
    expected_count: int,
    expected_digest: str,
) -> None:
    """Bind post-container provenance metadata before artifact admission."""
    if not isinstance(metadata, dict):
        raise ValueError("LongBench benchmark metadata must be an object")
    if set(metadata) != _BENCHMARK_METADATA_FIELDS:
        raise ValueError("LongBench benchmark metadata fields are not allowlisted")
    _reject_prompt_fields(metadata, "benchmark metadata")
    context_word_counts = []
    context_bucket_counts = {}
    for case in prepared_cases:
        context_word_count = case.get("context_word_count")
        bucket = case.get("nominal_context_bucket_tokens")
        if (
            isinstance(context_word_count, bool)
            or not isinstance(context_word_count, int)
            or context_word_count < 0
            or isinstance(bucket, bool)
            or not isinstance(bucket, int)
            or bucket <= 0
        ):
            raise ValueError("LongBench prepared case context metadata is invalid")
        context_word_counts.append(context_word_count)
        bucket_key = str(bucket)
        context_bucket_counts[bucket_key] = context_bucket_counts.get(bucket_key, 0) + 1
    expected_fields = {
        "benchmark_id": manifest["benchmark_id"],
        "display_name": "LongBench v2 local reference",
        "dataset": manifest["dataset"],
        "dataset_revision": manifest["dataset_revision"],
        "dataset_sha256": manifest["dataset_sha256"],
        "dataset_license": manifest["dataset_license"],
        "snapshot_sha256": manifest["snapshot_sha256"],
        "case_count": expected_count,
        "category_count": len({item["domain"] for item in expected_projection}),
        "difficulty_count": len({item["difficulty"] for item in expected_projection}),
        "length_scope": manifest["length_scope"],
        "minimum_context_word_count": min(context_word_counts),
        "maximum_context_word_count": max(context_word_counts),
        "context_bucket_counts": context_bucket_counts,
        "sample_policy": _TIER_SAMPLE_POLICIES[tier],
        "selection_digest_algorithm": manifest["selection_digest_algorithm"],
        "selection_digest_convention": manifest["selection_digest_convention"],
        "selection_sha256": expected_digest,
    }
    for field, expected_value in expected_fields.items():
        if metadata.get(field) != expected_value:
            raise ValueError("LongBench benchmark metadata mismatch: %s" % field)
    if receipt.get("dataset_revision") != metadata.get("dataset_revision"):
        raise ValueError("LongBench receipt and benchmark metadata revision mismatch")
    if receipt.get("dataset_sha256") != metadata.get("dataset_sha256"):
        raise ValueError("LongBench receipt and benchmark metadata source hash mismatch")
    if receipt.get("snapshot_sha256") != metadata.get("snapshot_sha256"):
        raise ValueError("LongBench receipt and benchmark metadata snapshot mismatch")
    if receipt.get("case_count") != metadata.get("case_count"):
        raise ValueError("LongBench receipt and benchmark metadata case count mismatch")
    if receipt.get("selection_digest_algorithm") != metadata.get("selection_digest_algorithm"):
        raise ValueError("LongBench receipt and benchmark metadata digest algorithm mismatch")
    if receipt.get("selection_digest_convention") != metadata.get("selection_digest_convention"):
        raise ValueError("LongBench receipt and benchmark metadata digest convention mismatch")
    if receipt.get("selection_sha256") != metadata.get("selection_sha256"):
        raise ValueError("LongBench receipt and benchmark metadata selection digest mismatch")


def _reject_prompt_fields(value: Any, path: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in _PROMPT_FIELDS:
                raise ValueError("LongBench %s contains prompt-bearing field %s" % (path, key))
            _reject_prompt_fields(child, "%s.%s" % (path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_prompt_fields(child, "%s[%d]" % (path, index))


def _validate_manifest(manifest: Any) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("LongBench selection manifest must be an object")
    if set(manifest) != _MANIFEST_FIELDS:
        raise ValueError("LongBench selection manifest fields are not allowlisted")
    _reject_prompt_fields(manifest, "manifest")
    if manifest.get("artifact_kind") != MANIFEST_ARTIFACT_KIND:
        raise ValueError("LongBench selection manifest artifact kind mismatch")
    if manifest.get("artifact_spec_version") != ARTIFACT_SPEC_VERSION:
        raise ValueError("LongBench selection manifest artifact version mismatch")
    if manifest.get("benchmark_id") != BENCHMARK_ID:
        raise ValueError("LongBench selection manifest benchmark mismatch")
    expected_identity = {
        "dataset": DATASET,
        "dataset_revision": DATASET_REVISION,
        "dataset_sha256": DATASET_SHA256,
        "dataset_license": "Apache-2.0",
        "snapshot_sha256": SNAPSHOT_SHA256,
        "selection_sha256": RAW_SELECTION_SHA256,
        "case_count": 23,
        "source_case_count": 503,
        "source_short_case_count": 180,
        "source_context_fit_case_count": 177,
        "maximum_estimated_context_tokens": 131072,
        "domain_count": 6,
        "difficulty_count": 2,
        "length_scope": "short",
        "selection_policy": "short_domain_difficulty_hash_rank_balanced_tier_blocks_v1",
    }
    for field, expected_value in expected_identity.items():
        if manifest.get(field) != expected_value:
            raise ValueError("LongBench selection manifest identity mismatch: %s" % field)
    if manifest.get("selection_digest_algorithm") != SELECTION_DIGEST_ALGORITHM:
        raise ValueError("LongBench selection manifest digest algorithm mismatch")
    if manifest.get("selection_digest_convention") != SELECTION_DIGEST_CONVENTION:
        raise ValueError("LongBench selection manifest digest convention mismatch")
    selected_ids = manifest.get("selected_ids")
    projection = manifest.get("selection_projection")
    if not isinstance(selected_ids, list) or not selected_ids or not all(
        isinstance(item, str) and item for item in selected_ids
    ):
        raise ValueError("LongBench selection manifest selected_ids must be a string array")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("LongBench selection manifest selected_ids contain duplicates")
    if manifest.get("case_count") != len(selected_ids):
        raise ValueError("LongBench selection manifest case count mismatch")
    if selection_digest(selected_ids, SELECTION_DIGEST_ALGORITHM) != manifest.get("selection_sha256"):
        raise ValueError("LongBench selection manifest selection digest mismatch")
    if not isinstance(projection, list) or len(projection) != len(selected_ids):
        raise ValueError("LongBench selection manifest selection projection mismatch")
    projection_ids = []
    allowed_projection_keys = {"_id", "domain", "sub_domain", "difficulty", "length"}
    for index, item in enumerate(projection):
        if not isinstance(item, dict) or set(item) != allowed_projection_keys:
            raise ValueError("LongBench selection manifest projection row %d is invalid" % index)
        if not all(isinstance(item[key], str) and item[key] for key in allowed_projection_keys):
            raise ValueError("LongBench selection manifest projection row %d is empty" % index)
        projection_ids.append(item["_id"])
    if projection_ids != selected_ids:
        raise ValueError("LongBench selection manifest projection order mismatch")
    projection_digest = hashlib.sha256(
        json.dumps(
            projection,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if projection_digest != PUBLIC_PROJECTION_SHA256:
        raise ValueError("LongBench selection manifest public projection mismatch")
    tiers = manifest.get("tier_prefix_counts")
    if tiers != TIER_PREFIX_COUNTS:
        raise ValueError("LongBench selection manifest tier prefixes are invalid")
    counts = [tiers[tier] for tier in TIER_NAMES]
    if any(isinstance(count, bool) or not isinstance(count, int) for count in counts):
        raise ValueError("LongBench selection manifest tier prefixes must be integers")
    if counts != sorted(counts) or counts[-1] != len(selected_ids) or any(count < 1 for count in counts):
        raise ValueError("LongBench selection manifest tier prefixes are inconsistent")
    domains = manifest.get("domains")
    difficulties = manifest.get("difficulties")
    if not isinstance(domains, list) or not isinstance(difficulties, list):
        raise ValueError("LongBench selection manifest strata are invalid")
    if manifest.get("domain_count") != len(domains) or manifest.get("difficulty_count") != len(difficulties):
        raise ValueError("LongBench selection manifest strata counts mismatch")
    if any(item["domain"] not in domains for item in projection):
        raise ValueError("LongBench selection manifest contains an unknown domain")
    if any(item["difficulty"] not in difficulties for item in projection):
        raise ValueError("LongBench selection manifest contains an unknown difficulty")
    if any(item["length"] != manifest.get("length_scope") for item in projection):
        raise ValueError("LongBench selection manifest contains an unexpected length")
    for field in _MANIFEST_METADATA_FIELDS:
        if field not in manifest:
            raise ValueError("LongBench selection manifest metadata is missing %s" % field)
