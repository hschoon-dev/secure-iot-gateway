"""Fail-closed transport policy for requests to an external OPA PDP."""

from __future__ import annotations

import ssl
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse


def opa_transport_allowed(url: str, deployment_mode: str) -> tuple[bool, str]:
    """Return whether an OPA endpoint is acceptable for this deployment mode.

    HTTP remains usable in the explicitly labelled test environment so the
    hermetic Compose E2E remains reproducible. Any production OPA enforcement
    requires an HTTPS endpoint; otherwise the request is denied rather than
    silently sending authorization input over an unprotected channel.
    """

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False, "OPA_URL must be an absolute HTTP(S) URL"
    if deployment_mode.strip().lower() == "production" and parsed.scheme != "https":
        return False, "production OPA enforcement requires an HTTPS OPA_URL"
    return True, "OPA transport accepted"


@lru_cache(maxsize=4)
def build_opa_ssl_context(
    url: str,
    deployment_mode: str,
    ca_cert: str,
    client_cert: str,
    client_key: str,
) -> ssl.SSLContext | None:
    """Build a mutually authenticated TLS context for an HTTPS OPA endpoint.

    Plain HTTP is retained only for explicitly labelled test-only callers.
    HTTPS never falls back to the host trust store or to unauthenticated TLS:
    all three component-scoped certificate paths are mandatory.
    """

    allowed, reason = opa_transport_allowed(url, deployment_mode)
    if not allowed:
        raise ValueError(reason)

    if urlparse(url).scheme == "http":
        return None

    material = {
        "OPA_TLS_CA_CERT": ca_cert,
        "OPA_TLS_CLIENT_CERT": client_cert,
        "OPA_TLS_CLIENT_KEY": client_key,
    }
    for label, raw_path in material.items():
        if not raw_path or not Path(raw_path).is_file():
            raise ValueError(f"{label} must reference a readable file for HTTPS OPA")

    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca_cert)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.check_hostname = True
    context.load_cert_chain(certfile=client_cert, keyfile=client_key)
    return context
