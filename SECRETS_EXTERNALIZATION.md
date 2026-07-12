# Secrets Externalization

Private keys, credential databases, and generated Node-RED master keys are not
versioned. Each service receives only its own runtime material below
`/run/siot-secrets/<component>`; mutable interface credentials are mounted
separately at `/var/lib/siot`.

## Preparing runtime material

Generate or provision certificates, then run from the repository root:

```bash
./secret_migration.sh
```

The command is non-destructive: it copies available legacy material, creates an
empty TinyDB credential store when necessary, applies restrictive permissions,
and never deletes a source file. Services fail closed when required runtime
material is missing. A reviewed, temporary `ALLOW_LEGACY_SECRETS=true` remains
available only for migration troubleshooting.

## Node-RED master-key migration (T11)

`node-red/settings.js` reads a minimum 32-character key from
`NODE_RED_CREDENTIAL_SECRET_FILE` (default:
`/run/siot-secrets/node-red/credential-secret`). The environment variable
`NODE_RED_CREDENTIAL_SECRET` is a documented fallback, but the file mount is
preferred. Startup fails if neither source exists.

Before deploying this branch over an installation with active Node-RED
credentials, stop Node-RED and back up its data directory. Then migrate the
encrypted credential store while the legacy `.config.runtime.json` still
contains `_credentialSecret`:

```bash
node node-red/migrate-credential-secret.js \
  /backup/node-red/.config.runtime.json \
  /backup/node-red/flows_cred.json \
  /run/siot-secrets/node-red/credential-secret \
  /node-red-data/flows_cred.json \
  /node-red-data/.config.runtime.json
```

The migration decrypts with the legacy generated key, encrypts with the new
external key using Node-RED's AES-256-CTR format, verifies a decrypt/readback,
removes `_credentialSecret` from the output runtime config, and writes outputs
with mode `0600`. It does not mutate the input backup.

CI exercises the same path with synthetic credentials:

```bash
node tests/node-red/test_credential_migration.js
```

The historic key must still be treated as compromised. After verified rollout,
rotate/revoke every real credential that the old Node-RED store could decrypt;
that operational revocation cannot be automated from this repository.

## Shared examples and production guard

The repository shares only `.env.example` and generators for ephemeral test
identities. It never shares a reusable private key or a production password.
`tests/ci/prepare_test_secrets.sh` marks its output with
`.runtime-secrets/.siot-test-only`. Before a production start, run:

```bash
SIOT_DEPLOYMENT_MODE=production ./validate-deployment-secrets.sh
```

The preflight fails if the runtime tree carries the test marker or if a required
password contains a known CI/example token. Test execution must opt in with
`SIOT_DEPLOYMENT_MODE=test` and requires the marker. This makes test material
easy to reproduce without making it silently reusable in production.

## Evidence gates and risk scores

`security/risk-gates.json` maps threat IDs to the CI job classes that provide
technical evidence. The final CI job writes a commit-bound JSON/Markdown report.
A green gate does **not** modify an ordinal risk score: it proves only the stated
technical invariant. Any residual-score change still requires a documented human
review of scope, deployment transfer, and operational prerequisites.
