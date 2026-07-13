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

## Local initial setup and staged activation

For a local deployment, create a unique, Git-ignored `.env` file first:

```bash
./setup-local-secrets.sh
```

The script writes the four Compose passwords with mode `0600`; Docker Compose
loads `.env` automatically. It refuses to overwrite an existing file unless
`--force` is supplied. Passwords are deliberately kept out of the repository,
but an `.env` file is still appropriate only for a protected local machine. A
production deployment should inject its values from its deployment secret
manager instead.

A fresh checkout has no private keys. To also generate fresh local
certificates, externalize them into a staged tree and activate it only after it
is complete:

```bash
./setup-local-secrets.sh --generate-runtime
```

`rotate-secrets.sh` follows the same two-step activation: it builds complete
runtime secrets under `.secret-staging/` and swaps both runtime directories by
rename. The preceding active trees remain beneath the timestamped
`.secrets-backup/` entry. This is a local, cutover-style rotation; it does not
implement a multi-host CA overlap rollout or certificate revocation.

After every service has been deployed with the new trust material and old
identities have been negatively tested, a backup may be removed explicitly:

```bash
./retire-old-secrets.sh --backup 20260713-120000 \
  --confirm 20260713-120000 --delete
```

Without both the matching confirmation value and `--delete`, the retirement
script performs a dry run. It never removes active runtime material.

### Script reference

| Script | Typical command | Effect and rollback |
| --- | --- | --- |
| `setup-local-secrets.sh` | `./setup-local-secrets.sh [--env-file PATH] [--force]` | Writes a mode-`0600` local Compose env file. It does not overwrite one without `--force`; restore a prior `.env` from its own backup if necessary. |
| `setup-local-secrets.sh` | `./setup-local-secrets.sh --generate-runtime` | Creates the `.env`, then rotates and activates fresh local runtime identities. A missing Node-RED runtime config is treated as an optional Node-RED deployment; an existing credential store still blocks unsafe key-only rotation. |
| `stage-runtime-secrets.sh` | `./stage-runtime-secrets.sh --stage-dir /secure/stage-20260713` | Creates `runtime-secrets/` and `runtime-data/` below a new stage directory. It never touches the active directories and removes a partial stage on failure. |
| `activate-runtime-secrets.sh` | `./activate-runtime-secrets.sh --stage-dir /secure/stage-20260713 [--backup-dir PATH]` | Moves a complete staged tree into the active runtime paths and moves the preceding paths into the backup. Keep stage and active paths on the same filesystem so each directory rename is atomic. |
| `rotate-secrets.sh` | `./rotate-secrets.sh` | Backs up source and active runtime material, generates a new CA and service identities, stages the result, then activates it. This is a local cutover, not a distributed CA-overlap deployment. |
| `retire-old-secrets.sh` | `./retire-old-secrets.sh --backup TS --confirm TS --delete` | Deletes only the timestamped backup after explicit matching confirmation. Without both flags, it is a dry run; it never removes active runtime paths. |

### Recommended local sequence

```bash
# One-time local setup. Docker Compose automatically loads .env afterwards.
./setup-local-secrets.sh --generate-runtime
SIOT_DEPLOYMENT_MODE=production ./validate-deployment-secrets.sh
docker compose up --build

# Later, after a planned cutover and service validation.
./rotate-secrets.sh
SIOT_DEPLOYMENT_MODE=production ./validate-deployment-secrets.sh
docker compose up --build -d

# Only after new identities work and old ones are rejected.
./retire-old-secrets.sh --backup 20260713-120000 \
  --confirm 20260713-120000 --delete
```

For multiple hosts, deploy a truststore containing both old and new trust
anchors first, migrate clients and servers in phases, and retire old material
only after every peer has switched. The local scripts deliberately do not
claim to implement that distributed rollover.

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
