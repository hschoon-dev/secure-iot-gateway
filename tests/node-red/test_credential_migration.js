"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const {
    decryptCredentials,
    encryptCredentials,
    migrate,
} = require("../../node-red/migrate-credential-secret.js");

const directory = fs.mkdtempSync(path.join(os.tmpdir(), "siot-node-red-migration-"));
try {
    const oldSecret = "legacy-system-generated-secret-for-test-only";
    const newSecret = "new-external-runtime-secret-for-test-only-2026";
    const fixture = {
        "opcua-client-node": {username: "synthetic-user", password: "synthetic-password"},
    };
    const runtimeConfig = path.join(directory, ".config.runtime.json");
    const input = path.join(directory, "flows_cred.json");
    const secretFile = path.join(directory, "credential-secret");
    const output = path.join(directory, "migrated", "flows_cred.json");
    const sanitized = path.join(directory, "migrated", ".config.runtime.json");

    fs.writeFileSync(runtimeConfig, JSON.stringify({_credentialSecret: oldSecret}));
    fs.writeFileSync(input, JSON.stringify(encryptCredentials(oldSecret, fixture)));
    fs.writeFileSync(secretFile, `${newSecret}\n`, {mode: 0o600});

    migrate(runtimeConfig, input, secretFile, output, sanitized);
    assert.deepStrictEqual(decryptCredentials(newSecret, JSON.parse(fs.readFileSync(output))), fixture);
    assert.throws(() => decryptCredentials(oldSecret, JSON.parse(fs.readFileSync(output))));
    assert.strictEqual(JSON.parse(fs.readFileSync(sanitized))._credentialSecret, undefined);
    assert.notStrictEqual(JSON.parse(fs.readFileSync(output)).$, JSON.parse(fs.readFileSync(input)).$);
    assert.strictEqual(fs.statSync(output).mode & 0o777, 0o600);
    process.stdout.write("PASS Node-RED synthetic decrypt/re-encrypt/readback migration\n");
} finally {
    fs.rmSync(directory, {recursive: true, force: true});
}
