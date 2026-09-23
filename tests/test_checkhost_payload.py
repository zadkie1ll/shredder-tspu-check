import unittest
from types import SimpleNamespace

from app.checkhost import CheckHostClient


class CheckHostPayloadTests(unittest.TestCase):
    def setUp(self):
        self.client = CheckHostClient(
            SimpleNamespace(
                checkhost_ru_targets=("russia",),
                checkhost_control_targets=("romania",),
            )
        )
        self.request = {
            "request_id": "check-1",
            "permanent_link": "https://example.test/check-1",
            "nodes": {
                "ru1": ["ru", "Russia, Moscow"],
                "ro1": ["ro", "Romania, Bucharest"],
            },
        }

    def summarize(self, ru_error, control_error=None):
        return self.client._summarize(
            "192.0.2.1:443",
            self.request,
            {
                "ru1": [{"error": ru_error, "time": 0.1}],
                "ro1": [{"error": control_error, "time": 0.1}],
            },
        )

    def test_null_error_is_reachable(self):
        self.assertEqual(self.summarize(None)["verdict"], "clean")

    def test_connection_refused_proves_reachability(self):
        self.assertEqual(self.summarize("Connection refused")["verdict"], "clean")

    def test_open_or_filtered_is_not_treated_as_reachable(self):
        self.assertEqual(self.summarize("Open or filtered")["verdict"], "uncertain")

    def test_ru_timeout_with_live_control_is_blocked(self):
        self.assertEqual(self.summarize("Connection timed out")["verdict"], "blocked")

    def test_absent_api_result_is_not_fabricated_as_timeout(self):
        result = self.client._summarize(
            "192.0.2.1:443",
            self.request,
            {"ro1": [{"error": None, "time": 0.1}]},
        )
        self.assertEqual(result["verdict"], "uncertain")
