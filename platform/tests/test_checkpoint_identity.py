"""Bounded checkpoint hashing; no checkpoint code or objects are loaded."""
import hashlib
import json
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, event, text

from agent_factory.store import Store


class CheckpointIdentityTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        self.store = SimpleNamespace(engine=self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE af_artifacts(id TEXT,task_id TEXT,body TEXT,content BLOB)"))

    def seed(self, raw):
        body = {"id": "artifact", "jobId": "task", "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO af_artifacts VALUES('artifact','task',:body,:raw)"),
                               {"body": json.dumps(body), "raw": raw})
        return body

    def test_multiple_bounded_chunks_and_original_identity(self):
        raw = b"synthetic checkpoint" * 120000
        body = self.seed(raw)
        chunks = []
        def inspect(_conn, _cursor, statement, parameters, _context, _many):
            if "substr(content" in statement:
                chunks.append(parameters[1])
        event.listen(self.engine, "before_cursor_execute", inspect)
        metadata, identity = Store.artifact_identity(self.store, "task", "artifact", len(raw))
        self.assertEqual(metadata, body)
        self.assertEqual(identity, {"sha256": body["sha256"], "sizeBytes": len(raw)})
        self.assertGreater(len(chunks), 1)
        self.assertLessEqual(max(chunks), 1024 * 1024)

    def test_bound_owner_scope_and_corruption_fail_closed(self):
        self.seed(b"synthetic")
        for bound in (True, 0, 2 * 1024**3 + 1):
            with self.assertRaises(ValueError):
                Store.artifact_identity(self.store, "task", "artifact", bound)
        with self.assertRaises(HTTPException):
            Store.artifact_identity(self.store, "other-task", "artifact", 100)
        with self.assertRaises(HTTPException):
            Store.artifact_identity(self.store, "task", "artifact", 1)
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE af_artifacts SET content=:raw"), {"raw": b"tampered!"})
        with self.assertRaises(HTTPException):
            Store.artifact_identity(self.store, "task", "artifact", 100)
