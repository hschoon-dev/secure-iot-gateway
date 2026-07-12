import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parent / "evaluation" / "render_risk_gate_report.py"
SPEC = importlib.util.spec_from_file_location("risk_gate_report", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RiskGateReportTests(unittest.TestCase):
    def test_green_jobs_prove_gates_without_changing_scores(self):
        report = MODULE.render("success", "success", "test-commit")
        self.assertTrue(all(item["gates_passed"] for item in report["threats"]))
        self.assertFalse(report["ordinal_scores_automatically_changed"])
        t11 = next(item for item in report["threats"] if item["id"] == "T-11")
        self.assertIn("remain open", t11["evidence_status"])

    def test_missing_docker_job_leaves_e2e_gates_unproven(self):
        report = MODULE.render("success", "failure", "test-commit")
        t02 = next(item for item in report["threats"] if item["id"] == "T-02")
        self.assertFalse(t02["gates_passed"])


if __name__ == "__main__":
    unittest.main()
