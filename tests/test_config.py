"""Tests for the configuration (keenetic.config)."""

import importlib
import os
import unittest

import keenetic.config as config

ENV_KEY = "KEENETIC_ROUTER_IP"


class TestConfig(unittest.TestCase):
    def setUp(self):
        self._orig = os.environ.get(ENV_KEY)

    def tearDown(self):
        # Restore the environment and reload the module so we don't mutate
        # the shared state for other tests in the same process.
        if self._orig is None:
            os.environ.pop(ENV_KEY, None)
        else:
            os.environ[ENV_KEY] = self._orig
        importlib.reload(config)

    def test_default_router_ip(self):
        os.environ.pop(ENV_KEY, None)
        importlib.reload(config)
        self.assertEqual(config.ROUTER_IP, "192.168.1.1")
        self.assertEqual(config.BASE_URL, "http://192.168.1.1")

    def test_env_router_ip(self):
        os.environ[ENV_KEY] = "10.0.0.1"
        importlib.reload(config)
        self.assertEqual(config.ROUTER_IP, "10.0.0.1")
        self.assertEqual(config.BASE_URL, "http://10.0.0.1")

    def test_default_login(self):
        self.assertEqual(config.LOGIN, "admin")


if __name__ == "__main__":
    unittest.main()
