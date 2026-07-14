from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RotationPreflightTests(unittest.TestCase):
    def test_active_node_red_store_is_rejected_before_any_key_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary)
            shutil.copy2(ROOT / "rotate-secrets.sh", fixture / "rotate-secrets.sh")

            grpc = fixture / "_generated_certificates" / "grpc"
            ca = grpc / "ca"
            ca.mkdir(parents=True)
            generator = grpc / "generate-grpc-certs.sh"
            generator.write_text("#!/usr/bin/env bash\nexit 0\n")
            generator.chmod(0o755)
            sentinel = ca / "ca.key"
            sentinel.write_text("must-not-change")

            node_red = fixture / "node-red"
            node_red.mkdir()
            (node_red / ".config.runtime.json").write_text(
                json.dumps({"_credentialSecret": "test-only-old-key"})
            )
            (node_red / "flows_cred.json").write_text(
                json.dumps({"$": "synthetic-encrypted-store"})
            )

            result = subprocess.run(
                ["bash", str(fixture / "rotate-secrets.sh")],
                cwd=fixture,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Refusing a key-only rotation", result.stderr)
            self.assertEqual(sentinel.read_text(), "must-not-change")
            self.assertFalse((fixture / ".secrets-backup").exists())


if __name__ == "__main__":
    unittest.main()
