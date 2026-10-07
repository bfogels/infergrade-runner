# Item timing placement upload binding — 2026-10-07

Contract 0.3.41 carries the existing bounded PR647 invocation receipt with each
capability task-performance payload. Individual timing observations reference
their own invocation and content fingerprint. Strict closed-schema validation,
digest recomputation, conflicting-ID exclusion and bounded tables preserve
unknown placement rather than borrowing another invocation.

Local validation: `./scripts/test_all.sh` passed 1174 unittest tests, tier audit
and product acceptance checks. Focused placement tests cover restarted servers,
invalid/path-bearing content, conflicting IDs, truncation and summary rollups.
Independent review found no blockers. Source export succeeded to
`dist/contracts/0.3.41`; this does not update a signed desktop release.

Hub import, cohort qualification, hosted deployment and physical GPU/native-app
acceptance are separate delivery steps. No model execution was added or claimed
by these local contract tests.
