import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.domain import Node, Verdict
from app.service import check_all, format_cycle_report


class FakeRemnawave:
    async def list_nodes(self):
        return [Node("1", "RU-1", "192.0.2.1"), Node("2", "RU-2", "192.0.2.2")]


class FakeStorage:
    def __init__(self, needs_full=False):
        self.recorded = []
        self.full = []
        self.needs_full = needs_full

    def record_check(self, node, verdict, _result):
        self.recorded.append((node.uuid, verdict))

    def needs_full_confirmation(self, _node):
        return self.needs_full

    def record_full_confirmation(self, node, verdict):
        self.full.append((node.uuid, verdict))

    def clear_full_confirmation(self, _node_uuid):
        pass


class FakeAtlas:
    def __init__(self):
        self.calls = []

    async def check(self, node, light=None):
        self.calls.append((node.uuid, light))
        return {
            "verdict": "blocked",
            "reason": "ripe_tls_blocked",
            "errors": {},
            "request_id": "ripe:1",
            "total": 5,
            "failures": 4,
            "service_errors": 0,
            "permanent_link": "https://atlas.ripe.net/measurements/1/",
        }


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_sends_one_report_for_all_nodes(self):
        storage = FakeStorage()
        settings = SimpleNamespace(check_concurrency=2)
        with patch("app.service.send_message", new=AsyncMock()) as sender:
            summary = await check_all(
                settings, FakeRemnawave(), FakeAtlas(), storage
            )
        self.assertEqual(summary, {"blocked": 2, "nodes": 2})
        self.assertEqual(len(storage.recorded), 2)
        self.assertEqual(sender.await_count, 1)
        report = sender.await_args.args[1]
        self.assertIn("RU-1 · 192.0.2.1", report)
        self.assertIn("RU-2 · 192.0.2.2", report)

    async def test_failed_summary_delivery_does_not_break_cycle(self):
        storage = FakeStorage()
        settings = SimpleNamespace(check_concurrency=1)
        with patch(
            "app.service.send_message",
            new=AsyncMock(side_effect=RuntimeError("telegram unavailable")),
        ):
            summary = await check_all(
                settings, FakeRemnawave(), FakeAtlas(), storage
            )
        self.assertEqual(summary["blocked"], 2)

    async def test_missing_atlas_is_reported_as_no_data(self):
        storage = FakeStorage()
        settings = SimpleNamespace(check_concurrency=2)
        with patch("app.service.send_message", new=AsyncMock()) as sender:
            summary = await check_all(
                settings, FakeRemnawave(), None, storage
            )
        self.assertEqual(summary, {"uncertain": 2, "nodes": 2})
        sender.assert_awaited_once()

    async def test_blocked_node_gets_full_confirmation(self):
        storage = FakeStorage(needs_full=True)
        atlas = FakeAtlas()
        settings = SimpleNamespace(check_concurrency=2)
        with patch("app.service.send_message", new=AsyncMock()):
            await check_all(settings, FakeRemnawave(), atlas, storage)
        self.assertEqual(atlas.calls.count(("1", False)), 1)
        self.assertEqual(atlas.calls.count(("2", False)), 1)
        self.assertEqual(len(storage.full), 2)

    def test_report_puts_blocked_nodes_first(self):
        nodes = [
            Node("1", "Clean", "192.0.2.1"),
            Node("2", "Blocked", "192.0.2.2"),
        ]
        report = format_cycle_report([
            (nodes[0], Verdict.CLEAN, {}),
            (nodes[1], Verdict.BLOCKED, {}),
        ])
        self.assertLess(report.index("Blocked"), report.index("Clean"))
