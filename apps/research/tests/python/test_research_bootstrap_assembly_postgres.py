"""Real assembled preparation through native PostgreSQL; no ML or device work."""
import hashlib
import os
from pathlib import Path
import sys
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient
from agent_factory_server.main import create_app
from agent_factory_research.research_bootstrap_assembly import prepare_application, REVISION
from agent_factory.process_runtime_profile import publish_process_application, TOOL_NAME
import test_research_preparation_postgres as fixture
from test_research_preparation_harness import tokenizer


@unittest.skipUnless(sys.platform == 'linux' and os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PG/Linux')
class BootstrapAssemblyPostgresTests(unittest.TestCase):
    setUp = fixture.PreparationPostgresTests.setUp
    request = fixture.PreparationPostgresTests.request
    until = fixture.PreparationPostgresTests.until
    lease = fixture.PreparationPostgresTests.lease
    cleanup_processes = fixture.PreparationPostgresTests.cleanup_processes
    test_original_native_export_import_lost_ack_and_reopen = fixture.PreparationPostgresTests.test_original_native_export_import_lost_ack_and_reopen

    def submit(self):
        def post(path, body):
            return self.request('POST', path, {'requestId': str(uuid4()), **body})
        proposal = post('/compositions/proposals', {'goal': 'Run the pinned synthetic process once',
            'mode': 'controlled-fixture', 'applicationRef': {
                key: self.application[key] for key in ('id', 'version', 'sha256')}})
        self.assertEqual(proposal['candidate']['status'], 'ready', proposal)
        plan = post('/compositions/proposals/' + proposal['id'] + '/accept', {})
        self.assertEqual(plan['tools'], [TOOL_NAME])
        self.assertEqual(plan['policy'], 'member-self-service')
        return post('/instances', {'planId': plan['id']}), plan

    def start(self):
        program = self.root / 'program'; program.mkdir(mode=0o700)
        custody = self.root / 'custody'; custody.mkdir(mode=0o700)
        info = program.stat()
        executable = Path(sys.executable).resolve()
        bundle = prepare_application(app_factory=create_app, db_url=self.database.url, workspace=self.root,
            program_root=program, program_identity={'device': info.st_dev, 'inode': info.st_ino},
            custody_root=custody, executable=str(executable),
            executable_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
            tokenizer_json=tokenizer(), preparation_manifest_sha256='b'*64)
        self.app, self.state = bundle['app'], bundle['state']
        self.settings, self.bootstrap = bundle['settings'], bundle['providerStore']
        self.provider = bundle['target'].provider
        self.spec, self.limits, self.driver = self.provider.spec, self.provider.limits, self.provider.driver
        self.preparation = bundle['preparation']
        self.store, self.auth = self.state['store'], self.state['auth']
        for engine in (self.bootstrap.engine, self.store.engine, self.store.native_db.db_engine):
            self.addCleanup(engine.dispose)
        self.assertEqual(self.settings.policy_revision, REVISION)
        self.assertEqual(self.settings.runtime_tool_contract, 'research-bootstrap-v1')
        self.assertFalse(bundle['target'].synthetic_fixture)
        self.assertEqual(self.settings.temporary_policy, 'member-self-service')
        self.assertEqual(self.settings.material_review_mode, 'member-self-service')
        self.target_ref = 'preparation'
        self.application = publish_process_application(self.state, target_ref=self.target_ref,
            author='alice')
        self.client = TestClient(self.app).__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.addCleanup(self.cleanup_processes)
