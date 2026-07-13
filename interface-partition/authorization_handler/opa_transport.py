"""Fail-closed transport policy for requests to an external OPA PDP."""

from __future__ import annotations

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
