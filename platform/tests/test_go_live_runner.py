import os
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select

from agent_factory.go_development import APPLICATION_ID, MODEL_ADAPTER_IDS
from pg_fixture import IsolatedPostgres

_RUNNER = Path(__file__).resolve().parents[2] / 'scripts' / 'run_go_live_validation.py'
spec = importlib.util.spec_from_file_location('go_validation_runner', _RUNNER)
assert spec is not None and spec.loader is not None
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


@unittest.skipUnless(os.name == "posix", "POSIX private diagnostic files required")
class GoLiveRunnerTests(unittest.TestCase):
    def arguments(self, directory, **changes):
        values = dict(evidence_directory=directory, execute_authorized_live=True,
                      use_balance_off=True, auto_reload_off=True, campaign_id='runner-test',
                      confirmation_id='attestation', database_url='unused',
                      exact_model_sequence='deepseek-v4-flash,gpt-6-luna')
        values.update(changes)
        return argparse.Namespace(**values)

    def test_new_execution_requires_explicit_exact_sequence_before_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            for sequence in (None, 'deepseek-flash,gpt-6-luna', 'gpt-6-luna,deepseek-v4-flash'):
                with patch.object(runner, 'credential', side_effect=AssertionError), \
                     patch.object(runner.GoLiveCampaign, 'create') as create:
                    with self.assertRaises(RuntimeError):
                        runner.run(self.arguments(directory, exact_model_sequence=sequence))
                    create.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_legacy_inspection_never_creates_campaign_or_reads_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'campaign.sqlite'
            path.write_bytes(b'legacy')
            before = path.read_bytes(), path.stat().st_mtime_ns
            with patch.object(runner, 'credential', side_effect=AssertionError), \
                 patch.object(runner, 'GoLiveCampaign') as campaign:
                campaign.return_value.inspect.return_value = {'remaining': 0}
                result = runner.run(self.arguments(directory, exact_model_sequence=None))
                campaign.create.assert_not_called()
                self.assertEqual(result['execution'], 'inspection-only')
            self.assertEqual(before, (path.read_bytes(), path.stat().st_mtime_ns))
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_setup_failure_is_durable_without_logging_or_credential(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runner, 'credential', side_effect=AssertionError), \
                 patch.object(runner, 'Settings', side_effect=ValueError('private-value')):
                result = runner.run(self.arguments(directory))
            self.assertEqual(result['status'], 'stopped')
            self.assertNotIn('private-value', json.dumps(result))
            events = result['campaign']['diagnostics']['events']
            self.assertEqual([e['phase'] for e in events], ['RUNNER_STARTED', 'RUNNER_FAILED', 'RUNNER_STOPPED'])
            before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                      for p in Path(directory).iterdir() if p.is_file()}
            inspected = runner.run(self.arguments(directory, exact_model_sequence=None))
            self.assertEqual(inspected['execution'], 'inspection-only')
            self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                                     for p in Path(directory).iterdir() if p.is_file()})

    def test_journal_and_stop_failures_preserve_original_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runner, 'credential', side_effect=AssertionError) as credential, \
                 patch.object(runner, 'Settings', side_effect=ValueError('original-private')), \
                 patch.object(runner.GoLiveCampaign, 'create') as create, \
                 patch.object(runner, 'GoDevelopmentModel') as provider:
                campaign = create.return_value
                campaign.journal.record.side_effect = [None, OSError('storage-private'), OSError('storage-private')]
                campaign.stop.side_effect = OSError('stop-private')
                campaign.inspect.side_effect = [OSError('inspect-private'), {'remaining': 6}]
                result = runner.run(self.arguments(directory))
                credential.assert_not_called()
                provider.assert_not_called()
                self.assertEqual(result['diagnostic']['errorType'], 'ValueError')
                self.assertEqual(result['campaign'], {'remaining': 6})
                self.assertEqual([row['operation'] for row in result['diagnosticPersistence']],
                                 ['campaign-stop', 'RUNNER_FAILED', 'RUNNER_STOPPED', 'campaign-inspect'])
                self.assertEqual(campaign.stop.call_count, 1)
                self.assertEqual(campaign.journal.record.call_count, 3)
                campaign.inspect.assert_called_with(include_diagnostics=False)
                self.assertNotIn('private', json.dumps(result))
                self.assertEqual(json.loads((Path(directory) / 'evidence.json').read_text()), result)

    @unittest.skipUnless(os.getenv("FACTORY_TEST_DATABASE_URL"), "Requires disposable loopback PostgreSQL")
    def test_member_publication_reaches_first_smoke_without_review_or_privilege_escalation(self):
        class StopBeforeDispatch(Exception):
            pass

        states = []
        original_create = runner.create_app

        def capture_application(settings):
            application = original_create(settings)
            states.append(application.app.state.factory)
            return application

        with tempfile.TemporaryDirectory() as directory, \
                IsolatedPostgres(os.environ["FACTORY_TEST_DATABASE_URL"]) as database, \
                patch.object(runner, "create_app", side_effect=capture_application), \
                patch.object(runner, "credential", side_effect=AssertionError("No provider credential needed")) as credential, \
                patch.object(runner, "GoDevelopmentModel", side_effect=StopBeforeDispatch) as model:
            result = runner.run(self.arguments(directory, database_url=database.url))
            self.assertEqual(result["status"], "stopped")
            self.assertEqual(result["stoppedPhase"], runner.MODELS[0] + ":smoke")
            self.assertEqual(result["diagnostic"]["errorType"], "StopBeforeDispatch")
            self.assertEqual(model.call_count, 1)
            self.assertEqual(model.call_args.kwargs["model_id"], runner.MODELS[0])
            credential.assert_not_called()
            state = states[0]
            governance, applications, auth = state["material_governance"], state["applications"], state["auth"]
            self.assertTrue(governance.member_publication())
            for owner in ("alice", "bob"):
                auth.require(owner, "run")
                with self.assertRaises(HTTPException) as denied:
                    auth.require(owner, "agent_os:admin")
                self.assertEqual(denied.exception.status_code, 403)
            store = state["store"]
            # The runner has already disposed its engines; reopen only for local
            # publication evidence and release that connection before DB cleanup.
            try:
                with store.engine.connect() as connection:
                    self.assertEqual(list(connection.execute(select(governance.reviews))), [])
                    self.assertEqual(list(connection.execute(select(applications.reviews))), [])
                    materials = list(connection.execute(select(governance.versions).where(
                        governance.versions.c.material_id.in_(["go-development-" + name for name in MODEL_ADAPTER_IDS]))).mappings())
                    self.assertEqual(len(materials), len(MODEL_ADAPTER_IDS))
                    self.assertTrue(all(row["author_id"] == "alice" and row["state"] == "published" for row in materials))
                    application = connection.execute(select(applications.states).where(
                        applications.states.c.id == APPLICATION_ID)).mappings().one()
                    self.assertEqual((application["author_id"], application["state"]), ("alice", "published"))
            finally:
                store.engine.dispose()
                store.native_db.db_engine.dispose()

    def test_started_journal_failure_prevents_factory_setup(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runner, 'credential', side_effect=AssertionError) as credential, \
                 patch.object(runner, 'Settings') as settings, \
                 patch.object(runner.GoLiveCampaign, 'create') as create:
                campaign = create.return_value
                campaign.journal.record.side_effect = OSError('private')
                campaign.inspect.return_value = {'remaining': 6}
                result = runner.run(self.arguments(directory))
                credential.assert_not_called()
                settings.assert_not_called()
                self.assertEqual(result['diagnostic']['errorType'], 'OSError')
                self.assertEqual(result['status'], 'stopped')
                campaign.stop.assert_called_once_with('UNKNOWN')
                self.assertNotIn('private', json.dumps(result))
