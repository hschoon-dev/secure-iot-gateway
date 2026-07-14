"""Negative probes for the production OPA HTTPS/mTLS endpoint."""

from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request


def context(ca: str, cert: str | None = None, key: str | None = None) -> ssl.SSLContext:
    tls = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca)
    tls.minimum_version = ssl.TLSVersion.TLSv1_3
    if cert and key:
        tls.load_cert_chain(certfile=cert, keyfile=key)
    return tls


def request(url: str, tls: ssl.SSLContext) -> int:
    body = json.dumps({"input": {}}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5, context=tls) as response:
        response.read()
        return response.status


def expect_missing_client_rejected(url: str, ca: str) -> None:
    try:
        request(url, context(ca))
    except (ssl.SSLError, urllib.error.URLError, ConnectionError):
        print("PASS opa-mtls: caller without client certificate rejected")
        return
    raise AssertionError("OPA accepted a caller without a client certificate")


def expect_identity_denied(url: str, ca: str, cert: str, key: str) -> None:
    try:
        request(url, context(ca, cert, key))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            print(f"PASS opa-authz: service-foreign identity denied ({exc.code})")
            return
        raise
    raise AssertionError("OPA accepted a valid but unauthorized gateway identity")


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    if mode == "missing-client":
        expect_missing_client_rejected(*args)
    elif mode == "foreign-identity":
        expect_identity_denied(*args)
    else:
        raise SystemExit(
            "usage: opa_mtls_probe.py missing-client URL CA | "
            "foreign-identity URL CA CERT KEY"
        )
