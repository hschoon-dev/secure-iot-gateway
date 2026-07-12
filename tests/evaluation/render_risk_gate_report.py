#!/usr/bin/env python3
"""Render a commit-bound risk-gate report from completed CI job classes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTER = ROOT / "security" / "risk-gates.json"


def render(regression_result: str, docker_result: str, commit: str) -> dict:
    job_results = {
        "regression-and-policy": regression_result,
        "docker-e2e-and-rotation": docker_result,
    }
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    threats = []
    for threat in register["threats"]:
        passed = all(job_results.get(job) == "success" for job in threat["required_jobs"])
        threats.append({**threat, "gates_passed": passed})
    return {
        "commit": commit,
        "job_results": job_results,
        "ordinal_scores_automatically_changed": False,
        "human_review_required": True,
        "policy": register["policy"],
        "threats": threats,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--regression-result", required=True)
    parser.add_argument("--docker-result", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    report = render(args.regression_result, args.docker_result, args.commit)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "risk-gates.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Security risk gates",
        "",
        f"Commit: `{args.commit}`",
        "",
        "| Threat | Gate | Evidence status |",
        "|---|---|---|",
    ]
    for threat in report["threats"]:
        gate = "PASS" if threat["gates_passed"] else "NOT PROVEN"
        lines.append(f"| {threat['id']} | {gate} | {threat['evidence_status']} |")
    lines.extend(
        [
            "",
            "Passing gates do not alter ordinal risk scores automatically. A documented human review is required.",
        ]
    )
    (args.output_dir / "risk-gates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not all(threat["gates_passed"] for threat in report["threats"]):
        raise SystemExit("one or more required CI job classes did not pass")


if __name__ == "__main__":
    main()
