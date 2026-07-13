# PikeOS/ELinOS transfer acceptance

This contract transfers the Docker/hosted-runner security claims to the target deployment
without treating container evidence as proof of partition isolation. Record every result against
one immutable gateway commit and one immutable PikeOS/ELinOS image set.

## Required identifiers

- gateway commit and dirty-state check;
- PikeOS, ELinOS and integration-project versions;
- hashes of deployed partition images;
- device/board identifier and network-topology revision;
- UTC start/end time and operator/reviewer identities.

Never archive private keys, passwords or decrypted Node-RED credentials. Evidence may contain
certificate fingerprints, public certificates, image hashes, commands, exit codes and redacted
service logs.

## T-02 and T-07: trust replacement and peer identity

1. Generate a new CA and all workload identities outside Git.
2. Deploy the new trust material to every protected partition and record public fingerprints.
3. Prove the intended new peer at each protected gRPC service.
4. Present a valid new-CA identity belonging to a different service; expect authorization denial.
5. Present the formerly intended identity from the retired CA; expect TLS rejection.
6. Bracket every negative probe with a successful new-peer probe so an unavailable service cannot
   be mistaken for rejection.
7. Verify the configured OPA endpoint uses HTTPS in production and validate its server identity;
   plain HTTP must fail closed.

## T-08: partition secret scope

For each deployed partition, enumerate the runtime-visible secret root without printing file
contents. The partition must see only its own component subtree. Attempted writes must fail.
Repeat after restart and image rollback. Host or hypervisor access is outside this claim and must
be assessed separately.

## T-11: real Node-RED store

1. Create an encrypted, access-controlled backup and document its retention owner.
2. Generate a new `_credentialSecret` outside Git and record only old/new fingerprints.
3. Run `node-red/migrate-credential-secret.js` into a staging output, never directly over the only
   active copy.
4. Deploy the migrated store and prove required credentials can be read by the real Node-RED
   runtime.
5. Prove the retired key cannot decrypt the active store.
6. Rotate or revoke every downstream credential that the historic store exposed and record the
   target-system confirmation, not the secret value.
7. Verify rollback and backup paths cannot reactivate the retired key or credentials.

## T-12: insecure OPC UA endpoint

Start the ordinary and production deployments and prove that port 4841 is closed. An insecure
server may be started only in a separately labelled test deployment with both
`SIOT_DEPLOYMENT_MODE=test` and `ENABLE_INSECURE_OPCUA_TEST_SERVER=true`. Production must reject
that combination before serving traffic.

## End-to-end and evidence bundle

After all changes, execute the intended OPC-UA → authorization → VoR/CPC → process/readback path.
The evidence bundle must contain the identifiers above, a check/result table, redacted logs,
fingerprints, commands and exit codes, plus independent reviewer sign-off. A failed or skipped
check leaves the corresponding transfer claim open; Compose evidence remains valid only for its
original scope.
