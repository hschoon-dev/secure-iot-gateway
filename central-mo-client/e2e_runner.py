"""Deterministic OPC UA end-to-end checks for the gateway entry point."""

from __future__ import annotations

import asyncio
import datetime
import os
import sys
from pathlib import Path

from asyncua import ua

from main import setup_client


def _assert_secret_scope() -> None:
    root = Path(os.environ.get("SIOT_SECRETS_ROOT", "/run/siot-secrets"))
    visible = sorted(path.name for path in root.iterdir())
    if visible != ["central-mo-client"]:
        raise AssertionError(
            f"secret scope violation: expected only central-mo-client, got {visible}"
        )
    print("PASS secret-scope: central-mo-client only", flush=True)


def _arguments(password: str, modification: str, *, valid_credentials: bool = True):
    return [
        ua.Variant("admin", ua.VariantType.String),
        ua.Variant(password if valid_credentials else "invalid-password", ua.VariantType.String),
        ua.Variant(["e2e"], ua.VariantType.String, [0]),
        ua.Variant(datetime.datetime.now(datetime.timezone.utc), ua.VariantType.DateTime),
        ua.Variant(["deterministic end-to-end request"], ua.VariantType.String, [0]),
        ua.Variant("flow rate adjustment", ua.VariantType.String),
        ua.Variant("Pump_B_Power", ua.VariantType.String),
        ua.Variant(modification, ua.VariantType.String),
        ua.Variant(1, ua.VariantType.Int32),
    ]


async def _submit(client, arguments):
    handler = await client.nodes.objects.get_child(["2:RequestHandler"])
    result = await handler.call_method("2:request", *arguments)
    if not isinstance(result, list) or len(result) != 3:
        raise AssertionError(f"unexpected method response: {result!r}")
    return result[2]


async def run() -> None:
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("ADMIN_PASSWORD is required")

    scenario = os.environ.get("E2E_SCENARIO", "full").strip().lower()
    _assert_secret_scope()
    client = await setup_client(max_retries=12, retry_delay=2)
    try:
        if scenario == "full":
            cases = (
                # 9 satisfies the complete mapping ruleset (including < 12 and < 16).
                ("allowed", _arguments(password, "9"), "Submission received"),
                ("opa-boundary-deny", _arguments(password, "16"), "authorization failed (opa)"),
                ("malformed-deny", _arguments(password, "not-a-number"), "Invalid input for modification."),
                (
                    "authentication-deny",
                    _arguments(password, "15", valid_credentials=False),
                    "Authentication failed",
                ),
            )
        elif scenario == "opa-outage":
            cases = (
                (
                    "opa-outage-fail-closed",
                    _arguments(password, "9"),
                    "authorization failed (opa)",
                ),
            )
        else:
            raise ValueError(f"unknown E2E_SCENARIO: {scenario}")
        for name, arguments, expected in cases:
            notification = await _submit(client, arguments)
            if expected not in notification:
                raise AssertionError(
                    f"{name}: expected {expected!r}, got {notification!r}"
                )
            print(f"PASS {name}: {notification}", flush=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:
        print(f"FAIL e2e: {exc}", file=sys.stderr, flush=True)
        raise
