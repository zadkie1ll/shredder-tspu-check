import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.domain import AlertDecision, AlertKind, Node, Verdict
from app.service import check_all


class FakeRemnawave:
    async def list_nodes(self):
        return [Node("1", "RU-1", "192.0.2.1"), Node("2", "RU-2", "192.0.2.2")]


class FakeCheckHost:
    async def check(self, _address):
        return {
            "verdict": "blocked",
            "reason": "ru_timeout_control_reachable",
            "errors": {},
            "request_id": "check-1",
            "total": 2,
            "failures": 1,
            "service_errors": 0,
            "permanent_link": "https://example.test/check-1",
        }


class FakeStorage:
    def __init__(self):
        self.recorded = []
        self.delivered = []

    def record_check(self, node, verdict, _result):
        self.recorded.append((node.uuid, verdict))
        return AlertDecision(AlertKind.BLOCKED, verdict)

    def mark_alert_delivered(self, node_uuid, status):
        self.delivered.append((node_uuid, status))


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cycle_checks_all_nodes_and_marks_delivered_alerts(self):
        storage = FakeStorage()
        settings = SimpleNamespace(check_concurrency=2)
        with patch("app.service.send_alert", new=AsyncMock()) as sender:
            summary = await check_all(
                settings, FakeRemnawave(), FakeCheckHost(), storage
            )
        self.assertEqual(summary, {"blocked": 2, "nodes": 2})
        self.assertEqual(len(storage.recorded), 2)
        self.assertEqual(len(storage.delivered), 2)
        self.assertEqual(sender.await_count, 2)

    async def test_failed_delivery_is_not_marked_and_probe_stays_blocked(self):
        storage = FakeStorage()
        settings = SimpleNamespace(check_concurrency=1)
        with patch(
            "app.service.send_alert",
            new=AsyncMock(side_effect=RuntimeError("telegram unavailable")),
        ):
            summary = await check_all(
                settings, FakeRemnawave(), FakeCheckHost(), storage
            )
        self.assertEqual(summary["blocked"], 2)
        self.assertEqual(storage.delivered, [])
