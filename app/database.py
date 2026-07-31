from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import Settings


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    original_relative_path TEXT NOT NULL,
    current_relative_path TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'approved', 'skipped', 'missing')),
    proposed_name TEXT,
    ocr_text TEXT,
    selections_json TEXT,
    page_count INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_at TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    before_relative_path TEXT,
    after_relative_path TEXT,
    payload_json TEXT,
    undone INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_actions_document ON actions(document_id);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.settings.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)

    def sync_documents(self) -> dict[str, int]:
        added = 0
        restored = 0
        missing = 0
        with self._lock, self.connect() as connection:
            known_rows = connection.execute(
                "SELECT id, current_relative_path, status FROM documents"
            ).fetchall()
            known = {row["current_relative_path"]: row for row in known_rows}
            disk_paths: set[str] = set()

            for path in sorted(self.settings.input_dir.rglob("*.pdf"), key=lambda p: str(p).lower()):
                if not path.is_file():
                    continue
                relative = path.relative_to(self.settings.input_dir).as_posix()
                disk_paths.add(relative)
                row = known.get(relative)
                if row:
                    if row["status"] == "missing":
                        connection.execute(
                            "UPDATE documents SET status='pending', updated_at=? WHERE id=?",
                            (utc_now(), row["id"]),
                        )
                        restored += 1
                    continue
                now = utc_now()
                connection.execute(
                    """
                    INSERT INTO documents (
                        id, original_relative_path, current_relative_path, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, 'pending', ?, ?)
                    """,
                    (str(uuid.uuid4()), relative, relative, now, now),
                )
                added += 1

            for row in known_rows:
                if row["current_relative_path"] not in disk_paths and row["status"] != "missing":
                    connection.execute(
                        "UPDATE documents SET status='missing', updated_at=? WHERE id=?",
                        (utc_now(), row["id"]),
                    )
                    missing += 1

        return {"added": added, "restored": restored, "missing": missing}

    @staticmethod
    def _document_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        raw = data.pop("selections_json", None)
        data["selections"] = json.loads(raw) if raw else []
        data["original_name"] = Path(data["original_relative_path"]).name
        data["current_name"] = Path(data["current_relative_path"]).name
        return data

    def list_documents(self) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM documents
                ORDER BY lower(original_relative_path), id
                """
            ).fetchall()
        return [self._document_dict(row) for row in rows]

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE id=?", (document_id,)
            ).fetchone()
        return self._document_dict(row) if row else None

    def update_page_count(self, document_id: str, page_count: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE documents SET page_count=?, updated_at=? WHERE id=?",
                (page_count, utc_now(), document_id),
            )

    def save_ocr(
        self,
        document_id: str,
        proposed_name: str,
        ocr_text: str,
        selections: list[dict[str, Any]],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE documents
                SET proposed_name=?, ocr_text=?, selections_json=?, updated_at=?
                WHERE id=?
                """,
                (proposed_name, ocr_text, json.dumps(selections), utc_now(), document_id),
            )

    def mark_approved(
        self,
        document_id: str,
        before_path: str,
        after_path: str,
        proposed_name: str,
        ocr_text: str | None,
        selections: list[dict[str, Any]],
    ) -> None:
        now = utc_now()
        payload = {
            "proposed_name": proposed_name,
            "ocr_text": ocr_text,
            "selections": selections,
        }
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE documents
                SET current_relative_path=?, status='approved', proposed_name=?,
                    ocr_text=?, selections_json=?, approved_at=?, updated_at=?
                WHERE id=?
                """,
                (
                    after_path,
                    proposed_name,
                    ocr_text,
                    json.dumps(selections),
                    now,
                    now,
                    document_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO actions (
                    document_id, action_type, before_relative_path,
                    after_relative_path, payload_json, created_at
                ) VALUES (?, 'rename', ?, ?, ?, ?)
                """,
                (document_id, before_path, after_path, json.dumps(payload), now),
            )

    def mark_skipped(self, document_id: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT current_relative_path FROM documents WHERE id=?", (document_id,)
            ).fetchone()
            if not row:
                return
            connection.execute(
                "UPDATE documents SET status='skipped', updated_at=? WHERE id=?",
                (now, document_id),
            )
            connection.execute(
                """
                INSERT INTO actions (
                    document_id, action_type, before_relative_path,
                    after_relative_path, created_at
                ) VALUES (?, 'skip', ?, ?, ?)
                """,
                (document_id, row["current_relative_path"], row["current_relative_path"], now),
            )

    def latest_undoable_rename(self) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM actions
                WHERE action_type='rename' AND undone=0
                ORDER BY id DESC LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def complete_undo(self, action_id: int, document_id: str, restored_path: str) -> None:
        now = utc_now()
        with self.connect() as connection:
            connection.execute("UPDATE actions SET undone=1 WHERE id=?", (action_id,))
            connection.execute(
                """
                UPDATE documents
                SET current_relative_path=?, status='pending', approved_at=NULL,
                    updated_at=? WHERE id=?
                """,
                (restored_path, now, document_id),
            )
            connection.execute(
                """
                INSERT INTO actions (
                    document_id, action_type, before_relative_path,
                    after_relative_path, payload_json, created_at
                ) VALUES (?, 'undo', ?, ?, ?, ?)
                """,
                (document_id, None, restored_path, json.dumps({"action_id": action_id}), now),
            )

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT a.*, d.current_relative_path
                FROM actions a
                JOIN documents d ON d.id=a.document_id
                ORDER BY a.id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
