"""Regression tests for fail-closed gateway security behavior."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
INTERFACE = ROOT / "interface-partition"
AUTHORIZATION = INTERFACE / "authorization_handler"
sys.path.insert(0, str(AUTHORIZATION))

from opa_input import parse_numeric_value


def _load_user_manager_module():
    """Load the module with lightweight dependency doubles for bootstrap tests."""
    tinydb = types.ModuleType("tinydb")
    tinydb.TinyDB = Mock
    tinydb.Query = Mock
    tinydb_table = types.ModuleType("tinydb.table")
    tinydb_table.Document = dict
    tinydb_storages = types.ModuleType("tinydb.storages")
    tinydb_storages.JSONStorage = Mock
    tinydb_middlewares = types.ModuleType("tinydb.middlewares")
    tinydb_middlewares.CachingMiddleware = Mock

    argon2 = types.ModuleType("argon2")
    argon2.PasswordHasher = Mock(return_value=Mock())
    argon2_low_level = types.ModuleType("argon2.low_level")
    argon2_low_level.Type = types.SimpleNamespace(ID="id")
    argon2_exceptions = types.ModuleType("argon2.exceptions")
    argon2_exceptions.VerifyMismatchError = ValueError
    argon2_exceptions.InvalidHash = ValueError
    argon2.exceptions = argon2_exceptions

    doubles = {
        "tinydb": tinydb,
        "tinydb.table": tinydb_table,
        "tinydb.storages": tinydb_storages,
        "tinydb.middlewares": tinydb_middlewares,
        "argon2": argon2,
        "argon2.low_level": argon2_low_level,
        "argon2.exceptions": argon2_exceptions,
    }
    module_path = INTERFACE / "user_manager" / "user_manager_tinydb.py"
    spec = importlib.util.spec_from_file_location("bootstrap_test_module", module_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, doubles):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


def _load_authorization_handler_module():
    casbin = types.ModuleType("casbin")
    casbin.Enforcer = Mock
    module_path = AUTHORIZATION / "authorization_handler.py"
    spec = importlib.util.spec_from_file_location("authorization_test_module", module_path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"casbin": casbin}):
        assert spec.loader is not None
        spec.loader.exec_module(module)
    return module


def _load_pure_module(name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(name, module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class NumericOpaInputTests(unittest.TestCase):
    def test_accepts_protocol_numeric_strings(self):
        self.assertEqual(parse_numeric_value("15"), 15.0)
        self.assertEqual(parse_numeric_value(" -2,5 "), -2.5)
        self.assertEqual(parse_numeric_value(4), 4.0)

    def test_rejects_missing_malformed_or_non_finite_values(self):
        invalid = (None, True, "", "set to 12", "12 then 13", "NaN", "inf", object())
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    parse_numeric_value(value)


class DeploymentTransportGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.brownfield_mode = _load_pure_module(
            "brownfield_security_mode",
            ROOT / "brownfield-opcua-server" / "security_mode.py",
        )
        cls.opa_transport = _load_pure_module(
            "opa_transport",
            AUTHORIZATION / "opa_transport.py",
        )

    def test_no_security_server_requires_explicit_test_mode(self):
        enabled = self.brownfield_mode.insecure_opcua_test_server_enabled
        self.assertFalse(enabled({}))
        self.assertTrue(
            enabled(
                {
                    "SIOT_DEPLOYMENT_MODE": "test",
                    "ENABLE_INSECURE_OPCUA_TEST_SERVER": "true",
                }
            )
        )
        with self.assertRaisesRegex(RuntimeError, "only when SIOT_DEPLOYMENT_MODE=test"):
            enabled(
                {
                    "SIOT_DEPLOYMENT_MODE": "production",
                    "ENABLE_INSECURE_OPCUA_TEST_SERVER": "true",
                }
            )

    def test_production_opa_enforcement_requires_https(self):
        allowed = self.opa_transport.opa_transport_allowed
        self.assertEqual(
            allowed("http://opa:8181/v1/data/siot/authz/allow", "production")[0],
            False,
        )
        self.assertEqual(
            allowed("https://opa.example/v1/data/siot/authz/allow", "production")[0],
            True,
        )
        self.assertEqual(
            allowed("http://opa:8181/v1/data/siot/authz/allow", "test")[0],
            True,
        )

    def test_opa_fail_open_is_test_only(self):
        allowed = self.opa_transport.opa_fail_open_allowed
        self.assertFalse(allowed(False, "test"))
        self.assertTrue(allowed(True, "test"))
        self.assertFalse(allowed(True, "production"))
        self.assertFalse(allowed(True, "staging"))
        self.assertFalse(allowed(True, "typo"))

    def test_opa_timeout_is_positive_finite_and_bounded(self):
        parse = self.opa_transport.parse_opa_timeout_seconds
        self.assertEqual(parse("0.75"), 0.75)
        self.assertEqual(parse(10), 10.0)
        for invalid in (None, "", "not-a-number", "nan", "inf", 0, -1, 10.01):
            with self.subTest(value=invalid):
                with self.assertRaisesRegex(ValueError, "OPA_TIMEOUT_SECONDS"):
                    parse(invalid)

    def test_https_opa_requires_complete_component_tls_material(self):
        build = self.opa_transport.build_opa_ssl_context
        build.cache_clear()
        with self.assertRaisesRegex(ValueError, "OPA_TLS_CA_CERT"):
            build(
                "https://opa:8181/v1/data/siot/authz/allow",
                "production",
                "",
                "",
                "",
            )

    def test_test_only_http_opa_does_not_create_tls_context(self):
        build = self.opa_transport.build_opa_ssl_context
        build.cache_clear()
        self.assertIsNone(
            build(
                "http://opa:8181/v1/data/siot/authz/allow",
                "test",
                "",
                "",
                "",
            )
        )


class AdminBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_user_manager_module()

    def _manager(self):
        manager = self.module.UserManagerTinyDB.__new__(self.module.UserManagerTinyDB)
        manager.retrieve_user = Mock(return_value=(False, None))
        manager._read_admin_password_from_env = Mock(
            return_value="A-valid-bootstrap-password-123"
        )
        manager.create_user = Mock(return_value=True)
        return manager

    def test_rejects_failed_admin_creation(self):
        manager = self._manager()
        manager.create_user.return_value = False
        with self.assertRaisesRegex(SystemExit, "2"):
            manager._bootstrap_admin_or_die()

    def test_rejects_unverifiable_admin_after_insert(self):
        manager = self._manager()
        with self.assertRaisesRegex(SystemExit, "2"):
            manager._bootstrap_admin_or_die()
        self.assertEqual(manager.retrieve_user.call_count, 2)

    def test_accepts_admin_only_after_readback(self):
        manager = self._manager()
        manager.retrieve_user.side_effect = [
            (False, None),
            (True, (1, "admin", "hash", "")),
        ]
        manager._bootstrap_admin_or_die()
        manager.create_user.assert_called_once()


class CredentialPersistenceTests(unittest.TestCase):
    def test_insert_flushes_tinydb_cache_before_cross_module_readback(self):
        module = _load_user_manager_module()
        connector = module.DatabaseConnector.__new__(module.DatabaseConnector)
        connector._lock = threading.RLock()
        connector._User = Mock()
        connector._table = Mock()
        connector._table.get.return_value = None
        connector._db = Mock()
        connector._db.storage.flush = Mock()

        with patch.object(module.UserManagerTinyDB, "hash_password", return_value="hash"):
            self.assertTrue(connector.insert_credentials(("admin", "valid-password")))

        connector._db.storage.flush.assert_called_once_with()


class AuthorizationIsolationTests(unittest.TestCase):
    def test_authorization_read_waits_for_role_change(self):
        AuthorizationHandler = _load_authorization_handler_module().AuthorizationHandler

        handler = AuthorizationHandler.__new__(AuthorizationHandler)
        handler._lock = threading.RLock()
        mutation_started = threading.Event()
        release_mutation = threading.Event()
        enforce_called = threading.Event()

        class EnforcerDouble:
            def get_all_roles(self):
                return []

            def get_all_subjects(self):
                return ["PlantOperator", "Admin"]

            def get_roles_for_user(self, _user):
                return ["PlantOperator"]

            def delete_role_for_user(self, _user, _role):
                mutation_started.set()
                release_mutation.wait(timeout=2)
                return True

            def add_role_for_user(self, _user, _role):
                return True

            def save_policy(self):
                return None

            def enforce(self, *_args):
                enforce_called.set()
                return True

        handler.enforcer = EnforcerDouble()
        writer = threading.Thread(
            target=handler.set_single_role_for_user,
            args=("alice", "Admin"),
        )
        reader = threading.Thread(
            target=handler.verify_authorization,
            args=("alice", "Pump_B_Power", '"flow rate adjustment"'),
        )

        writer.start()
        self.assertTrue(mutation_started.wait(timeout=1))
        reader.start()
        time.sleep(0.05)
        self.assertFalse(enforce_called.is_set())
        release_mutation.set()
        writer.join(timeout=2)
        reader.join(timeout=2)
        self.assertTrue(enforce_called.is_set())

    def test_remove_user_accepts_casbin_none_as_save_success(self):
        AuthorizationHandler = _load_authorization_handler_module().AuthorizationHandler
        handler = AuthorizationHandler.__new__(AuthorizationHandler)
        handler._lock = threading.RLock()
        handler.enforcer = Mock()
        handler.enforcer.delete_user.return_value = True
        handler.enforcer.save_policy.return_value = None

        self.assertTrue(handler.remove_user("alice"))

    def test_remove_user_propagates_explicit_save_failure(self):
        AuthorizationHandler = _load_authorization_handler_module().AuthorizationHandler
        handler = AuthorizationHandler.__new__(AuthorizationHandler)
        handler._lock = threading.RLock()
        handler.enforcer = Mock()
        handler.enforcer.delete_user.return_value = True
        handler.enforcer.save_policy.return_value = False

        self.assertFalse(handler.remove_user("alice"))


if __name__ == "__main__":
    unittest.main()
