from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("apple_git.store")


class SQLiteStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is not None:
                return self._conn
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._conn = conn
            return conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None

    def bootstrap(self) -> None:
        conn = self._connect()
        with self._lock:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS issue_mappings (
                    reminder_id TEXT PRIMARY KEY,
                    github_issue_number INTEGER NOT NULL,
                    github_pr_number INTEGER,
                    section TEXT NOT NULL,
                    reminder_title TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_issue_mappings_issue ON issue_mappings(github_issue_number);
                CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
                """
            )
            conn.commit()

    @staticmethod
    def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {k: row[k] for k in row.keys()}

    def upsert_issue_mapping(
        self,
        reminder_id: str,
        github_issue_number: int,
        section: str,
        reminder_title: str,
        github_pr_number: int | None = None,
    ) -> None:
        conn = self._connect()
        with self._lock:
            conn.execute(
                """
                INSERT INTO issue_mappings(reminder_id, github_issue_number, github_pr_number, section, reminder_title)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(reminder_id) DO UPDATE SET
                    github_issue_number = excluded.github_issue_number,
                    github_pr_number = excluded.github_pr_number,
                    section = excluded.section,
                    reminder_title = excluded.reminder_title,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (reminder_id, github_issue_number, github_pr_number, section, reminder_title),
            )
            conn.commit()

    def get_mapping_by_reminder_id(self, reminder_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM issue_mappings WHERE reminder_id = ?",
                (reminder_id,),
            ).fetchone()
            return self._row_to_dict(row)

    def get_mapping_by_issue_number(self, github_issue_number: int) -> dict[str, Any] | None:
        conn = self._connect()
        with self._lock:
            row = conn.execute(
                "SELECT * FROM issue_mappings WHERE github_issue_number = ?",
                (github_issue_number,),
            ).fetchone()
            return self._row_to_dict(row)

    def list_mappings(self, section: str | None = None) -> list[dict[str, Any]]:
        conn = self._connect()
        with self._lock:
            if section:
                rows = conn.execute(
                    "SELECT * FROM issue_mappings WHERE section = ? ORDER BY updated_at DESC",
                    (section,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM issue_mappings ORDER BY updated_at DESC"
                ).fetchall()
            return [self._row_to_dict(row) for row in rows if row is not None]

    def update_pr_number(self, reminder_id: str, github_pr_number: int) -> bool:
        conn = self._connect()
        with self._lock:
            cursor = conn.execute(
                "UPDATE issue_mappings SET github_pr_number = ?, updated_at = CURRENT_TIMESTAMP WHERE reminder_id = ?",
                (github_pr_number, reminder_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def update_section(self, reminder_id: str, section: str) -> bool:
        conn = self._connect()
        with self._lock:
            cursor = conn.execute(
                "UPDATE issue_mappings SET section = ?, updated_at = CURRENT_TIMESTAMP WHERE reminder_id = ?",
                (section, reminder_id),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_mapping(self, reminder_id: str) -> bool:
        conn = self._connect()
        with self._lock:
            cursor = conn.execute(
                "DELETE FROM issue_mappings WHERE reminder_id = ?",
                (reminder_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def create_event(self, event_id: str, event_type: str, payload: dict[str, Any]) -> None:
        conn = self._connect()
        with self._lock:
            conn.execute(
                """
                INSERT INTO events(event_id, event_type, payload_json)
                VALUES(?, ?, ?)
                """,
                (event_id, event_type, json.dumps(payload)),
            )
            conn.commit()

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._connect()
        with self._lock:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            events = []
            for row in rows:
                data = self._row_to_dict(row)
                if data is None:
                    continue
                try:
                    data["payload"] = json.loads(data.pop("payload_json", "{}"))
                except json.JSONDecodeError:
                    data["payload"] = {}
                events.append(data)
            return events
