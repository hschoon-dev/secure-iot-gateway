# P1 acceptance contract

This contract separates repository hygiene from cryptographic risk closure.
Deleting Git history is useful hygiene, but it cannot revoke material that has
already been copied. Closure therefore depends on replacing the active trust
and proving that old material no longer authenticates.

## T-02: exposed CA private key

T-02 is closed for the evaluated deployment only when all of the following are
recorded against one immutable commit:

1. a new CA and fresh service identities are generated outside version control;
2. every deployed truststore contains the new trust material and no old CA;
3. every protected service accepts its intended new peer identity;
4. every protected service rejects the corresponding old identity;
5. every mTLS service rejects a valid new-CA certificate issued to the wrong
   gateway component;
6. the full request path succeeds after redeployment; and
7. fingerprints, commands, image identifiers, test cases and exit status are
   stored as a CI evidence artifact linked to the immutable commit and run ID.

The automated acceptance is designed to cover CA replacement, the complete
post-rotation Docker E2E path, five wrong-service identities and the obsolete
formerly intended identity at every protected gRPC server. Each obsolete-peer
negative is bracketed by successful checks with the new intended peer so an
unavailable server cannot be misreported as a trust rejection. A final claim
of production closure must remain scoped to the services and deployment
actually exercised by a successful evidence run.

## T-11: versioned Node-RED credential master key

T-11 is closed only when:

1. a new credential secret is generated outside version control and mounted at runtime;
2. the old and new key fingerprints differ without disclosing either key;
3. the credential store is successfully re-encrypted under the new key;
4. required credentials can be read by the redeployed Node-RED instance;
5. the old key can no longer decrypt the active credential store; and
6. backup, rollback and evidence handling do not reintroduce the old key.

The synthetic CI migration proves items 1–3, 5, and repository-safe evidence
handling without inventing production credentials. Item 4 and revocation of
every downstream credential exposed through the historic store remain an
operational acceptance step on the actual Node-RED deployment. CI runs that set
`SKIP_NODE_RED_ROTATION=true` exercise PKI rotation independently of T-11.
