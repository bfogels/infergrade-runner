"""Immutable, versioned generation policies.

This module is intentionally a registry foundation.  Execution adapters and
benchmark selection do not consume it yet; a later integration change must
bind a resolved policy to the request, protocol identity, and result receipt.
Keeping the policy payload small and canonical here makes that integration
reviewable instead of allowing adapter defaults to become an implicit
benchmark contract.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Dict, Mapping, Optional, Tuple


DEFAULT_GENERATION_POLICY_ID = "deterministic_v1"
DIRECT_ANSWER_GENERATION_POLICY_ID = "deterministic_direct_answer_v1"
REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID = "reasoning_constraint_stress_thinking_v2"
# Keep the original v2 policy immutable.  Qualification uses a separately
# named, empirically more viable profile so a budget change cannot silently
# rewrite the identity of the locked policy.
REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID = (
    "reasoning_constraint_stress_qualification_thinking_v1"
)

POLICY_REVISION = "generation_policy_v1"
_MAX_OUTPUT_TOKENS = 4096
_MAX_THINKING_BUDGET_TOKENS = 4096
_MAX_SEED = 2**31 - 1
_POLICY_ID = re.compile(r"^[a-z0-9][a-z0-9_]*$")
_THINKING_MODES = frozenset(("default", "disabled", "enabled"))
_TERMINAL_ANSWER_FORMATS = frozenset(("integer",))
_TERMINAL_PROTOCOLS = frozenset(
    (
        (None, None, "none_v1"),
        ("FINAL_ANSWER:", "integer", "final_answer_integer_v1"),
    )
)
_JSON_SCALARS = (bool, int, float, str)

# These are deliberately ordered tuples rather than an inferred dataclass
# field list.  The base tuple is kept byte-compatible for legacy policies;
# optional fields are added only when a policy opts into them.
CANONICAL_POLICY_FIELDS = (
    "policy_id",
    "policy_revision",
    "protocol_version",
    "temperature",
    "top_p",
    "seed",
    "max_output_tokens",
    "max_output_token_cap",
    "thinking_mode",
    "enable_thinking",
    "thinking_budget_tokens",
    "cache_prompt",
    "prompt_directive",
    "prompt_transform_id",
    "chat_template_kwargs",
    "terminal_answer_marker",
    "terminal_answer_format",
    "terminal_parser_id",
    "stop_semantics_version",
)
OPTIONAL_CANONICAL_POLICY_FIELDS = ("top_k",)


class UnknownGenerationPolicyError(ValueError):
    """Raised when a request names a policy that is not in the registry."""


@dataclass(frozen=True)
class GenerationPolicy:
    """One complete, immutable generation-policy identity.

    ``chat_template_kwargs`` is stored as sorted tuples so a caller cannot
    mutate nested state after resolution.  ``to_dict`` returns a fresh JSON
    compatible object for serialization or future adapter integration.

    A null ``max_output_tokens`` and ``max_output_token_cap`` means the
    benchmark specification owns both values; it does not mean unbounded
    generation.  A fixed policy must instead record both a budget and a cap.
    """

    policy_id: str
    policy_revision: str
    protocol_version: str
    temperature: float
    top_p: float
    seed: int
    max_output_tokens: Optional[int]
    max_output_token_cap: Optional[int]
    thinking_mode: str
    enable_thinking: Optional[bool]
    thinking_budget_tokens: int
    cache_prompt: bool
    prompt_directive: Optional[str]
    prompt_transform_id: str
    chat_template_kwargs: Tuple[Tuple[str, Any], ...]
    terminal_answer_marker: Optional[str]
    terminal_answer_format: Optional[str]
    terminal_parser_id: str
    stop_semantics_version: str
    # ``None`` preserves the original v2 policy's canonical JSON and digest.
    # The qualification profile opts into this llama.cpp sampling control and
    # therefore includes it in its own canonical identity.
    top_k: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.policy_id, str) or not _POLICY_ID.fullmatch(self.policy_id):
            raise ValueError("policy_id must be a lowercase identifier")
        if not isinstance(self.policy_revision, str) or not self.policy_revision:
            raise ValueError("policy_revision must be a non-empty string")
        if not isinstance(self.protocol_version, str) or not self.protocol_version:
            raise ValueError("protocol_version must be a non-empty string")
        if not isinstance(self.temperature, (int, float)) or isinstance(self.temperature, bool):
            raise ValueError("temperature must be numeric")
        if not math.isfinite(float(self.temperature)) or not 0.0 <= float(self.temperature) <= 2.0:
            raise ValueError("temperature must be finite and between 0 and 2")
        if not isinstance(self.top_p, (int, float)) or isinstance(self.top_p, bool):
            raise ValueError("top_p must be numeric")
        if not math.isfinite(float(self.top_p)) or not 0.0 < float(self.top_p) <= 1.0:
            raise ValueError("top_p must be finite and greater than 0 and at most 1")
        if self.top_k is not None and (
            not isinstance(self.top_k, int)
            or isinstance(self.top_k, bool)
            or not 0 <= self.top_k <= _MAX_OUTPUT_TOKENS
        ):
            raise ValueError("top_k must be null or an integer between 0 and 4096")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or not 0 <= self.seed <= _MAX_SEED:
            raise ValueError("seed must be an integer between 0 and 2^31-1")
        if self.max_output_tokens is not None and (
            not isinstance(self.max_output_tokens, int)
            or isinstance(self.max_output_tokens, bool)
            or not 1 <= self.max_output_tokens <= _MAX_OUTPUT_TOKENS
        ):
            raise ValueError("max_output_tokens must be null or an integer between 1 and 4096")
        if self.max_output_token_cap is not None and (
            not isinstance(self.max_output_token_cap, int)
            or isinstance(self.max_output_token_cap, bool)
            or not 1 <= self.max_output_token_cap <= _MAX_OUTPUT_TOKENS
        ):
            raise ValueError("max_output_token_cap must be null or an integer between 1 and 4096")
        if self.max_output_tokens is not None and self.max_output_token_cap is None:
            raise ValueError("fixed max_output_tokens requires a non-null max_output_token_cap")
        if (
            self.max_output_tokens is not None
            and self.max_output_token_cap is not None
            and self.max_output_tokens > self.max_output_token_cap
        ):
            raise ValueError("max_output_tokens must not exceed max_output_token_cap")
        if not isinstance(self.thinking_mode, str) or self.thinking_mode not in _THINKING_MODES:
            raise ValueError("thinking_mode must be default, disabled, or enabled")
        if self.enable_thinking is not None and not isinstance(self.enable_thinking, bool):
            raise ValueError("enable_thinking must be true, false, or null")
        expected_enable_thinking = {
            "default": None,
            "disabled": False,
            "enabled": True,
        }[self.thinking_mode]
        if self.enable_thinking != expected_enable_thinking:
            raise ValueError("enable_thinking must agree with thinking_mode")
        if (
            not isinstance(self.thinking_budget_tokens, int)
            or isinstance(self.thinking_budget_tokens, bool)
            or not 0 <= self.thinking_budget_tokens <= _MAX_THINKING_BUDGET_TOKENS
        ):
            raise ValueError("thinking_budget_tokens must be an integer between 0 and 4096")
        if not isinstance(self.cache_prompt, bool):
            raise ValueError("cache_prompt must be a boolean")
        if self.thinking_mode in {"default", "disabled"} and self.thinking_budget_tokens != 0:
            raise ValueError("default and disabled thinking policies must have a zero thinking budget")
        if self.thinking_mode == "enabled" and self.thinking_budget_tokens == 0:
            raise ValueError("enabled thinking policies must have a positive thinking budget")
        if (
            self.thinking_mode == "enabled"
            and self.max_output_tokens is not None
            and self.thinking_budget_tokens > self.max_output_tokens
        ):
            raise ValueError("thinking_budget_tokens must not exceed fixed max_output_tokens")
        if (
            self.thinking_mode == "enabled"
            and self.max_output_token_cap is not None
            and self.thinking_budget_tokens > self.max_output_token_cap
        ):
            raise ValueError("thinking_budget_tokens must not exceed max_output_token_cap")
        if self.prompt_directive is not None and not isinstance(self.prompt_directive, str):
            raise ValueError("prompt_directive must be a string or null")
        if not isinstance(self.prompt_transform_id, str) or not self.prompt_transform_id:
            raise ValueError("prompt_transform_id must be a non-empty string")
        if not isinstance(self.chat_template_kwargs, tuple):
            raise ValueError("chat_template_kwargs must be an immutable tuple of pairs")
        previous_key = None
        chat_template_values: Dict[str, Any] = {}
        for item in self.chat_template_kwargs:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError("chat_template_kwargs entries must be (key, value) tuples")
            key, value = item
            if not isinstance(key, str) or not key:
                raise ValueError("chat_template_kwargs keys must be non-empty strings")
            if previous_key is not None and key <= previous_key:
                raise ValueError("chat_template_kwargs keys must be unique and sorted")
            if not isinstance(value, _JSON_SCALARS) or (isinstance(value, float) and not math.isfinite(value)):
                raise ValueError("chat_template_kwargs values must be finite JSON scalars")
            chat_template_values[key] = value
            previous_key = key
        if "enable_thinking" in chat_template_values:
            template_enable_thinking = chat_template_values["enable_thinking"]
            if not isinstance(template_enable_thinking, bool):
                raise ValueError("chat_template_kwargs.enable_thinking must be a boolean")
            if template_enable_thinking is not self.enable_thinking:
                raise ValueError("chat_template_kwargs.enable_thinking must agree with enable_thinking")
        if self.terminal_answer_marker is not None and not isinstance(self.terminal_answer_marker, str):
            raise ValueError("terminal_answer_marker must be a string or null")
        if self.terminal_answer_format is not None and not isinstance(self.terminal_answer_format, str):
            raise ValueError("terminal_answer_format must be a string or null")
        if self.terminal_answer_format is not None and self.terminal_answer_format not in _TERMINAL_ANSWER_FORMATS:
            raise ValueError("terminal_answer_format is unsupported")
        if not isinstance(self.terminal_parser_id, str) or not self.terminal_parser_id:
            raise ValueError("terminal_parser_id must be a non-empty string")
        terminal_protocol = (
            self.terminal_answer_marker,
            self.terminal_answer_format,
            self.terminal_parser_id,
        )
        if terminal_protocol not in _TERMINAL_PROTOCOLS:
            raise ValueError("terminal answer marker, format, and parser must name one supported protocol")
        if not isinstance(self.stop_semantics_version, str) or not self.stop_semantics_version:
            raise ValueError("stop_semantics_version must be a non-empty string")

    def to_dict(self) -> Dict[str, Any]:
        """Return the canonical policy fields as a fresh JSON-compatible dict."""

        payload = {
            "policy_id": self.policy_id,
            "policy_revision": self.policy_revision,
            "protocol_version": self.protocol_version,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "seed": self.seed,
            "max_output_tokens": self.max_output_tokens,
            "max_output_token_cap": self.max_output_token_cap,
            "thinking_mode": self.thinking_mode,
            "enable_thinking": self.enable_thinking,
            "thinking_budget_tokens": self.thinking_budget_tokens,
            "cache_prompt": self.cache_prompt,
            "prompt_directive": self.prompt_directive,
            "prompt_transform_id": self.prompt_transform_id,
            "chat_template_kwargs": {key: value for key, value in self.chat_template_kwargs},
            "terminal_answer_marker": self.terminal_answer_marker,
            "terminal_answer_format": self.terminal_answer_format,
            "terminal_parser_id": self.terminal_parser_id,
            "stop_semantics_version": self.stop_semantics_version,
        }
        if self.top_k is not None:
            payload["top_k"] = self.top_k
        return payload

    def canonical_json(self) -> str:
        """Serialize policy fields with one stable JSON representation."""

        return json.dumps(
            self.to_dict(),
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def fingerprint_sha256(self) -> str:
        """Return the lowercase SHA-256 of the canonical policy JSON."""

        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def fingerprint(self) -> str:
        """Short ergonomic alias for the canonical SHA-256 fingerprint."""

        return self.fingerprint_sha256


def _policy(
    policy_id: str,
    *,
    protocol_version: str,
    max_output_tokens: Optional[int],
    max_output_token_cap: Optional[int],
    thinking_mode: str,
    enable_thinking: Optional[bool],
    thinking_budget_tokens: int,
    cache_prompt: bool,
    prompt_directive: Optional[str],
    prompt_transform_id: str,
    chat_template_kwargs: Tuple[Tuple[str, Any], ...],
    terminal_parser_id: str,
    stop_semantics_version: str,
    terminal_answer_marker: Optional[str] = None,
    terminal_answer_format: Optional[str] = None,
    policy_revision: str = POLICY_REVISION,
    temperature: float = 0.0,
    top_p: float = 1.0,
    top_k: Optional[int] = None,
) -> GenerationPolicy:
    return GenerationPolicy(
        policy_id=policy_id,
        policy_revision=policy_revision,
        protocol_version=protocol_version,
        temperature=temperature,
        top_p=top_p,
        seed=0,
        max_output_tokens=max_output_tokens,
        max_output_token_cap=max_output_token_cap,
        thinking_mode=thinking_mode,
        enable_thinking=enable_thinking,
        thinking_budget_tokens=thinking_budget_tokens,
        cache_prompt=cache_prompt,
        prompt_directive=prompt_directive,
        prompt_transform_id=prompt_transform_id,
        chat_template_kwargs=chat_template_kwargs,
        terminal_answer_marker=terminal_answer_marker,
        terminal_answer_format=terminal_answer_format,
        terminal_parser_id=terminal_parser_id,
        stop_semantics_version=stop_semantics_version,
        top_k=top_k,
    )


GENERATION_POLICY_REGISTRY: Mapping[str, GenerationPolicy] = MappingProxyType(
    {
        DEFAULT_GENERATION_POLICY_ID: _policy(
            DEFAULT_GENERATION_POLICY_ID,
            protocol_version="generation_protocol_v1",
            max_output_tokens=None,
            max_output_token_cap=None,
            thinking_mode="default",
            enable_thinking=None,
            thinking_budget_tokens=0,
            cache_prompt=False,
            prompt_directive=None,
            prompt_transform_id="none_v1",
            chat_template_kwargs=(),
            terminal_parser_id="none_v1",
            stop_semantics_version="backend_stop_v1",
        ),
        DIRECT_ANSWER_GENERATION_POLICY_ID: _policy(
            DIRECT_ANSWER_GENERATION_POLICY_ID,
            protocol_version="generation_protocol_v1",
            max_output_tokens=None,
            max_output_token_cap=None,
            thinking_mode="disabled",
            enable_thinking=False,
            thinking_budget_tokens=0,
            cache_prompt=False,
            prompt_directive="/no_think",
            prompt_transform_id="direct_answer_model_aware_v2",
            chat_template_kwargs=(("enable_thinking", False),),
            terminal_parser_id="none_v1",
            stop_semantics_version="backend_stop_v1",
        ),
        REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID: _policy(
            REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID,
            protocol_version="generation_protocol_v2",
            max_output_tokens=512,
            max_output_token_cap=512,
            thinking_mode="enabled",
            enable_thinking=True,
            thinking_budget_tokens=256,
            cache_prompt=False,
            prompt_directive=None,
            prompt_transform_id="reasoning_constraint_stress_terminal_v1",
            chat_template_kwargs=(("enable_thinking", True),),
            terminal_answer_marker="FINAL_ANSWER:",
            terminal_answer_format="integer",
            terminal_parser_id="final_answer_integer_v1",
            stop_semantics_version="natural_or_budget_v1",
        ),
        REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID: _policy(
            REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID,
            policy_revision="generation_policy_v2",
            protocol_version="generation_protocol_v3",
            temperature=0.6,
            top_p=0.95,
            top_k=20,
            max_output_tokens=1536,
            max_output_token_cap=1536,
            thinking_mode="enabled",
            enable_thinking=True,
            thinking_budget_tokens=512,
            cache_prompt=False,
            prompt_directive=(
                "After reasoning, output exactly one final line in the form "
                "FINAL_ANSWER: <signed integer>. Do not write any text after that line."
            ),
            prompt_transform_id="reasoning_constraint_stress_terminal_v2",
            chat_template_kwargs=(("enable_thinking", True),),
            terminal_answer_marker="FINAL_ANSWER:",
            terminal_answer_format="integer",
            terminal_parser_id="final_answer_integer_v1",
            stop_semantics_version="natural_or_budget_v2",
        ),
    }
)


def resolve_generation_policy(policy_id: Optional[str] = None) -> GenerationPolicy:
    """Resolve a policy id, defaulting only when the id is omitted.

    Unknown and empty ids fail closed.  In particular, a typo must not silently
    inherit the deterministic default and become part of a benchmark run.
    """

    resolved_id = DEFAULT_GENERATION_POLICY_ID if policy_id is None else policy_id
    if not isinstance(resolved_id, str) or not resolved_id:
        raise UnknownGenerationPolicyError("Unknown generation policy: %r" % (resolved_id,))
    try:
        return GENERATION_POLICY_REGISTRY[resolved_id]
    except KeyError as exc:
        raise UnknownGenerationPolicyError("Unknown generation policy: %s" % resolved_id) from exc


__all__ = [
    "CANONICAL_POLICY_FIELDS",
    "OPTIONAL_CANONICAL_POLICY_FIELDS",
    "DEFAULT_GENERATION_POLICY_ID",
    "DIRECT_ANSWER_GENERATION_POLICY_ID",
    "GENERATION_POLICY_REGISTRY",
    "GenerationPolicy",
    "POLICY_REVISION",
    "REASONING_CONSTRAINT_STRESS_THINKING_POLICY_ID",
    "REASONING_CONSTRAINT_STRESS_QUALIFICATION_THINKING_POLICY_ID",
    "UnknownGenerationPolicyError",
    "resolve_generation_policy",
]
