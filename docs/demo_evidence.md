# Demo Evidence Fixtures

Runner carries a small synthetic TinyLlama quant-ladder fixture for report and contract tests.

The fixture is intentionally labeled:

- `source_bundle_origin: infergrade_demo_fixture`
- `derived.demo_evidence: true`
- simulated execution
- informational-only comparison grade

It exists to exercise the same result/report shape a real multi-quant run would produce. It is not benchmark truth and must not be presented as real uploaded evidence.

## Current Fixture

- Family: TinyLlama
- Checkpoint: `TinyLlama-1.1B-Chat-v1.0`
- Quants: Q4_K_M, Q5_K_M, Q8_0
- Benchmark scope: decision suite
- Check: `interactive_chat_v1`
- Hardware lane: 24 GB demo workstation

## Why No Real Ladder Is Committed Yet

Sprint 34 prefers at least one real local canonical ladder when practical. We are not committing one yet because the repo does not currently have a reviewed, reproducible, multi-quant local run bundle with provenance good enough to treat as a canonical example.

Until that exists, demo fixtures are safer: they make report and compare behavior testable while remaining visibly synthetic.
