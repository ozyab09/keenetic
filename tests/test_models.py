"""Тесты моделей данных (keenetic.models)."""

import unittest

from keenetic.models import str_val, parse_connection, ips_for_host, to_connection


class TestStrVal(unittest.TestCase):
    def test_none(self):
        self.assertEqual(str_val(None), "-")

    def test_bool(self):
        self.assertEqual(str_val(True), "true")

    def test_int_float(self):
        self.assertEqual(str_val(443), "443")
        self.assertEqual(str_val(4.5), "4.5")

    def test_dict_address(self):
        self.assertEqual(str_val({"address": "8.8.8.8"}), "8.8.8.8")

    def test_plain_string(self):
        self.assertEqual(str_val("tcp"), "tcp")


class TestParseConnection(unittest.TestCase):
    def test_object_format(self):
        c = {"src": {"address": "10.0.0.5"}, "dst": {"address": "8.8.8.8"},
             "sport": 50000, "dport": 443, "protocol": "TCP"}
        raw = parse_connection(c)
        self.assertIsNotNone(raw)
        self.assertEqual(raw.src_ip, "10.0.0.5")
        self.assertEqual(raw.dst_ip, "8.8.8.8")
        self.assertEqual(raw.dst_port, "443")
        self.assertEqual(raw.protocol, "TCP")

    def test_nat_format(self):
        c = {"src": "10.0.0.5", "dst": "8.8.8.8", "sport": 50000, "dport": 443,
             "src-out": "10.0.0.5", "dst-out": "8.8.4.4", "bytes": 100, "bytes-out": 200}
        raw = parse_connection(c)
        self.assertIsNotNone(raw)
        self.assertEqual(raw.x_src_ip, "10.0.0.5")
        self.assertEqual(raw.x_dst_ip, "8.8.4.4")
        self.assertEqual(raw.bytes_in, "100")
        self.assertEqual(raw.bytes_out, "200")

    def test_empty_record(self):
        self.assertIsNone(parse_connection({"foo": "bar"}))


class TestIpsForHost(unittest.TestCase):
    def test_collects_nat_ips(self):
        c = {"src": "10.0.0.5", "dst": "8.8.8.8", "dst-out": "8.8.4.4"}
        raw = parse_connection(c)
        ips = ips_for_host(raw)
        self.assertIn("10.0.0.5", ips)
        self.assertIn("8.8.8.8", ips)
        self.assertIn("8.8.4.4", ips)
        self.assertNotIn("-", ips)


class TestToConnection(unittest.TestCase):
    def test_outbound(self):
        c = {"src": "10.0.0.5", "dst": "8.8.8.8", "sport": 50000, "dport": 443}
        raw = parse_connection(c)
        conn = to_connection(raw, "10.0.0.5")
        self.assertEqual(conn.src_ip, "10.0.0.5")
        self.assertEqual(conn.dst_ip, "8.8.8.8")

    def test_inbound(self):
        c = {"src": "8.8.8.8", "dst": "10.0.0.5", "sport": 443, "dport": 50000}
        raw = parse_connection(c)
        conn = to_connection(raw, "10.0.0.5")
        self.assertEqual(conn.src_ip, "8.8.8.8")
        self.assertEqual(conn.dst_ip, "10.0.0.5")


if __name__ == "__main__":
    unittest.main()
