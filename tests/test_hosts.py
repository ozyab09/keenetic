"""Тесты интерактивного выбора хоста (keenetic.hosts.select_host)."""

import unittest
from unittest.mock import patch

from keenetic.hosts import select_host
from keenetic.models import Host


HOSTS = [
    Host(index=1, ip="10.0.0.10", mac="aa:bb:cc:dd:ee:01", name="TV",
         interface="Home", active=True),
    Host(index=2, ip="10.0.0.20", mac="aa:bb:cc:dd:ee:02", name="Phone",
         interface="Home", active=False),
]


class TestSelectHost(unittest.TestCase):
    def test_enter_confirms_last(self):
        with patch("builtins.input", return_value=""):
            host = select_host(HOSTS, last_ip="10.0.0.10")
        self.assertEqual(host.ip, "10.0.0.10")

    def test_quit_exits(self):
        for word in ("quit", "exit", "q", "выход"):
            with patch("builtins.input", return_value=word):
                with self.assertRaises(SystemExit):
                    select_host(HOSTS, last_ip="10.0.0.10")

    def test_enter_without_last_exits(self):
        with patch("builtins.input", return_value=""):
            with self.assertRaises(SystemExit):
                select_host(HOSTS, last_ip=None)

    def test_last_word(self):
        with patch("builtins.input", return_value="last"):
            host = select_host(HOSTS, last_ip="10.0.0.10")
        self.assertEqual(host.ip, "10.0.0.10")

    def test_by_number(self):
        with patch("builtins.input", return_value="2"):
            host = select_host(HOSTS, last_ip=None)
        self.assertEqual(host.ip, "10.0.0.20")

    def test_by_ip(self):
        with patch("builtins.input", return_value="10.0.0.20"):
            host = select_host(HOSTS, last_ip=None)
        self.assertEqual(host.ip, "10.0.0.20")

    def test_by_name_partial(self):
        with patch("builtins.input", return_value="phon"):
            host = select_host(HOSTS, last_ip=None)
        self.assertEqual(host.ip, "10.0.0.20")


if __name__ == "__main__":
    unittest.main()
