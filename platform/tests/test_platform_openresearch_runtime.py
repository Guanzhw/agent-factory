"""Final native-harness permission checks; no processes or model requests."""
from copy import deepcopy
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from agent_factory.runtime_packages.openresearch_v1.entry import (
    BUILTINS, LOCAL_TOOLS, PERMISSIONS, opencode_config, verify_effective_agent, verify_no_startup_dispatch,
)


class PlatformOpenResearchRuntimeTests(unittest.TestCase):
    def agent(self):
        return {'name': 'build', 'model': {'providerID': 'factory', 'modelID': 'owner-model'},
            'permission': [{'permission': name, 'pattern': '*', 'action': action}
                for name, action in PERMISSIONS.items()],
            'tools': {name: name in LOCAL_TOOLS for name in BUILTINS}}

    def test_native_permissions_without_legacy_tool_merge(self):
        config = opencode_config('synthetic-owner-capability-0123456789')
        self.assertNotIn('tools', config)
        for name in ('factory', 'build', 'plan'):
            self.assertNotIn('tools', config['agent'][name])
        self.assertTrue(verify_effective_agent(self.agent(), 'build')['effectiveToolsVerified'])

    def test_reject_wildcard_order_and_inactive_tools_even_with_correct_config(self):
        agent = self.agent()
        agent['permission'].append({'permission': '*', 'pattern': '*', 'action': 'deny'})
        with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')
        for tool in ('bash', 'read', 'edit'):
            agent = self.agent(); agent['tools'][tool] = False
            with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')

    def test_restart_refuses_original_durable_work_without_mutating_custody(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / 'native.db'
            verify_no_startup_dispatch(path)
            self.assertFalse(path.exists())
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.executescript('''CREATE TABLE chat_queued_messages(id TEXT,session_id TEXT,payload_json TEXT);
                    CREATE TABLE chat_turns(id TEXT,state TEXT);
                    CREATE TABLE runs(id TEXT,status TEXT);
                    CREATE TABLE chat_run_wakeups(run_id TEXT,state TEXT);
                    CREATE TABLE chat_spawns(session_id TEXT,state TEXT);''')
                conn.execute("INSERT INTO runs VALUES ('original-run','done')")
                conn.execute("INSERT INTO chat_turns VALUES ('original-turn','completed')")
                conn.execute("INSERT INTO chat_run_wakeups VALUES ('original-run','delivered')")
                conn.execute("INSERT INTO chat_spawns VALUES ('original-child','done')")
            verify_no_startup_dispatch(path)
            for statement, undo in (
                ("INSERT INTO chat_queued_messages VALUES ('original-goal','original-chat','{}')", 'DELETE FROM chat_queued_messages'),
                ("UPDATE chat_turns SET state='running'", "UPDATE chat_turns SET state='completed'"),
                ("UPDATE runs SET status='running'", "UPDATE runs SET status='done'"),
                ("UPDATE chat_run_wakeups SET state='pending'", "UPDATE chat_run_wakeups SET state='delivered'"),
                ("UPDATE chat_spawns SET state='waking'", "UPDATE chat_spawns SET state='done'")):
                with closing(sqlite3.connect(path)) as conn, conn: conn.execute(statement)
                original = hashlib.sha256(path.read_bytes()).hexdigest()
                with self.assertRaises(ValueError): verify_no_startup_dispatch(path)
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original)
                with closing(sqlite3.connect(path)) as conn, conn: conn.execute(undo)
            with closing(sqlite3.connect(path)) as conn, conn: conn.execute('DROP TABLE chat_spawns')
            with self.assertRaises(ValueError): verify_no_startup_dispatch(path)

    def test_reject_undeclared_external_tool_and_provider_fallback(self):
        agent = self.agent(); agent['tools']['unknown_external'] = True
        with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')
        for tool in ('webfetch', 'task', 'skill'):
            agent = deepcopy(self.agent())
            agent['permission'].append({'permission': tool, 'pattern': '*', 'action': 'allow'})
            agent['tools'][tool] = True
            with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')
        agent = self.agent(); agent['model']['providerID'] = 'fallback'
        with self.assertRaises(ValueError): verify_effective_agent(agent, 'build')
