"""Tests for storing the last choice (keenetic.last_choice)."""

import os
import tempfile
import unittest

from keenetic import last_choice


class TestLastChoice(unittest.TestCase):
    def setUp(self):
        self._fd, self.path = tempfile.mkstemp(suffix=".json")
        os.close(self._fd)
        os.unlink(self.path)  # let the function create the file itself

    def tearDown(self):
        if os.path.exists(self.path):
            os.unlink(self.path)

    def test_roundtrip_with_group(self):
        last_choice.save_last_choice("10.0.0.5", "collect", 443, "domain-list16", self.path)
        data = last_choice.load_last_choice(self.path)
        self.assertEqual(data["host"], "10.0.0.5")
        self.assertEqual(data["mode"], "collect")
        self.assertEqual(data["port"], 443)
        self.assertEqual(data["group"], "domain-list16")

    def test_collect_skip_stores_empty(self):
        last_choice.save_last_choice("10.0.0.5", "collect", 443, None, self.path)
        self.assertEqual(last_choice.load_last_choice(self.path)["group"], "")

    def test_once_preserves_previous_group(self):
        last_choice.save_last_choice("10.0.0.5", "collect", 443, "domain-list16", self.path)
        last_choice.save_last_choice("10.0.0.6", "once", 0, None, self.path)
        self.assertEqual(last_choice.load_last_choice(self.path)["group"], "domain-list16")

    def test_missing_file(self):
        self.assertEqual(last_choice.load_last_choice("/nonexistent/path.txt"), {})

    def test_corrupt_file(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("not json{{")
        self.assertEqual(last_choice.load_last_choice(self.path), {})


if __name__ == "__main__":
    unittest.main()
