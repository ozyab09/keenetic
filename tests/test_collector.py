"""Тесты режима сбора (keenetic.collector)."""

import time
import unittest
from unittest.mock import patch

from keenetic.collector import fetch_and_collect, print_collected
from keenetic.models import Host, CollectedHost
from keenetic.whois import WhoisInfo

HOST = Host(index=1, ip="10.0.0.5", mac="aa:bb:cc:dd:ee:ff", name="TV",
            interface="Home", active=True)


def _conns():
    """Соединения: два от нашего хоста (443 и 53) и одно от чужого."""
    return [
        {"src": "10.0.0.5", "dst": "8.8.8.8", "sport": 50000, "dport": 443},
        {"src": "10.0.0.5", "dst": "9.9.9.9", "sport": 50001, "dport": 53},
        {"src": "10.0.0.9", "dst": "1.1.1.1", "sport": 50002, "dport": 443},
    ]


class TestFetchAndCollect(unittest.TestCase):
    def test_port_443_filters(self):
        with patch("keenetic.collector.get_all_endpoint_connections",
                   return_value=_conns()):
            collected = {}
            fetch_and_collect(None, HOST, collected, 1, 5, 443)
        self.assertEqual(set(collected), {"8.8.8.8"})

    def test_port_0_collects_all_ports(self):
        with patch("keenetic.collector.get_all_endpoint_connections",
                   return_value=_conns()):
            collected = {}
            fetch_and_collect(None, HOST, collected, 1, 5, 0)
        self.assertEqual(set(collected), {"8.8.8.8", "9.9.9.9"})
        self.assertEqual(collected["8.8.8.8"].ports, {"443"})
        self.assertEqual(collected["9.9.9.9"].ports, {"53"})

    def test_ignores_other_hosts(self):
        with patch("keenetic.collector.get_all_endpoint_connections",
                   return_value=_conns()):
            collected = {}
            fetch_and_collect(None, HOST, collected, 1, 5, 0)
        self.assertNotIn("1.1.1.1", collected)


class TestPrintCollected(unittest.TestCase):
    def test_missing_port_dash_does_not_crash(self):
        ch = CollectedHost(ip="8.8.8.8", ports={"443", "-"}, count=2,
                           first_seen=time.time(), last_seen=time.time())
        with patch("keenetic.collector.whois_lookup",
                   return_value=WhoisInfo(ip="8.8.8.8", cidr="8.8.8.0/24",
                                          org_name="Test", organization="Test")):
            cache = print_collected({"8.8.8.8": ch}, HOST, 0)
        self.assertIn("8.8.8.8", cache)

    def test_empty_collected(self):
        self.assertEqual(print_collected({}, HOST, 0), {})


if __name__ == "__main__":
    unittest.main()
