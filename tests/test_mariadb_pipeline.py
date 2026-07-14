"""Fast regression tests for the persisted CPC gRPC/mTLS processing path."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "intermediate-vor-partition-cpc"


def _load_pipeline_server_module():
    """Load the pure rule-processing logic without installing gRPC locally."""
    grpc = types.ModuleType("grpc")
    grpc.StatusCode = types.SimpleNamespace(PERMISSION_DENIED="permission-denied")
    grpc.ssl_channel_credentials = Mock()
    grpc.ssl_server_credentials = Mock()
    grpc.secure_channel = Mock()
    grpc.server = Mock()

    pipeline_pb2 = types.ModuleType("pipeline_pb2")
    pipeline_pb2_grpc = types.ModuleType("pipeline_pb2_grpc")
    pipeline_pb2_grpc.ProcessingServiceServicer = object
    pipeline_pb2_grpc.CpcServiceStub = Mock
    pipeline_pb2_grpc.add_ProcessingServiceServicer_to_server = Mock()

    module_path = COMPONENT / "pipeline_server.py"
    spec = importlib.util.spec_from_file_location(
        "mariadb_pipeline_server_test_module", module_path
    )
    module = importlib.util.module_from_spec(spec)
    doubles = {
        "grpc": grpc,
        "pipeline_pb2": pipeline_pb2,
        "pipeline_pb2_grpc": pipeline_pb2_grpc,
    }
    with patch.dict(sys.modules, doubles):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


class PersistedPipelineRuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_pipeline_server_module()

    def _cpc(self, endpoint_value: str = "42"):
        cpc = Mock()
        cpc.read_values.return_value = {
            **self.module._FIXED_REQUIREMENTS,
            "Plant:ModbusSetpoint": endpoint_value,
        }
        return cpc

    def test_persisted_json_list_is_applied_over_cpc(self):
        cpc = self._cpc()
        endpoints = [
            ["Plant:ModbusSetpoint", "absolute, 9", "units", "== 9"]
        ]

        applied = self.module.process_endpoint_rules(cpc, "request-1", endpoints)

        self.assertEqual(applied, {"Plant:ModbusSetpoint": 9.0})
        cpc.apply.assert_called_once_with(
            "request-1", {"Plant:ModbusSetpoint": 9.0}
        )

    def test_protobuf_shaped_endpoint_uses_same_verified_logic(self):
        cpc = self._cpc("10")
        endpoint = types.SimpleNamespace(
            name="Plant:ModbusSetpoint",
            change_type="relative, 20%",
            unit="units",
            condition="<= 12",
        )

        applied = self.module.process_endpoint_rules(cpc, "request-2", [endpoint])

        self.assertEqual(applied, {"Plant:ModbusSetpoint": 12.0})
        cpc.apply.assert_called_once_with(
            "request-2", {"Plant:ModbusSetpoint": 12.0}
        )

    def test_failed_constraint_never_reaches_apply(self):
        cpc = self._cpc()
        endpoints = [
            ["Plant:ModbusSetpoint", "absolute, 9", "units", "> 10"]
        ]

        with self.assertRaisesRegex(ValueError, "mapping constraint failed"):
            self.module.process_endpoint_rules(cpc, "request-3", endpoints)

        cpc.apply.assert_not_called()

    def test_missing_acceptance_requirement_fails_closed(self):
        cpc = self._cpc()
        del cpc.read_values.return_value["TestObject:SystemAvailable"]
        endpoints = [
            ["Plant:ModbusSetpoint", "absolute, 9", "units", "== 9"]
        ]

        with self.assertRaisesRegex(ValueError, "acceptance requirement failed"):
            self.module.process_endpoint_rules(cpc, "request-4", endpoints)

        cpc.apply.assert_not_called()


if __name__ == "__main__":
    unittest.main()
