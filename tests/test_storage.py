import tempfile
import unittest
from pathlib import Path

from app.domain import AlertKind, Node, Verdict
from app.storage import Storage


class StorageTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.storage = Storage(str(Path(self.tempdir.name) / "state.sqlite3"))
        self.node = Node("node-1", "Russia 1", "192.0.2.10")

    def tearDown(self):
        self.storage.close()
        self.tempdir.cleanup()

    def result(self, verdict):
        return {"verdict": verdict.value}

    def test_initial_clean_state_is_quiet(self):
        decision = self.storage.record_check(
            self.node, Verdict.CLEAN, self.result(Verdict.CLEAN)
        )
        self.assertIsNone(decision)
        self.assertEqual(self.storage.get(self.node.uuid)["last_status"], "clean")

    def test_failed_alert_is_retried_until_marked_delivered(self):
        first = self.storage.record_check(
            self.node, Verdict.BLOCKED, self.result(Verdict.BLOCKED)
        )
        retry = self.storage.record_check(
            self.node, Verdict.BLOCKED, self.result(Verdict.BLOCKED)
        )
        self.assertEqual(first.kind, AlertKind.BLOCKED)
        self.assertEqual(retry.kind, AlertKind.BLOCKED)

        self.storage.mark_alert_delivered(self.node.uuid, Verdict.BLOCKED)
        self.assertIsNone(
            self.storage.record_check(
                self.node, Verdict.BLOCKED, self.result(Verdict.BLOCKED)
            )
        )

    def test_recovery_is_emitted_only_after_delivered_block_alert(self):
        self.storage.record_check(
            self.node, Verdict.BLOCKED, self.result(Verdict.BLOCKED)
        )
        self.storage.mark_alert_delivered(self.node.uuid, Verdict.BLOCKED)
        decision = self.storage.record_check(
            self.node, Verdict.CLEAN, self.result(Verdict.CLEAN)
        )
        self.assertEqual(decision.kind, AlertKind.RECOVERED)

    def test_uncertain_observation_preserves_last_decisive_state(self):
        self.storage.record_check(self.node, Verdict.CLEAN, self.result(Verdict.CLEAN))
        self.storage.record_check(
            self.node, Verdict.UNCERTAIN, self.result(Verdict.UNCERTAIN)
        )
        self.assertEqual(self.storage.get(self.node.uuid)["last_status"], "clean")
