"""Executable Casbin-ABAC counter-prototype and optional OPA comparator."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import casbin


HERE = Path(__file__).resolve().parent
ACTION = "flow rate adjustment"


@dataclass(frozen=True)
class Resource:
    name: str


@dataclass(frozen=True)
class RequestContext:
    value: float
    limit: float = 16.0


CASES = (
    ("operator-below", "alice", ("PlantOperator",), 15.0, True),
    ("operator-boundary", "alice", ("PlantOperator",), 16.0, False),
    ("admin-below", "admin", ("Admin",), 15.0, True),
    ("admin-boundary", "admin", ("Admin",), 16.0, False),
    ("unknown-user", "mallory", (), 15.0, False),
)


def build_enforcer() -> casbin.Enforcer:
    return casbin.Enforcer(str(HERE / "model.conf"), str(HERE / "policy.csv"))


def casbin_decision(enforcer: casbin.Enforcer, user: str, value: float) -> bool:
    return bool(
        enforcer.enforce(
            user,
            Resource("Pump_B_Power"),
            ACTION,
            RequestContext(value),
        )
    )


def opa_decision(url: str, user: str, roles: tuple[str, ...], value: float) -> bool:
    body = json.dumps(
        {
            "input": {
                "user": {"id": user, "roles": roles},
                "action": ACTION,
                "parameter": "Pump_B_Power",
                "value": value,
                "limits": {"pump_b_power_max_kw": 16.0},
            }
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2.0) as response:
        result = json.loads(response.read().decode("utf-8")).get("result")
    if not isinstance(result, bool):
        raise RuntimeError(f"OPA returned no boolean decision: {result!r}")
    return result


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def benchmark(call, iterations: int) -> dict[str, float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        call()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    return {
        "median_ms": round(statistics.median(samples), 4),
        "p95_ms": round(percentile(samples, 0.95), 4),
        "max_ms": round(max(samples), 4),
    }


def wait_for_opa(url: str, attempts: int = 20, delay: float = 0.25) -> None:
    for attempt in range(1, attempts + 1):
        try:
            opa_decision(url, "alice", ("PlantOperator",), 15.0)
            return
        except (OSError, RuntimeError, urllib.error.URLError):
            if attempt == attempts:
                raise
            time.sleep(delay)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opa-url")
    parser.add_argument("--iterations", type=int, default=1000)
    args = parser.parse_args()
    if args.iterations < 1:
        raise SystemExit("--iterations must be positive")

    enforcer = build_enforcer()
    if args.opa_url:
        wait_for_opa(args.opa_url)
    decisions = []
    for name, user, roles, value, expected in CASES:
        casbin_allowed = casbin_decision(enforcer, user, value)
        if casbin_allowed is not expected:
            raise AssertionError(
                f"{name}: Casbin expected {expected}, got {casbin_allowed}"
            )
        row = {"case": name, "expected": expected, "casbin": casbin_allowed}
        if args.opa_url:
            opa_allowed = opa_decision(args.opa_url, user, roles, value)
            row["opa"] = opa_allowed
            if opa_allowed != casbin_allowed:
                raise AssertionError(
                    f"{name}: decision mismatch Casbin={casbin_allowed} OPA={opa_allowed}"
                )
        decisions.append(row)

    result = {
        "decision_parity": decisions,
        "iterations": args.iterations,
        "casbin": benchmark(
            lambda: casbin_decision(enforcer, "alice", 15.0), args.iterations
        ),
    }
    if args.opa_url:
        result["opa_http"] = benchmark(
            lambda: opa_decision(
                args.opa_url, "alice", ("PlantOperator",), 15.0
            ),
            args.iterations,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
