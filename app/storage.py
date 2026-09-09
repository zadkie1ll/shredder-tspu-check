import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS node_state (
                node_uuid TEXT PRIMARY KEY,
                node_name TEXT NOT NULL,
                address TEXT NOT NULL,
                last_status TEXT,
                last_checked_at TEXT,
                last_result TEXT,
                last_notified_status TEXT
            )
            """
        )
        self.db.commit()

    def get(self, node_uuid: str):
        return self.db.execute(
            "SELECT * FROM node_state WHERE node_uuid = ?", (node_uuid,)
        ).fetchone()

    def save_check(self, node, status: str, result: dict) -> bool:
        previous = self.get(node.uuid)
        previous_status = previous["last_status"] if previous else None
        notified_status = previous["last_notified_status"] if previous else None
        should_notify = status in {"blocked", "clean"} and status != notified_status
        if should_notify:
            notified_status = status

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
                status,
                _now(),
                json.dumps(result, ensure_ascii=False),
                notified_status,
            ),
        )
        self.db.commit()
        return should_notify

