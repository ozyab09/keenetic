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

    def post_parse(self, commands):
        self.posted = commands
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


class TestFindSubnetConflicts(unittest.TestCase):
    def test_exact_duplicates_within_group(self):
        groups = {"a": ["8.8.8.8", "8.8.8.8/32", "142.250.0.0/15"]}
        conflicts = sr.find_subnet_conflicts(groups)
        self.assertEqual([c for c, _ in conflicts["exact"]], ["8.8.8.8/32"])
        self.assertEqual(conflicts["covered"], [])
        self.assertEqual(conflicts["cross_covered"], [])
        self.assertEqual(conflicts["misaligned"], [])

    def test_exact_duplicates_across_groups(self):
        groups = {"a": ["8.8.8.0/24"], "b": ["8.8.8.0/24"]}
        conflicts = sr.find_subnet_conflicts(groups)
        self.assertEqual(len(conflicts["exact"]), 1)
        self.assertEqual(len(conflicts["exact"][0][1]), 2)

    def test_covered_same_group(self):
        groups = {"a": ["8.8.0.0/16", "8.8.8.0/24"]}
        conflicts = sr.find_subnet_conflicts(groups)
        self.assertEqual(conflicts["covered"], [("8.8.8.0/24", "8.8.0.0/16", "a")])

    def test_cross_group_coverage(self):
        groups = {"a": ["8.8.0.0/16"], "b": ["8.8.8.0/24"]}
        conflicts = sr.find_subnet_conflicts(groups)
        self.assertEqual(conflicts["covered"], [])  # different groups
        self.assertEqual(conflicts["cross_covered"],
                         [("8.8.8.0/24", "8.8.0.0/16", "b", "a")])

    def test_misaligned(self):
        groups = {"a": ["10.0.0.128/24"]}
        conflicts = sr.find_subnet_conflicts(groups)
        self.assertEqual(conflicts["misaligned"], [("a", "10.0.0.128/24", "10.0.0.0/24")])
        self.assertEqual(conflicts["exact"], [])

    def test_no_conflicts(self):
        groups = {"a": ["8.8.8.0/24", "example.com"], "b": ["142.250.0.0/15"]}
        conflicts = sr.find_subnet_conflicts(groups)
        for key in conflicts:
            self.assertEqual(conflicts[key], [], key)

    def test_domains_ignored(self):
        conflicts = sr.find_subnet_conflicts({"a": ["example.com", "google.com"]})
        for key in conflicts:
            self.assertEqual(conflicts[key], [], key)


class TestDedupeEntries(unittest.TestCase):
    def test_dedupes_raw_and_canonical(self):
        entries = [{"address": "8.8.8.8"}, {"address": "8.8.8.8/32"},
                   {"address": "8.8.8.8"}, {"address": "example.com"},
                   {"address": "example.com"}]
        result = sr._dedupe_entries(entries)
        self.assertEqual([e["address"] for e in result], ["8.8.8.8", "example.com"])

    def test_keeps_distinct_subnets(self):
        entries = [{"address": "8.8.0.0/16"}, {"address": "8.8.8.0/24"}]
        self.assertEqual(len(sr._dedupe_entries(entries)), 2)


class TestRemoveCoveredEntries(unittest.TestCase):
    def test_removes_narrower(self):
        entries = [{"address": "8.8.0.0/16"}, {"address": "8.8.8.0/24"},
                   {"address": "example.com"}]
        result = sr._remove_covered_entries(entries)
        self.assertEqual([e["address"] for e in result], ["8.8.0.0/16", "example.com"])

    def test_keeps_distinct(self):
        entries = [{"address": "8.8.0.0/16"}, {"address": "142.250.0.0/15"}]
        self.assertEqual(len(sr._remove_covered_entries(entries)), 2)

    def test_identical_subnets_not_both_removed(self):
        entries = [{"address": "8.8.8.0/24"}, {"address": "8.8.8.0/24"}]
        self.assertEqual(len(sr._remove_covered_entries(entries)), 2)


class TestCanonicalizeEntries(unittest.TestCase):
    def test_rewrites_misaligned(self):
        entries = [{"address": "10.0.0.128/24"}, {"address": "8.8.8.8"},
                   {"address": "example.com"}]
        result = sr._canonicalize_entries(entries)
        self.assertEqual([e["address"] for e in result],
                         ["10.0.0.0/24", "8.8.8.8", "example.com"])

    def test_keeps_canonical(self):
        entries = [{"address": "8.8.0.0/16"}, {"address": "142.250.0.0/15"}]
        result = sr._canonicalize_entries(entries)
        self.assertEqual([e["address"] for e in result],
                         ["8.8.0.0/16", "142.250.0.0/15"])


class TestRunParseCommands(unittest.TestCase):
    def test_empty_ok(self):
        self.assertTrue(sr.run_parse_commands(FakeSession({}), []))

    def test_success(self):
        self.assertTrue(sr.run_parse_commands(FakeSession({}), ["system configuration save"]))

    def test_non_200_fails(self):
        s = FakeSession({}, post_status=500)
        self.assertFalse(sr.run_parse_commands(s, ["system configuration save"]))

    def test_status_error_fails(self):
        body = b'[{"parse": {"status": [{"status": "error", "message": "bad"}]}}]'
        s = FakeSession({}, post_body=body)
        self.assertFalse(sr.run_parse_commands(s, ["no object-group fqdn a include 1.1.1.1"]))


