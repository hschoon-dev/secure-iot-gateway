# Casbin-ABAC-Gegenprototyp

This executable counter-prototype models the same `Pump_B_Power < 16` rule as
the OPA spike. Casbin keeps subject/resource/action policy in `policy.csv` and
evaluates the numeric request context through ABAC attributes in `model.conf`.

Run the reproducible Casbin/OPA parity comparison (the script starts the pinned
OPA image and fails on any decision mismatch):

```sh
tests/evaluation/run_casbin_opa_comparison.sh
```

The underlying `compare.py` also accepts `--opa-url` for a manually managed OPA
endpoint. The process fails on an unexpected decision or any Casbin/OPA
mismatch. Reported times are process-local Casbin enforcement versus OPA over
HTTP and therefore measure the deployment paths, not only policy-engine
execution.

## Recorded comparison

`comparison-result.json` records the reproducible sprint run with 1,000
iterations. All five decisions matched. In this Docker Desktop run, Casbin's
median in-process enforcement was `0.0380 ms`; OPA's median HTTP path was
`2.6410 ms`. This is an architectural path comparison, not a claim about the
engines' isolated execution speed.
