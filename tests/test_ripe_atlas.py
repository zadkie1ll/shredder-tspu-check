import unittest

from app.domain import Node
from app.ripe_atlas import build_measurement_payload, summarize_results


class RipeAtlasTests(unittest.TestCase):
    def test_private_tls_payload_uses_ip_port_and_client_sni(self):
        node = Node("n1", "Node 1", "192.0.2.10", 8443, ("example.com",))
        payload = build_measurement_payload(node, "example.com", [10, 20])
        definition = payload["definitions"][0]
        self.assertEqual(definition["target"], "192.0.2.10")
        self.assertEqual(definition["port"], 8443)
        self.assertEqual(definition["hostname"], "example.com")
        self.assertFalse(definition["is_public"])
        self.assertEqual(payload["probes"][0]["value"], "10,20")
        self.assertTrue(payload["is_oneoff"])

    def test_majority_tls_failure_is_blocked(self):
        rows = [
            {"prb_id": 1, "method": "TLS"},
            {"prb_id": 2, "err": "connect timeout"},
            {"prb_id": 3, "err": "connect timeout"},
            {"prb_id": 4, "err": "connect timeout"},
            {"prb_id": 5, "err": "connect timeout"},
        ]
        result = summarize_results(rows, minimum_results=5)
        self.assertEqual(result["verdict"], "blocked")
        self.assertEqual(result["availability"], 20)

    def test_too_few_results_are_uncertain(self):
        result = summarize_results(
            [{"prb_id": 1, "err": "timeout"}], minimum_results=5
        )
        self.assertEqual(result["verdict"], "uncertain")
        self.assertEqual(result["reason"], "insufficient_atlas_results")

    def test_seventy_percent_tls_success_is_clean(self):
        rows = [{"prb_id": value, "method": "TLS"} for value in range(7)]
        rows.extend({"prb_id": value, "err": "timeout"} for value in range(7, 10))
        result = summarize_results(rows, minimum_results=5)
        self.assertEqual(result["verdict"], "clean")
        self.assertEqual(result["availability"], 70)
