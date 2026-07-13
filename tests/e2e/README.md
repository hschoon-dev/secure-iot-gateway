# End-to-End-Test-Harness

The harness creates a fresh credential database, builds the Compose stack,
runs a finite OPC UA client, and removes all containers afterwards. Runtime
credentials stay below the ignored `.e2e-runtime` directory.

```sh
ADMIN_PASSWORD='CiOnlyPasswordWith32Characters123' tests/e2e/run.sh
```

The test first proves that each participating component can see only its own
secret subtree. It then presents five CA-valid client certificates to services
for which those identities are not authorized; every call must reach TLS and
fail with gRPC `PERMISSION_DENIED`. Finally, all four deterministic request
cases must pass:

Before the gRPC identity probes, the harness also verifies the production OPA
transport: TLS 1.3 and a client certificate are mandatory, and the fail-closed
`system.authz` policy denies a valid CPC certificate because only the Interface
identity may call the gateway decision path.

The CPC legacy Flask bridge is disabled by default and port 5000 is checked as
closed. Both the synchronous evaluation path and the default MariaDB consumer
use the typed CPC gRPC/mTLS service.

- Casbin and OPA allow `Pump_B_Power=9`; both downstream mTLS hops complete
  and the CPC confirms the write by reading the endpoint back.
- OPA denies the exclusive upper boundary `Pump_B_Power=16`.
- malformed numeric input is denied before OPA.
- invalid credentials are denied before authorization.

On failure, the harness prints the last 120 log lines for every service before
cleaning up.

`tests/rotation/run_isolated.sh` reuses the same suite after generating a new
CA. It additionally brackets each obsolete-client negative check with the new
intended identity, proving that a TLS timeout represents rejection of old
trust rather than an unavailable service.

`tests/mariadb/run.sh` separately builds and verifies the default asynchronous
MariaDB pipeline through the final Modbus readback and checks the two database
accounts with positive and negative least-privilege operations.