class TestApplyAuditFix(unittest.TestCase):
    def test_variant1_dedupes(self):
        groups = {"a": {"description": "",
                        "include": [{"address": "8.8.8.8"}, {"address": "8.8.8.8/32"}]}}
        s = FakeSession(groups)
        with patch("builtins.input", return_value="y"):
            sr._apply_audit_fix(s, groups, 1)
        self.assertEqual(s.posted, ["no object-group fqdn a include 8.8.8.8/32",
                                    "system configuration save"])

    def test_variant2_removes_covered(self):
        groups = {"a": {"description": "",
                        "include": [{"address": "8.8.0.0/16"}, {"address": "8.8.8.0/24"}]}}
        s = FakeSession(groups)
        with patch("builtins.input", return_value="y"):
            sr._apply_audit_fix(s, groups, 2)
        self.assertEqual(s.posted, ["no object-group fqdn a include 8.8.8.0/24",
                                    "system configuration save"])

    def test_variant3_canonicalizes(self):
        groups = {"a": {"description": "",
                        "include": [{"address": "10.0.0.128/24"}]}}
        s = FakeSession(groups)
        with patch("builtins.input", return_value="y"):
            sr._apply_audit_fix(s, groups, 3)
        self.assertEqual(s.posted, ["no object-group fqdn a include 10.0.0.128/24",
                                    "object-group fqdn a include 10.0.0.0/24",
                                    "system configuration save"])

    def test_variant3_dedupe_after_canonicalize(self):
        # canonicalizing 10.0.0.128/24 → 10.0.0.0/24 makes it a duplicate of
        # the existing entry, so only the removal command is generated
        groups = {"a": {"description": "",
                        "include": [{"address": "10.0.0.128/24"},
                                     {"address": "10.0.0.0/24"}]}}
        s = FakeSession(groups)
        with patch("builtins.input", return_value="y"):
            sr._apply_audit_fix(s, groups, 3)
        self.assertEqual(s.posted, ["no object-group fqdn a include 10.0.0.128/24",
                                    "system configuration save"])

    def test_decline_no_write(self):
        groups = {"a": {"description": "",
                        "include": [{"address": "8.8.8.8"}, {"address": "8.8.8.8/32"}]}}
        s = FakeSession(groups)
        with patch("builtins.input", return_value="n"):
            sr._apply_audit_fix(s, groups, 1)
        self.assertIsNone(s.posted)

    def test_no_changes_no_prompt(self):
        groups = {"a": {"description": "", "include": [{"address": "8.8.8.8"}]}}
        s = FakeSession(groups)
        with patch("builtins.input", return_value="y") as m:
            sr._apply_audit_fix(s, groups, 2)
        m.assert_not_called()
        self.assertIsNone(s.posted)

    def test_parse_error_reported(self):
        body = b'[{"parse": {"status": [{"status": "error", "message": "bad"}]}}]'
        groups = {"a": {"description": "",
                        "include": [{"address": "8.8.8.8"}, {"address": "8.8.8.8/32"}]}}
        s = FakeSession(groups, post_body=body)
        with patch("builtins.input", return_value="y"):
            sr._apply_audit_fix(s, groups, 1)
        self.assertIsNotNone(s.posted)  # commands were sent, the error was reported


class TestRunSubnetAudit(unittest.TestCase):
    def test_clean_groups_no_fix_prompt(self):
        groups = {"a": {"description": "", "include": [{"address": "8.8.8.0/24"}]}}
        s = FakeSession(groups)
        with patch("builtins.input") as m:
            sr.run_subnet_audit(s)
        m.assert_not_called()
        self.assertIsNone(s.posted)

    def test_fix_applied(self):
        groups = {"a": {"description": "d",
                        "include": [{"address": "8.8.8.8"}, {"address": "8.8.8.8/32"}]}}
        s = FakeSession(groups)
        with patch("builtins.input", side_effect=["1", "y"]):
            sr.run_subnet_audit(s)
        self.assertEqual(s.posted, ["no object-group fqdn a include 8.8.8.8/32",
                                    "system configuration save"])

    def test_misaligned_only_offers_fix(self):
        groups = {"a": {"description": "d", "include": [{"address": "10.0.0.128/24"}]}}
        s = FakeSession(groups)
        with patch("builtins.input", side_effect=["3", "y"]):
            sr.run_subnet_audit(s)
        self.assertEqual(s.posted, ["no object-group fqdn a include 10.0.0.128/24",
                                    "object-group fqdn a include 10.0.0.0/24",
                                    "system configuration save"])

    def test_zero_variant_no_write(self):
        groups = {"a": {"description": "d",
                        "include": [{"address": "8.8.8.8"}, {"address": "8.8.8.8/32"}]}}
        s = FakeSession(groups)
        with patch("builtins.input", return_value="0"):
            sr.run_subnet_audit(s)
        self.assertIsNone(s.posted)

    def test_no_groups(self):
        with patch("builtins.input") as m:
            sr.run_subnet_audit(FakeSession({}))
        m.assert_not_called()


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
