"""Deployment-mode guards for the brownfield OPC UA test services."""

from __future__ import annotations

import os
from collections.abc import Mapping


_TRUE_VALUES = {"1", "true", "yes", "on"}


def insecure_opcua_test_server_enabled(
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Allow the NoSecurity server only after an explicit test-mode opt-in.

    Keeping the implementation is useful for isolated compatibility tests, but
    a production deployment must not be able to expose it accidentally.
    """

    env = os.environ if environment is None else environment
    enabled = env.get("ENABLE_INSECURE_OPCUA_TEST_SERVER", "false").strip().lower()
    if enabled not in _TRUE_VALUES:
        return False

    mode = env.get("SIOT_DEPLOYMENT_MODE", "production").strip().lower()
    if mode != "test":
        raise RuntimeError(
            "ENABLE_INSECURE_OPCUA_TEST_SERVER=true is permitted only when "
            "SIOT_DEPLOYMENT_MODE=test."
        )
    return True
