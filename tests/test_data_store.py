import importlib.util
import os
from pathlib import Path
import unittest
from unittest import mock

MODULE_PATH = Path(__file__).resolve().parents[1] / "services" / "data_store.py"
_spec = importlib.util.spec_from_file_location("data_store", MODULE_PATH)
data_store = importlib.util.module_from_spec(_spec)
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(data_store)


class TestDbParams(unittest.TestCase):
    def setUp(self):
        self.env_patcher = mock.patch.dict(os.environ, {}, clear=True)
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    def test_uses_default_ports_when_not_configured(self):
        env = {
            "FMP_DATA_USER": "user",
            "FMP_DATA_PASS": "pass",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            params = data_store._db_params()

        ports = [p["port"] for p in params]
        self.assertEqual(ports, [5433, 5432])
        self.assertEqual(params[0]["user"], "user")
        self.assertEqual(params[0]["password"], "pass")

    def test_ignores_invalid_port_values(self):
        env = {
            "FMP_DATA_USER": "user",
            "FMP_DATA_PASS": "pass",
            "FMP_DATA_PORT": "not-a-port",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            params = data_store._db_params()

        ports = [p["port"] for p in params]
        self.assertEqual(ports, [5433, 5432])


class FakeConnection:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class FakePsycopg:
    def __init__(self, fail_ports=None):
        self.fail_ports = set(fail_ports or [])
        self.attempts = []
        self.last_connection = None

    def connect(self, **kwargs):
        port = kwargs.get("port")
        self.attempts.append(port)
        if port in self.fail_ports:
            raise Exception(f"Port {port} unavailable")
        self.last_connection = FakeConnection()
        return self.last_connection


class TestConnectFallback(unittest.TestCase):
    def tearDown(self):
        data_store._psycopg2_mod = None
        data_store._psycopg2_extras = None

    def test_connect_falls_back_to_next_available_port(self):
        env = {
            "FMP_DATA_USER": "user",
            "FMP_DATA_PASS": "pass",
            "FMP_DATA_PORT": "6000",
        }
        fake_psycopg = FakePsycopg(fail_ports={6000})

        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(data_store, "_load_psycopg2", return_value=(fake_psycopg, None)):
                with data_store._connect() as conn:
                    self.assertIs(conn, fake_psycopg.last_connection)

        self.assertEqual(fake_psycopg.attempts, [6000, 5433])
        self.assertTrue(fake_psycopg.last_connection.closed)
