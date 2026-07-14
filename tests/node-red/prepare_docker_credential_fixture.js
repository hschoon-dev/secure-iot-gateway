"use strict";

/* Build a disposable Node-RED data directory for the Docker acceptance test.
 * All credentials are synthetic and stay in the test temporary directory. */

const fs = require("fs");
const path = require("path");
const {
    encryptCredentials,
    migrate,
} = require("../../node-red/migrate-credential-secret.js");

const [targetDirectory] = process.argv.slice(2);
if (!targetDirectory) {
    throw new Error("usage: prepare_docker_credential_fixture.js TARGET_DIRECTORY");
}

const root = path.resolve(__dirname, "..", "..");
const legacySecret = "test-only-legacy-node-red-secret-2026";
const runtimeSecret = "test-only-runtime-node-red-secret-2026";
const probeNodeId = "credential-probe-node";
const dataDirectory = path.join(targetDirectory, "data");
const secretDirectory = path.join(targetDirectory, "secrets");
const sourceDirectory = path.join(targetDirectory, "legacy");

fs.mkdirSync(dataDirectory, {recursive: true, mode: 0o755});
fs.mkdirSync(secretDirectory, {recursive: true, mode: 0o755});
fs.mkdirSync(sourceDirectory, {recursive: true, mode: 0o755});
const probeModuleDirectory = path.join(
    dataDirectory,
    "node_modules",
    "node-red-contrib-credential-probe",
);
fs.mkdirSync(probeModuleDirectory, {recursive: true, mode: 0o755});

const legacyConfig = path.join(sourceDirectory, ".config.runtime.json");
const legacyStore = path.join(sourceDirectory, "flows_cred.json");
const runtimeSecretFile = path.join(secretDirectory, "credential-secret");
const migratedStore = path.join(dataDirectory, "flows_cred.json");
const sanitizedConfig = path.join(dataDirectory, ".config.runtime.json");

fs.writeFileSync(legacyConfig, JSON.stringify({_credentialSecret: legacySecret}), {mode: 0o600});
fs.writeFileSync(
    legacyStore,
    JSON.stringify(encryptCredentials(legacySecret, {[probeNodeId]: {password: "synthetic"}})),
    {mode: 0o600},
);
fs.writeFileSync(runtimeSecretFile, `${runtimeSecret}\n`, {mode: 0o600});

migrate(legacyConfig, legacyStore, runtimeSecretFile, migratedStore, sanitizedConfig);

const migratedConfig = JSON.parse(fs.readFileSync(sanitizedConfig, "utf8"));
if (Object.hasOwn(migratedConfig, "_credentialSecret")) {
    throw new Error("migration left the legacy credential secret in the runtime config");
}

fs.copyFileSync(path.join(root, "node-red", "settings.js"), path.join(dataDirectory, "settings-base.js"));
fs.writeFileSync(
    path.join(dataDirectory, "settings.js"),
    [
        'const settings = require("./settings-base.js");',
        'settings.flowFile = "flows.json";',
        "module.exports = settings;",
        "",
    ].join("\n"),
    {mode: 0o644},
);

fs.writeFileSync(
    path.join(probeModuleDirectory, "credential-probe.js"),
    [
        "module.exports = function(RED) {",
        "  function CredentialProbe(config) {",
        "    RED.nodes.createNode(this, config);",
        "    this.on('input', function(msg, send, done) {",
        "      msg.payload = this.credentials && this.credentials.password ? 'credential-loaded' : 'credential-missing';",
        "      send(msg);",
        "      done();",
        "    });",
        "  }",
        "  RED.nodes.registerType('credential-probe', CredentialProbe, {",
        "    credentials: {password: {type: 'password'}},",
        "  });",
        "};",
        "",
    ].join("\n"),
    {mode: 0o644},
);
fs.writeFileSync(
    path.join(probeModuleDirectory, "package.json"),
    JSON.stringify({
        name: "node-red-contrib-credential-probe",
        version: "1.0.0",
        "node-red": {nodes: {"credential-probe": "credential-probe.js"}},
    }),
    {mode: 0o644},
);

fs.writeFileSync(
    path.join(dataDirectory, "flows.json"),
    JSON.stringify([
        {id: "tab", type: "tab", label: "credential acceptance"},
        {id: "http-in", type: "http in", z: "tab", method: "get", url: "/credential-probe", wires: [[probeNodeId]]},
        {id: probeNodeId, type: "credential-probe", z: "tab", wires: [["http-response"]]},
        {id: "http-response", type: "http response", z: "tab", wires: []},
    ]),
    {mode: 0o644},
);

// The fixture is synthetic; relaxed read permissions let the unprivileged
// node-red image read host-mounted test files. Production secrets stay 0600.
for (const file of [migratedStore, sanitizedConfig, runtimeSecretFile]) {
    fs.chmodSync(file, 0o644);
}
fs.chmodSync(dataDirectory, 0o777);
