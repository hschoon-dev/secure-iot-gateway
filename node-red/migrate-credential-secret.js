#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

function keyFor(secret) {
    return crypto.createHash("sha256").update(secret).digest();
}

function decryptCredentials(secret, encrypted) {
    if (!encrypted || Object.keys(encrypted).length !== 1 || typeof encrypted.$ !== "string") {
        throw new Error("input is not a Node-RED encrypted credential object");
    }
    const iv = Buffer.from(encrypted.$.substring(0, 32), "hex");
    const ciphertext = encrypted.$.substring(32);
    const decipher = crypto.createDecipheriv("aes-256-ctr", keyFor(secret), iv);
    return JSON.parse(
        decipher.update(ciphertext, "base64", "utf8") + decipher.final("utf8")
    );
}

function encryptCredentials(secret, credentials) {
    const iv = crypto.randomBytes(16);
    const cipher = crypto.createCipheriv("aes-256-ctr", keyFor(secret), iv);
    return {
        $: iv.toString("hex") +
            cipher.update(JSON.stringify(credentials), "utf8", "base64") +
            cipher.final("base64"),
    };
}

function readJson(filename) {
    return JSON.parse(fs.readFileSync(filename, "utf8"));
}

function writePrivate(filename, value) {
    fs.mkdirSync(path.dirname(filename), {recursive: true, mode: 0o700});
    const temporary = `${filename}.tmp-${process.pid}`;
    fs.writeFileSync(temporary, `${JSON.stringify(value, null, 4)}\n`, {mode: 0o600});
    fs.renameSync(temporary, filename);
    fs.chmodSync(filename, 0o600);
}

function migrate(runtimeConfigFile, inputFile, newSecretFile, outputFile, sanitizedConfigFile) {
    const runtimeConfig = readJson(runtimeConfigFile);
    const oldSecret = runtimeConfig._credentialSecret;
    if (typeof oldSecret !== "string" || oldSecret.length === 0) {
        throw new Error("legacy runtime config has no _credentialSecret");
    }
    const newSecret = fs.readFileSync(newSecretFile, "utf8").trim();
    if (newSecret.length < 32) {
        throw new Error("new credential secret must contain at least 32 characters");
    }

    const cleartext = decryptCredentials(oldSecret, readJson(inputFile));
    const reencrypted = encryptCredentials(newSecret, cleartext);
    if (JSON.stringify(decryptCredentials(newSecret, reencrypted)) !== JSON.stringify(cleartext)) {
        throw new Error("post-migration readback verification failed");
    }
    try {
        const legacyReadback = decryptCredentials(oldSecret, reencrypted);
        if (JSON.stringify(legacyReadback) === JSON.stringify(cleartext)) {
            throw new Error("legacy credential secret still decrypts migrated store");
        }
    } catch (error) {
        if (error.message === "legacy credential secret still decrypts migrated store") {
            throw error;
        }
        // A different AES-CTR key normally produces invalid JSON, which is the
        // expected proof that the legacy key no longer opens the new store.
    }
    writePrivate(outputFile, reencrypted);

    const sanitized = {...runtimeConfig};
    delete sanitized._credentialSecret;
    writePrivate(sanitizedConfigFile, sanitized);
    return cleartext;
}

function main(argv) {
    if (argv.length !== 5) {
        throw new Error(
            "usage: migrate-credential-secret.js RUNTIME_CONFIG INPUT_CREDENTIALS " +
            "NEW_SECRET_FILE OUTPUT_CREDENTIALS SANITIZED_RUNTIME_CONFIG"
        );
    }
    migrate(...argv);
    process.stdout.write("Node-RED credentials migrated and readback-verified.\n");
}

if (require.main === module) {
    try {
        main(process.argv.slice(2));
    } catch (error) {
        process.stderr.write(`ERROR: ${error.message}\n`);
        process.exit(1);
    }
}

module.exports = {decryptCredentials, encryptCredentials, migrate};
