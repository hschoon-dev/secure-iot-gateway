# Typed gRPC/mTLS request pipeline

The deployed request path no longer uses the shared
`vor-database/mapped_requests.json` hand-off or the CPC Flask bridge.

```text
OPC UA client
  -> Interface (authentication, Casbin, OPA)
  -> Intermediate VoR :50051 (request verification and mapping, mTLS)
  -> VoR CPC processor :50052 (acceptance and mapping constraints, mTLS)
  -> CPC :50053 (typed read/apply and verified readback, mTLS)
```

The three internal services use generated protobuf messages. Both new server
ports require a client certificate signed by the active gateway CA. A request
is acknowledged at the OPC UA boundary only after the CPC write has succeeded
and its readback matches. Transport, acceptance, constraint, or write failures
propagate back as a failed submission.

Each identity is externalized under only its owning component:

- `intermediate-vor-partition`: processing client key
- `intermediate-vor-partition-cpc`: processing server and CPC client keys
- `cpc-partition`: CPC pipeline server key

`tests/e2e/run.sh` builds the complete stack, proves the component scopes, and
executes the positive write/readback plus authentication and authorization
denial cases.
