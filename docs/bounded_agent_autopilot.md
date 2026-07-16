# Bounded benchmark-agent autopilot

InferGrade can execute a Hub-issued benchmark-agent grant without asking the
owner to enqueue each run manually. The owner still creates the grant and pairs
the Runner; the Runner cannot widen the model, artifact, task, job-count,
download, machine, expiry, or local-only policy.

After pairing an `agent_dogfood` Runner with a demand-queue grant, run:

```bash
infergrade start --autopilot --execution-mode local_native
```

The command repeatedly:

1. reads the private bounded work plan;
2. prints the exact model, quant, task, and download size chosen by Hub;
3. materializes that immutable candidate with an idempotency key;
4. claims only the returned run ID through the existing worker path;
5. executes, uploads, and completes the run; and
6. exits when the grant has no eligible candidates or its local `--max-jobs`
   cap is reached.

Transient Hub storage contention is retried with the same idempotency key, so a
retry cannot double-charge the grant or create a second run. The Hub grant is
still the authority: `--max-jobs` may narrow work locally but cannot expand it.

Autopilot is local-native only. It does not issue pairing codes, change result
visibility, grant direct publication authority, rent hardware, or select an
artifact outside the Hub's reviewed immutable candidate list. A revoked or
expired runner token stops the command and requires re-pairing.
