"""Ephemeral private database authentication routing; synthetic values, no DB."""
from contextlib import redirect_stderr, redirect_stdout
import importlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call, patch

import test_run_research_candidate as fixture

runner = fixture.runner


@unittest.skipUnless(sys.platform == 'linux', 'Private filesystem/journal require Linux')
class CandidateDatabaseAuthTests(unittest.TestCase):
    def setUp(self):
        fixture.CandidateRunnerTests.setUp(self)
        self.database = importlib.import_module('research_candidate_database')
        self.anchor = patch.object(self.database, 'anchor_database').start()
        bootstrap = importlib.import_module('bootstrap_research_control')
        self.read = patch.object(bootstrap, 'read_database_url', wraps=bootstrap.read_database_url).start()

    def override(self, name='ephemeral-db'):
        path = self.root / name
        runner.write_private(path, b'postgresql+psycopg://synthetic:synthetic-password@127.0.0.1:5432/synthetic')
        return str(path)

    def call(self, argv, run):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = runner.main(argv, run=run)
        return code, out.getvalue(), err.getvalue()

    def test_strict_arguments_reject_duplicate_unknown_missing_and_misordered_options(self):
        base = ['--config', str(self.path)]
        invalid = [base + ['--database-url-file'], base + ['--database-url-file', '/synthetic/a',
            '--database-url-file', '/synthetic/b'], base + ['--unknown', '/synthetic/a'],
            ['--database-url-file', '/synthetic/a', *base], base + ['--config', str(self.path)],
            ['--recover', '--recover', *base], base + ['--database-url-file', 'relative'],
            base + ['--database-url-file', '/synthetic/../private']]
        for argv in invalid:
            run = Mock()
            with self.subTest(argv=argv):
                self.assertEqual(self.call(argv, run), (2, '', 'RESEARCH_CANDIDATE_STOPPED\n'))
                run.assert_not_called()
        self.assertFalse(Path(self.config['workspace']).exists())

    def test_override_is_transient_and_journal_identity_survives_different_override_path(self):
        first, second = self.override('db-first'), self.override('db-second')
        retained_before = {field: Path(self.config[field]).read_bytes() for field in
            ('baselineConfigFile', 'baselineEvaluationReceiptFile', 'baselineRunConfigFile')}
        config_before = self.path.read_bytes()
        inputs = runner.load_inputs(self.config)
        seen = []
        def execute(config, workspace, progress, journal, *, database_url=None):
            seen.append(database_url)
            self.assertEqual(config, self.config)
            self.assertEqual(journal.snapshot()['identity'], inputs['identity'])
        self.assertEqual(self.call(['--config', str(self.path), '--database-url-file', first], execute),
                         (0, 'RESEARCH_CANDIDATE_COMPLETED_PRIVATE_EVIDENCE\n', ''))
        workspace = Path(self.config['workspace'])
        journal_before = (workspace / 'candidate-journal.json').read_bytes()
        recovery = importlib.import_module('research_candidate_recover_command')
        def recover(config, reopened_inputs, journal, *, database_url=None):
            seen.append(database_url)
            self.assertEqual(reopened_inputs['identity'], inputs['identity'])
            self.assertEqual(journal.snapshot()['identity'], inputs['identity'])
            self.assertFalse(journal.fresh)
            return {'cleanupConfirmed': True}
        with patch.object(recovery, 'recover', side_effect=recover):
            self.assertEqual(self.call(['--recover', '--config', str(self.path), '--database-url-file', second], Mock()),
                             (0, 'RESEARCH_CANDIDATE_ORIGINAL_STOP_CONFIRMED\n', ''))
        self.assertEqual(seen, [item.args[0] for item in self.anchor.call_args_list])
        self.assertEqual(self.read.call_args_list, [call(first), call(second)])
        self.assertEqual(self.anchor.call_count, 2)
        self.assertEqual((workspace / 'candidate-journal.json').read_bytes(), journal_before)
        self.assertEqual(self.path.read_bytes(), config_before)
        for field, raw in retained_before.items():
            self.assertEqual(Path(self.config[field]).read_bytes(), raw)
        for record in workspace.glob('*.json'):
            raw = record.read_bytes()
            self.assertNotIn(first.encode(), raw)
            self.assertNotIn(second.encode(), raw)
            self.assertNotIn(b'synthetic-password', raw)
        self.assertEqual(runner.load_inputs(self.config)['identity'], inputs['identity'])

    def test_override_failure_keeps_fixed_public_error_without_path_or_value(self):
        path = self.override()
        run = Mock(side_effect=ValueError(path + ' synthetic-password'))
        self.assertEqual(self.call(['--config', str(self.path), '--database-url-file', path], run),
                         (2, '', 'RESEARCH_CANDIDATE_STOPPED\n'))
        run.assert_called_once()
        for record in Path(self.config['workspace']).glob('*.json'):
            self.assertNotIn(b'synthetic-password', record.read_bytes())
            self.assertNotIn(path.encode(), record.read_bytes())

    def test_json_config_cannot_persist_the_override(self):
        with self.assertRaises(ValueError):
            runner.config_from_bytes(runner.canonical({**self.config, 'databaseUrlFile': self.override()}))
        self.assertNotIn('databaseUrlFile', json.loads(self.path.read_bytes()))

    def test_baseline_authorization_accepts_resolved_url_without_reading_original_secret_file(self):
        authority = importlib.import_module('research_candidate_baseline')
        bootstrap = importlib.import_module('bootstrap_research_control')
        state_module = importlib.import_module('research_candidate_state')
        inputs = runner.load_inputs(self.config)
        captured = {'receipt': inputs['baselineReceipt'], 'runConfig': inputs['baselineRunConfig'],
                    'contract': {'comparisonManifest': self.manifest}, 'snapshots': {}}
        resolved = 'postgresql+psycopg://synthetic:in-memory-only@127.0.0.1:5432/synthetic'
        class StopBeforeConnection(Exception):
            pass
        with patch.object(authority, 'build_baseline_snapshots', return_value=captured), \
             patch.object(bootstrap, 'read_database_url', side_effect=AssertionError('NO_SECOND_SECRET_READ')) as read, \
             patch.object(state_module, 'open_state', side_effect=StopBeforeConnection) as opened:
            with self.assertRaises(StopBeforeConnection):
                authority.authorize_baseline(inputs, database_url=resolved)
        read.assert_not_called()
        self.assertEqual(opened.call_args.args[0].db_url, resolved)

    def test_direct_execute_resolves_once_and_reuses_url_for_anchor_auth_and_preparation(self):
        from agent_factory import research_bootstrap_assembly, research_local_driver, research_profile
        from agent_factory import research_device_observer
        authority = importlib.import_module('research_candidate_baseline')
        inputs = runner.load_inputs(self.config)
        workspace = Path(self.config['workspace']); workspace.mkdir(mode=0o700)
        journal = Mock(snapshot=Mock(return_value={'identity': inputs['identity']}),
                       remaining=Mock(return_value=1800))
        override = self.override()
        class StopBeforePreparation(Exception):
            pass
        with patch.object(runner, 'load_inputs', return_value=inputs), \
             patch.object(runner, 'runtime_identity'), \
             patch.object(runner, 'read_private', return_value=b'synthetic-source'), \
             patch.object(authority, 'authorize_baseline', return_value=inputs['observation']) as authorize, \
             patch.object(research_profile, 'verify_upstream_source'), \
             patch.object(research_local_driver, 'derive_local_identities', return_value={'identities': {
                 'candidate': {'sha256': 'f' * 64}, 'baseline': {'sha256': self.observation['variantSha256']}}}), \
             patch.object(research_device_observer, 'NvidiaSmiObserver'), \
             patch.object(research_bootstrap_assembly, 'prepare_application', side_effect=StopBeforePreparation) as prepare:
            with self.assertRaises(StopBeforePreparation):
                runner.execute(self.config, workspace, Mock(), journal, database_url_file=override)
        self.read.assert_called_once_with(override)
        self.anchor.assert_called_once()
        resolved = self.anchor.call_args.args[0]
        authorize.assert_called_once_with(inputs, database_url=resolved)
        self.assertEqual(prepare.call_args.kwargs['db_url'], resolved)
        self.assertNotIn(override.encode(), (workspace / 'preparation-recovery.json').read_bytes())
        self.assertEqual(inputs['baselineConfig'], self.baseline)

    def test_direct_recovery_resolves_once_and_uses_same_database_for_reopened_state(self):
        command = importlib.import_module('research_candidate_recover_command')
        state_module = importlib.import_module('research_candidate_state')
        inputs = runner.load_inputs(self.config)
        workspace = Path(self.config['workspace']); workspace.mkdir(mode=0o700)
        journal = Mock(fresh=False, snapshot=Mock(return_value={'identity': inputs['identity'], 'stages': {}}))
        override = self.override()
        with patch.object(state_module, 'open_state') as opened:
            report = command.recover(self.config, inputs, journal, database_url_file=override)
        self.read.assert_called_once_with(override)
        self.anchor.assert_called_once()
        self.assertEqual(opened.call_args.args[0].db_url, self.anchor.call_args.args[0])
        self.assertFalse(report['cleanupConfirmed'])
        self.assertEqual(report['newAttempts'], 0)

    def test_database_preflight_checks_anchor_without_workspace_or_execution(self):
        override = self.override()
        run = Mock()
        argv = ['--database-preflight', '--config', str(self.path), '--database-url-file', override]
        self.assertEqual(self.call(argv, run), (0, 'RESEARCH_CANDIDATE_DATABASE_BOUND_NO_EXECUTION\n', ''))
        self.read.assert_called_once_with(override)
        self.anchor.assert_called_once()
        run.assert_not_called()
        self.assertFalse(Path(self.config['workspace']).exists())

    def test_anchor_rejection_prevents_workspace_and_journal_creation(self):
        override = self.override()
        self.anchor.side_effect = ValueError('synthetic private database detail')
        run = Mock()
        self.assertEqual(self.call(['--config', str(self.path), '--database-url-file', override], run),
                         (2, '', 'RESEARCH_CANDIDATE_STOPPED\n'))
        run.assert_not_called()
        self.assertFalse(Path(self.config['workspace']).exists())

    def test_private_database_file_symlink_and_broad_mode_fail_before_anchor(self):
        target = Path(self.override())
        alias = self.root / 'alias'; alias.symlink_to(target)
        run = Mock()
        for path in (alias, target):
            if path == target:
                target.chmod(0o644)
            self.assertEqual(self.call(['--config', str(self.path), '--database-url-file', str(path)], run),
                             (2, '', 'RESEARCH_CANDIDATE_STOPPED\n'))
        self.anchor.assert_not_called()
        run.assert_not_called()
        self.assertFalse(Path(self.config['workspace']).exists())

    def test_execution_rejects_retained_bytes_changed_after_database_anchor_before_workspace(self):
        journal_module = importlib.import_module('research_candidate_recovery')
        override = self.override()
        retained = Path(self.config['baselineRunConfigFile'])
        original = retained.read_bytes()
        def change_after_anchor(database_url, inputs):
            # Still valid, semantically identical JSON; immutable byte identity
            # must nevertheless remain the same as the anchored read.
            retained.write_bytes(original + b'\n')
        self.anchor.side_effect = change_after_anchor
        run = Mock()
        with patch.object(journal_module, 'CandidateJournal') as create_journal:
            self.assertEqual(self.call(['--config', str(self.path), '--database-url-file', override], run),
                             (2, '', 'RESEARCH_CANDIDATE_STOPPED\n'))
        self.read.assert_called_once_with(override)
        self.anchor.assert_called_once()
        create_journal.assert_not_called()
        run.assert_not_called()
        self.assertFalse(Path(self.config['workspace']).exists())

    def test_recovery_rejects_retained_observation_changed_after_anchor_before_opening_journal(self):
        journal_module = importlib.import_module('research_candidate_recovery')
        recovery = importlib.import_module('research_candidate_recover_command')
        override = self.override()
        inputs = runner.load_inputs(self.config)
        workspace = Path(self.config['workspace']); workspace.mkdir(mode=0o700)
        journal_path = workspace / 'candidate-journal.json'
        with journal_module.CandidateJournal(journal_path, identity=inputs['identity'], total_seconds=1800):
            pass
        before = {path.name: (path.read_bytes(), path.stat().st_mtime_ns) for path in workspace.iterdir()}
        retained = Path(self.config['baselineEvaluationReceiptFile'])
        def change_after_anchor(database_url, anchored_inputs):
            changed = json.loads(retained.read_bytes())
            changed['imported']['observation']['valBpb'] = 1.4
            retained.write_bytes(runner.canonical(changed))
        self.anchor.side_effect = change_after_anchor
        with patch.object(journal_module, 'CandidateJournal') as reopen_journal, \
             patch.object(recovery, 'recover') as recover:
            self.assertEqual(self.call(['--recover', '--config', str(self.path), '--database-url-file', override], Mock()),
                             (2, '', 'RESEARCH_CANDIDATE_STOPPED\n'))
        self.read.assert_called_once_with(override)
        self.anchor.assert_called_once()
        reopen_journal.assert_not_called()
        recover.assert_not_called()
        self.assertEqual({path.name: (path.read_bytes(), path.stat().st_mtime_ns)
                          for path in workspace.iterdir()}, before)
