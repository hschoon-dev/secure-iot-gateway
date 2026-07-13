"""Submit one deterministic request through the default MariaDB pipeline."""

from __future__ import annotations

import asyncio
import os
import sys

from e2e_runner import _arguments, _assert_secret_scope, _submit
from main import setup_client


async def run() -> None:
    password = os.environ.get("ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("ADMIN_PASSWORD is required")

    _assert_secret_scope()
    client = await setup_client(max_retries=12, retry_delay=2)
    try:
        notification = await _submit(client, _arguments(password, "9"))
        if "Submission received" not in notification:
            raise AssertionError(f"unexpected submission response: {notification!r}")
        print(f"PASS mariadb-submit: {notification}", flush=True)
    finally:
        await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except Exception as exc:
        print(f"FAIL MariaDB E2E: {exc}", file=sys.stderr, flush=True)
        raise
