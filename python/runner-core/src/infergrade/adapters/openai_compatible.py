"""Observed-runtime adapter for already-running local OpenAI-compatible servers."""

from typing import Any, Dict, Optional

from infergrade.adapters.base import BaseAdapter
from infergrade.models import RunRequest
from infergrade.observed_runtime import (
    OBSERVED_RUNTIME_CONTRACT_VERSION,
    OpenAICompatibleClient,
    ObservedRuntimeError,
    ObservedRuntimeProbe,
)


class OpenAICompatibleAdapter(BaseAdapter):
    """Use a loopback OpenAI-compatible endpoint without verified claims.

    The adapter is intentionally not registered as the existing ``llama.cpp``
    backend.  Callers that opt into the observed lane construct it explicitly,
    then pass generated text into the normal Runner benchmark/scoring path.
    """

    backend_name = "openai-compatible-observed"

    def __init__(
        self,
        endpoint: Optional[str] = None,
        provider_hint: Optional[str] = None,
        model_id: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout_seconds: float = 2.0,
        generation_timeout_seconds: float = 300.0,
        max_response_bytes: int = 512 * 1024,
        client: Optional[OpenAICompatibleClient] = None,
    ):
        if client is not None and endpoint is not None:
            raise ValueError("provide either client or endpoint")
        self.client = client or OpenAICompatibleClient(
            endpoint,
            provider_hint=provider_hint,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            generation_timeout_seconds=generation_timeout_seconds,
            max_response_bytes=max_response_bytes,
        )
        self.model_id = model_id.strip() if isinstance(model_id, str) and model_id.strip() else None

    def probe(self) -> ObservedRuntimeProbe:
        return self.client.probe()

    def _probe_or_raise(self) -> ObservedRuntimeProbe:
        return self.client.last_probe or self.probe()

    def _failure_receipt(
        self,
        error: ObservedRuntimeError,
        selected_model_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        probe = self.client.last_probe
        if probe is None:
            probe = ObservedRuntimeProbe(
                endpoint=self.client.endpoint,
                provider=self.client.provider_hint or "unknown",
                model_ids=[],
                model_endpoint_status="unavailable",
                failure_code=error.code,
                generation_profile=self.client.last_generation_profile or {},
            )
        else:
            # Do not mutate a prior successful probe into a failure receipt.
            # Copy its reported IDs and make the failed chat status explicit.
            chat_endpoint_status = (
                "unavailable" if self.client.last_generation_profile is not None else "not_probed"
            )
            probe = ObservedRuntimeProbe(
                endpoint=probe.endpoint,
                provider=probe.provider,
                model_ids=list(probe.model_ids),
                model_endpoint_status=probe.model_endpoint_status,
                chat_endpoint_status=chat_endpoint_status,
                failure_code=error.code,
                generation_profile=self.client.last_generation_profile or {},
            )
        return probe.to_receipt(selected_model_id=selected_model_id)

    def _selected_model_id(self, request: Optional[RunRequest], probe: ObservedRuntimeProbe) -> Optional[str]:
        if self.model_id:
            return self.model_id if self.model_id in probe.model_ids else None
        # A request model is only safe to use when the endpoint reported that
        # exact ID.  A single reported model can be selected implicitly; an
        # ambiguous list requires an explicit adapter model ID.
        requested = getattr(request, "model", None) if request is not None else None
        if requested and requested in probe.model_ids:
            return requested
        return probe.model_ids[0] if len(probe.model_ids) == 1 else None

    def runtime_metadata(self, request: RunRequest) -> Dict[str, object]:
        probe = self._probe_or_raise()
        return {
            "observed_runtime_contract": OBSERVED_RUNTIME_CONTRACT_VERSION,
            "evidence_kind": "observed_runtime",
            "evidence_lane": "observed",
            "provider": probe.provider,
            "endpoint_network_scope": "loopback",
            "model_identity_status": "reported_only",
            "artifact_identity_status": "unknown",
            "runtime_identity_status": "unknown",
            "verified": False,
        }

    def observed_runtime_receipt(self, request: Optional[RunRequest] = None) -> Dict[str, Any]:
        probe = self._probe_or_raise()
        selected = self._selected_model_id(request, probe)
        return probe.to_receipt(selected_model_id=selected)

    def resolve_version(self, simulate: bool = True, request: RunRequest = None) -> str:
        if simulate:
            return "simulated-openai-compatible-observed"
        # This is the adapter contract version, not an inferred server build
        # version.  The observed lane must never promote a banner string to a
        # verified runtime identity.
        self._probe_or_raise()
        return OBSERVED_RUNTIME_CONTRACT_VERSION

    def preflight_model(self, request: RunRequest) -> None:
        probe = self._probe_or_raise()
        if self.model_id and self.model_id not in probe.model_ids:
            raise ObservedRuntimeError("model_not_available")
        if not self.model_id and not self._selected_model_id(request, probe):
            raise ObservedRuntimeError("model_not_available")

    def generate_text(self, request: RunRequest, prompt: str, max_tokens: int) -> Dict[str, object]:
        if request.simulate:
            return super().generate_text(request, prompt, max_tokens)
        self.client.reset_generation_profile()
        selected_model_id = None
        try:
            probe = self._probe_or_raise()
            selected_model_id = self._selected_model_id(request, probe)
            if not selected_model_id:
                raise ObservedRuntimeError("model_not_available")
            text = self.client.complete(selected_model_id, prompt, max_tokens, stream=False)
            if self.client.last_probe is not None:
                self.client.last_probe.chat_endpoint_status = "compatible"
            return {
                "text": text,
                "status": "completed",
                "error": None,
                "observed_runtime": self.observed_runtime_receipt(request),
            }
        except ObservedRuntimeError as exc:
            receipt = self._failure_receipt(exc, selected_model_id=selected_model_id)
            return {
                "text": "",
                "status": "failed",
                "error": exc.code,
                "observed_runtime": receipt,
            }

    def generate_text_streaming(
        self,
        request: RunRequest,
        prompt: str,
        max_tokens: int,
    ) -> Dict[str, object]:
        """Exercise the same seam with SSE while keeping receipt semantics."""
        if request.simulate:
            return super().generate_text(request, prompt, max_tokens)
        self.client.reset_generation_profile()
        selected_model_id = None
        try:
            probe = self._probe_or_raise()
            selected_model_id = self._selected_model_id(request, probe)
            if not selected_model_id:
                raise ObservedRuntimeError("model_not_available")
            text = self.client.complete(selected_model_id, prompt, max_tokens, stream=True)
            if self.client.last_probe is not None:
                self.client.last_probe.chat_endpoint_status = "compatible"
            return {
                "text": text,
                "status": "completed",
                "error": None,
                "observed_runtime": self.observed_runtime_receipt(request),
            }
        except ObservedRuntimeError as exc:
            receipt = self._failure_receipt(exc, selected_model_id=selected_model_id)
            return {
                "text": "",
                "status": "failed",
                "error": exc.code,
                "observed_runtime": receipt,
            }


ObservedRuntimeAdapter = OpenAICompatibleAdapter


__all__ = ["OpenAICompatibleAdapter", "ObservedRuntimeAdapter"]
