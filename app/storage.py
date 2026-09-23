import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .domain import AlertDecision, AlertKind, Verdict, normalize_verdict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS node_state (
                node_uuid TEXT PRIMARY KEY,
                node_name TEXT NOT NULL,
                address TEXT NOT NULL,
                last_status TEXT,
                last_checked_at TEXT,
                last_result TEXT,
                last_notified_status TEXT
            )
            """)
        self.db.commit()

    def get(self, node_uuid: str):
        return self.db.execute(
            "SELECT * FROM node_state WHERE node_uuid = ?", (node_uuid,)
        ).fetchone()

    def record_check(
        self, node, status: str | Verdict, result: dict
    ) -> AlertDecision | None:
        verdict = normalize_verdict(status)
        previous = self.get(node.uuid)
        previous_status = previous["last_status"] if previous else None
        notified_status = previous["last_notified_status"] if previous else None

        decision = None
        if verdict == Verdict.BLOCKED and notified_status != Verdict.BLOCKED.value:
            decision = AlertDecision(AlertKind.BLOCKED, verdict)
        elif verdict == Verdict.CLEAN and notified_status == Verdict.BLOCKED.value:
            decision = AlertDecision(AlertKind.RECOVERED, verdict)

        # An uncertain observation must never erase the last decisive state.
        stable_status = (
            previous_status if verdict == Verdict.UNCERTAIN else verdict.value
        )
        # The first healthy observation establishes a quiet baseline. It is
        # not a recovery notification because no outage was observed before it.
        if previous is None and verdict == Verdict.CLEAN:
            notified_status = Verdict.CLEAN.value

        self.db.execute(
            """
            INSERT INTO node_state
                (node_uuid, node_name, address, last_status, last_checked_at,
                 last_result, last_notified_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(node_uuid) DO UPDATE SET
                node_name=excluded.node_name,
                address=excluded.address,
                last_status=excluded.last_status,
                last_checked_at=excluded.last_checked_at,
                last_result=excluded.last_result,
                last_notified_status=excluded.last_notified_status
            """,
            (
                node.uuid,
                node.name,
                node.address,
                stable_status,
                _now(),
                json.dumps(result, ensure_ascii=False),
                notified_status,
            ),
        )
        self.db.commit()
        return decision

    def mark_alert_delivered(self, node_uuid: str, status: str | Verdict) -> None:
        verdict = normalize_verdict(status)
        if verdict == Verdict.UNCERTAIN:
            raise ValueError("uncertain verdict cannot be marked as notified")
        self.db.execute(
            "UPDATE node_state SET last_notified_status = ? WHERE node_uuid = ?",
            (verdict.value, node_uuid),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()
