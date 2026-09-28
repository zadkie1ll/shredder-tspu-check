import tempfile
import unittest
from pathlib import Path

from app.domain import Node, Verdict
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

    def test_initial_clean_state_is_stored(self):
        self.storage.record_check(
            self.node, Verdict.CLEAN, self.result(Verdict.CLEAN)
        )
        self.assertEqual(self.storage.get(self.node.uuid)["last_status"], "clean")

    def test_uncertain_observation_preserves_last_decisive_state(self):
        self.storage.record_check(self.node, Verdict.CLEAN, self.result(Verdict.CLEAN))
        self.storage.record_check(
            self.node, Verdict.UNCERTAIN, self.result(Verdict.UNCERTAIN)
        )
        self.assertEqual(self.storage.get(self.node.uuid)["last_status"], "clean")

    def test_full_confirmation_is_due_daily_and_cleared_after_recovery(self):
        self.storage.record_check(
            self.node, Verdict.BLOCKED, self.result(Verdict.BLOCKED)
        )
        self.assertTrue(self.storage.needs_full_confirmation(self.node))
        self.storage.record_full_confirmation(self.node, Verdict.BLOCKED)
        self.assertFalse(self.storage.needs_full_confirmation(self.node))
        self.storage.clear_full_confirmation(self.node.uuid)
        self.assertTrue(self.storage.needs_full_confirmation(self.node))
