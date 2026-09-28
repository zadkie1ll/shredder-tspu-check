import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .domain import Verdict, normalize_verdict


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
        columns = {
            row["name"] for row in self.db.execute("PRAGMA table_info(node_state)")
        }
        for name, sql_type in (
            ("last_full_checked_at", "TEXT"),
            ("last_full_address", "TEXT"),
            ("last_full_verdict", "TEXT"),
        ):
            if name not in columns:
                self.db.execute(
                    f"ALTER TABLE node_state ADD COLUMN {name} {sql_type}"
                )
        self.db.commit()

    def get(self, node_uuid: str):
        return self.db.execute(
            "SELECT * FROM node_state WHERE node_uuid = ?", (node_uuid,)
        ).fetchone()

    def record_check(
        self, node, status: str | Verdict, result: dict
    ) -> None:
        verdict = normalize_verdict(status)
        previous = self.get(node.uuid)
        previous_status = previous["last_status"] if previous else None
        notified_status = previous["last_notified_status"] if previous else None

        # An uncertain observation must never erase the last decisive state.
        stable_status = (
            previous_status if verdict == Verdict.UNCERTAIN else verdict.value
        )
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

    def needs_full_confirmation(self, node, cooldown_hours: int = 24) -> bool:
        row = self.get(node.uuid)
        if row is None or row["last_full_address"] != node.address:
            return True
        value = row["last_full_checked_at"]
        if not value:
            return True
        checked_at = datetime.fromisoformat(value)
        return checked_at <= datetime.now(timezone.utc) - timedelta(
            hours=cooldown_hours
        )

    def record_full_confirmation(self, node, verdict: str | Verdict) -> None:
        normalized = normalize_verdict(verdict)
        self.db.execute(
            """
            UPDATE node_state
            SET last_full_checked_at = ?, last_full_address = ?,
                last_full_verdict = ?
            WHERE node_uuid = ?
            """,
            (_now(), node.address, normalized.value, node.uuid),
        )
        self.db.commit()

    def clear_full_confirmation(self, node_uuid: str) -> None:
        self.db.execute(
            """
            UPDATE node_state
            SET last_full_checked_at = NULL, last_full_address = NULL,
                last_full_verdict = NULL
            WHERE node_uuid = ?
            """,
            (node_uuid,),
        )
        self.db.commit()

    def close(self) -> None:
        self.db.close()
