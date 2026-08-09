"""Tests for subnet comparison and group selection (keenetic.static_routes)."""

import json
import unittest
from unittest.mock import patch

from keenetic import static_routes as sr
from keenetic.whois import WhoisInfo


class FakeSession:
    """Session stub: serves groups, accepts writes."""

    def __init__(self, groups, post_status=200, post_body=b"{}"):
        self.groups = groups
        self.post_status = post_status
        self.post_body = post_body
        self.posted = None

    def get(self, path):
        return json.dumps(self.groups).encode(), 200

    def post_json(self, path, payload):
        self.posted = payload
        return self.post_body, self.post_status


GROUPS = {
    "domain-list16": {"description": "Youtube Personal List",
                      "include": [{"address": "142.250.0.0/15"}]},
    "domain-list1": {"description": "Other domains",
                     "include": [{"address": "example.com"}]},
    "domain-list2": {"description": "", "include": [{"address": "8.8.8.8"}]},
}


class TestExtractSubnets(unittest.TestCase):
    def test_canonicalization(self):
        self.assertEqual(sr.extract_subnets(["8.8.8.8", "142.250.0.0/15"]),
                         {"8.8.8.8/32", "142.250.0.0/15"})

    def test_skips_zero_and_domains(self):
        self.assertEqual(sr.extract_subnets(["0.0.0.0", "0.0.0.0/0", "example.com"]), set())


class TestIsCovered(unittest.TestCase):
    def test_same_subnet(self):
        self.assertTrue(sr._is_covered("8.8.8.0/24", {"8.8.8.0/24"}))

    def test_wider_covers(self):
        self.assertTrue(sr._is_covered("8.8.8.0/24", {"8.8.0.0/16"}))

    def test_narrower_does_not_cover(self):
        self.assertFalse(sr._is_covered("8.8.0.0/16", {"8.8.8.0/24"}))

    def test_not_covered(self):
        self.assertFalse(sr._is_covered("1.2.3.0/24", {"8.8.8.0/24"}))


class TestGoogleSubnetsFromWhois(unittest.TestCase):
    def _whois(self, cidr, org_name, organization):
        return WhoisInfo(ip="1.1.1.1", cidr=cidr, org_name=org_name,
                         organization=organization, error=False)

    def test_filters_google_youtube(self):
        cache = {
            "a": self._whois("142.250.0.0/15", "Google LLC", "Google LLC (GOGL)"),
            "b": self._whois("8.8.8.0/24", "Google LLC", "Google LLC"),
            "c": self._whois("157.240.0.0/16", "Facebook Inc.", "Facebook Inc. (FB)"),
            "d": self._whois("", "YouTube", "YouTube LLC"),
        }
        found = sr.google_subnets_from_whois(cache)
        self.assertIn("142.250.0.0/15", found)
        self.assertIn("8.8.8.0/24", found)
        self.assertNotIn("157.240.0.0/16", found)

    def test_skips_errors_and_missing_cidr(self):
        cache = {
            "a": WhoisInfo(ip="1.1.1.1", error="timeout"),
            "b": WhoisInfo(ip="2.2.2.2", cidr="", org_name="Google LLC"),
        }
        self.assertEqual(sr.google_subnets_from_whois(cache), {})


class TestSelectFqdnGroup(unittest.TestCase):
    def test_enter_last_group(self):
        with patch("builtins.input", return_value=""):
            self.assertEqual(sr.select_fqdn_group(FakeSession(GROUPS), "domain-list1"),
                             "domain-list1")

    def test_enter_after_skip(self):
        # an empty string in last_choice means "don't add" → default 0
        with patch("builtins.input", return_value=""):
            self.assertIsNone(sr.select_fqdn_group(FakeSession(GROUPS), ""))

    def test_enter_no_last_defaults_first(self):
        # sorting: groups with a description first, then by name
        with patch("builtins.input", return_value=""):
            self.assertEqual(sr.select_fqdn_group(FakeSession(GROUPS), None),
                             "domain-list1")

    def test_by_number(self):
        with patch("builtins.input", return_value="3"):
            self.assertEqual(sr.select_fqdn_group(FakeSession(GROUPS), None),
                             "domain-list2")

    def test_skip_zero(self):
        with patch("builtins.input", return_value="0"):
            self.assertIsNone(sr.select_fqdn_group(FakeSession(GROUPS), None))

    def test_by_name(self):
        with patch("builtins.input", return_value="domain-list16"):
            self.assertEqual(sr.select_fqdn_group(FakeSession(GROUPS), None),
                             "domain-list16")

    def test_by_description(self):
        with patch("builtins.input", return_value="youtube personal"):
            self.assertEqual(sr.select_fqdn_group(FakeSession(GROUPS), None),
                             "domain-list16")

    def test_unknown_then_number(self):
        with patch("builtins.input", side_effect=["no-such", "2"]):
            self.assertEqual(sr.select_fqdn_group(FakeSession(GROUPS), None),
                             "domain-list16")

    def test_no_groups(self):
        with patch("builtins.input", return_value=""):
            self.assertIsNone(sr.select_fqdn_group(FakeSession({}), None))


class TestAddMissingSubnets(unittest.TestCase):
    def test_writes_to_chosen_group(self):
        s = FakeSession(GROUPS)
        sr._add_missing_subnets(s, {"34.128.0.0/10": "Google LLC"}, "domain-list1")
        payload = s.posted["domain-list1"]
        self.assertEqual(payload["description"], "Other domains")
        addrs = [e["address"] for e in payload["include"]]
        self.assertIn("example.com", addrs)      # old entries kept
        self.assertIn("34.128.0.0/10", addrs)    # new one added

    def test_unknown_group_no_write(self):
        s = FakeSession(GROUPS)
        sr._add_missing_subnets(s, {"34.128.0.0/10": "Google LLC"}, "no-such")
        self.assertIsNone(s.posted)

    def test_write_error(self):
        s = FakeSession(GROUPS, post_status=500)
        sr._add_missing_subnets(s, {"34.128.0.0/10": "Google LLC"}, "domain-list16")
        self.assertIsNotNone(s.posted)


class TestCompareGoogleSubnets(unittest.TestCase):
    @staticmethod
    def _cache():
        return {
            "a": WhoisInfo(ip="142.250.185.78", cidr="142.250.0.0/15",
                           org_name="Google LLC", organization="Google LLC (GOGL)"),
            "b": WhoisInfo(ip="34.160.212.185", cidr="34.128.0.0/10",
                           org_name="Google LLC", organization="Google LLC (GOOGL-2)"),
        }

    def test_with_group_adds_missing(self):
        s = FakeSession(GROUPS)  # router has 142.250.0.0/15, missing 34.128.0.0/10
        sr.compare_google_subnets(s, self._cache(), "domain-list16")
        addrs = [e["address"] for e in s.posted["domain-list16"]["include"]]
        self.assertIn("34.128.0.0/10", addrs)

    def test_without_group_skips_add(self):
        s = FakeSession(GROUPS)
        sr.compare_google_subnets(s, self._cache(), None)
        self.assertIsNone(s.posted)

    def test_no_google_subnets(self):
        cache = {"a": WhoisInfo(ip="1.1.1.1", cidr="1.0.0.0/8", org_name="APNIC")}
        s = FakeSession(GROUPS)
        sr.compare_google_subnets(s, cache, "domain-list16")
        self.assertIsNone(s.posted)


if __name__ == "__main__":
    unittest.main()
