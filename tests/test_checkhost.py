import unittest

from app.checkhost import classify_observations
from app.domain import Verdict


def observation(country, *, reachable=False, timeout=False):
    return {
        "country": country,
        "reachable": reachable,
        "is_timeout": timeout,
    }


class CheckHostClassifierTests(unittest.TestCase):
    ru = ("russia",)
    controls = ("romania", "serbia")

    def classify(self, *items):
        return classify_observations(list(items), self.ru, self.controls)

    def test_blocked_requires_ru_timeout_and_live_external_control(self):
        verdict, reason = self.classify(
            observation("Russia, Moscow", timeout=True),
            observation("Russia, Saint Petersburg", timeout=True),
            observation("Romania, Bucharest", reachable=True),
        )
        self.assertEqual(verdict, Verdict.BLOCKED)
        self.assertEqual(reason, "ru_timeout_control_reachable")

    def test_one_reachable_ru_probe_is_clean(self):
        verdict, reason = self.classify(
            observation("Russia, Moscow", timeout=True),
            observation("Russia, Saint Petersburg", reachable=True),
        )
        self.assertEqual(verdict, Verdict.CLEAN)
        self.assertEqual(reason, "ru_reachable")

    def test_global_outage_is_not_reported_as_tspu(self):
        verdict, _ = self.classify(
            observation("Russia, Moscow", timeout=True),
            observation("Romania, Bucharest", timeout=True),
            observation("Serbia, Belgrade", timeout=True),
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)

    def test_missing_probe_result_is_not_a_timeout(self):
        verdict, reason = self.classify(
            observation("Russia, Moscow"),
            observation("Romania, Bucharest", reachable=True),
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertEqual(reason, "insufficient_evidence")

    def test_missing_ru_geo_is_uncertain(self):
        verdict, reason = self.classify(
            observation("Romania, Bucharest", reachable=True)
        )
        self.assertEqual(verdict, Verdict.UNCERTAIN)
        self.assertEqual(reason, "no_ru_probes")
