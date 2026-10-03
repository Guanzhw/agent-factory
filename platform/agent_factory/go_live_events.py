"""Private, append-only local diagnostics; events never establish server receipt."""
from __future__ import annotations

from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any
from uuid import UUID

from .go_diagnostics import safe_diagnostic

_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class GoDiagnosticJournal:
    @classmethod
    def create(cls, path: str | Path, campaign_id: str) -> GoDiagnosticJournal:
        cls._platform_check()
        if not isinstance(campaign_id, str) or not _ID.fullmatch(campaign_id):
            raise ValueError("Invalid diagnostic campaign")
        target = Path(path).absolute()
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW
        descriptor = os.open(target, flags, 0o600)
        os.close(descriptor)
        with closing(sqlite3.connect(target)) as conn:
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript("""
                CREATE TABLE metadata (version INTEGER NOT NULL, campaign_id TEXT NOT NULL);
                CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    utc_time TEXT NOT NULL, ticket_id TEXT NOT NULL, diagnostic TEXT NOT NULL);
                CREATE TRIGGER no_event_update BEFORE UPDATE ON events
                    BEGIN SELECT RAISE(ABORT, 'Append only'); END;
                CREATE TRIGGER no_event_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'Append only'); END;
            """)
            conn.execute("INSERT INTO metadata VALUES (1, ?)", (campaign_id,))
            conn.commit()
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return cls(target)

    @staticmethod
    def _platform_check():
        if os.name != "posix" or not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_DIRECTORY", 0):
            raise ValueError("Diagnostic journal requires POSIX file protection")

    def __init__(self, path: str | Path):
        self._platform_check()
        self.path = Path(path).absolute()
        self._identity = self._file_identity()
        with self._connection() as conn:
            row = conn.execute("SELECT version, campaign_id FROM metadata").fetchall()
            if len(row) != 1 or row[0][0] != 1 or not _ID.fullmatch(row[0][1]):
                raise ValueError("Invalid diagnostic journal")
            self.campaign_id = row[0][1]
            conn.execute("SELECT seq, utc_time, ticket_id, diagnostic FROM events LIMIT 0")

    def _file_identity(self):
        descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
                raise ValueError("Invalid diagnostic file")
            return info.st_dev, info.st_ino
        finally:
            os.close(descriptor)

    @contextmanager
    def _connection(self, *, write: bool = False):
        if self._file_identity() != self._identity:
            raise ValueError("Diagnostic file changed")
        conn = sqlite3.connect(self.path.as_uri() + ("?mode=rw" if write else "?mode=ro"), uri=True)
        try:
            if write:
                conn.execute("PRAGMA synchronous=FULL")
                conn.execute("BEGIN IMMEDIATE")
            if self._file_identity() != self._identity:
                raise ValueError("Diagnostic file changed")
            yield conn
            if self._file_identity() != self._identity:
                raise ValueError("Diagnostic file changed")
            if write:
                conn.commit()
        finally:
            conn.close()

    def record(self, ticket_id: str, phase: str, *, http_status: Any = None,
               response_headers: Any = None, error: Any = None) -> None:
        if type(ticket_id) is not str:
            raise ValueError("Invalid diagnostic ticket")
        if ticket_id != "runner":
            try:
                parsed = UUID(ticket_id)
            except ValueError:
                raise ValueError("Invalid diagnostic ticket") from None
            if parsed.version != 4 or str(parsed) != ticket_id:
                raise ValueError("Invalid diagnostic ticket")
        diagnostic = safe_diagnostic(phase, http_status=http_status,
                                     response_headers=response_headers, error=error)
        with self._connection(write=True) as conn:
            conn.execute("INSERT INTO events (utc_time, ticket_id, diagnostic) VALUES (?, ?, ?)",
                         (datetime.now(timezone.utc).isoformat(), ticket_id,
                          json.dumps(diagnostic, sort_keys=True)))

    def inspect(self) -> dict:
        with self._connection() as conn:
            rows = conn.execute("SELECT seq, utc_time, ticket_id, diagnostic FROM events ORDER BY seq").fetchall()
        return {"campaignId": self.campaign_id, "events": [
            {"sequence": seq, "timestampUtc": utc, "requestId": ticket, **json.loads(value)}
            for seq, utc, ticket, value in rows]}
