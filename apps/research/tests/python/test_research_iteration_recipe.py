"""Reviewed byte/pin calibration only; no ORX, containers, PG or native runs."""
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from agent_factory_research.openresearch import OpenResearchError, REVISION
from agent_factory_research import orx_local
from agent_factory_research.research_iteration_recipe import (
    IterationSeedORXAdapter, IterationPromotedORXAdapter, IterationORXProvider,
    PROMOTED_SOURCE_COMMIT, PROMOTED_ARCHIVE_SHA256,
)


class IterationRecipeTests(unittest.TestCase):
    def test_default_recipe_and_packaged_files_keep_original_pins(self):
        recipe = orx_local.TaskLocalORXAdapter._recipe
        self.assertIsNone(recipe.identity)
        self.assertEqual(recipe.commit, '169b85d17a7faa5f15ca8bb5d7fe94ae1069b2d5')
        self.assertEqual(recipe.archive_sha256, '3feae56d2102a5d3ce9c1484747961013a0ab34003c450bcb201030c58460938')
        self.assertEqual(recipe.files(), orx_local.TOY_FILES)
        root = Path(orx_local.__file__).parent / 'orx_toy'
        for name, sha in recipe.hashes:
            self.assertEqual(hashlib.sha256((root / name).read_bytes()).hexdigest(), sha)
        with self.assertRaises(FrozenInstanceError):
            recipe.baseline_mse = 0

    def test_both_git_archives_reproduce_pins_and_only_baseline_bytes_change(self):
        root = Path(orx_local.__file__).parent / 'orx_toy'
        git = shutil.which('git')
        self.assertIsNotNone(git)
        for adapter in (orx_local.TaskLocalORXAdapter, IterationSeedORXAdapter, IterationPromotedORXAdapter):
            recipe = adapter._recipe
            with self.subTest(recipe=recipe.identity), tempfile.TemporaryDirectory() as directory:
                path = Path(directory)
                for name, source in recipe.sources:
                    raw = (root / source).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), recipe.files()[name])
                    (path / name).write_bytes(raw)
                env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
                    'GIT_AUTHOR_NAME': 'Factory toy evaluator', 'GIT_AUTHOR_EMAIL': 'toy@example.invalid',
                    'GIT_COMMITTER_NAME': 'Factory toy evaluator', 'GIT_COMMITTER_EMAIL': 'toy@example.invalid',
                    'GIT_AUTHOR_DATE': '2000-01-01T00:00:00Z', 'GIT_COMMITTER_DATE': '2000-01-01T00:00:00Z'}
                def command(*args):
                    return subprocess.check_output([git, '-c', 'core.hooksPath=', '-c', 'commit.gpgSign=false',
                                                    *args], cwd=path, env=env, timeout=5)
                command('init', '-q', '-b', 'main'); command('add', '--', *recipe.files())
                command('commit', '-q', '-m', 'Reviewed original deterministic toy evaluator')
                self.assertEqual(command('rev-parse', 'HEAD').decode().strip(), recipe.commit)
                self.assertEqual(hashlib.sha256(command('archive', '--format=tar', 'HEAD')).hexdigest(), recipe.archive_sha256)
                instance = object.__new__(adapter)
                instance._git = command
                instance._validate_owned_source = lambda: {'sourceCommit': recipe.commit,
                    'sourceArchiveSha256': recipe.archive_sha256}
                exported = instance.source_archive_bytes()
                self.assertEqual(hashlib.sha256(exported).hexdigest(), recipe.archive_sha256)
        promoted = IterationPromotedORXAdapter._recipe
        self.assertEqual(promoted.commit, PROMOTED_SOURCE_COMMIT)
        self.assertEqual(promoted.archive_sha256, PROMOTED_ARCHIVE_SHA256)
        self.assertEqual([k for k, v in promoted.hashes if v != orx_local.TOY_FILES[k]], ['baseline.py'])

    def test_actual_reviewed_predictor_bytes_give_seed_improvement_then_tie(self):
        root = Path(orx_local.__file__).parent / 'orx_toy'
        data = json.loads((root / 'dataset.json').read_text())
        values = []
        for adapter in (IterationSeedORXAdapter, IterationPromotedORXAdapter):
            scores = []
            for name in ('baseline.py', 'candidate.py'):
                source = dict(adapter._recipe.sources)[name]
                namespace = {}
                exec(compile((root / source).read_bytes(), source, 'exec'), namespace)
                scores.append(sum((namespace['predict'](row['x']) - row['y']) ** 2 for row in data) / len(data))
            values.append(scores)
        self.assertEqual(values, [[16.0, 0.0], [0.0, 0.0]])

    def test_reopening_another_recipe_is_rejected_including_legacy(self):
        classes = (orx_local.TaskLocalORXAdapter, IterationSeedORXAdapter, IterationPromotedORXAdapter)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manifest.json'
            for original in classes:
                manifest = dict(schemaVersion=1, ownerId='alice', taskId='task', scenario='success', limits={},
                    upstreamRevision=REVISION, upstreamSourceArchiveSha256=orx_local.SOURCE_ARCHIVE_SHA256)
                if original._recipe.identity is not None:
                    manifest['recipeIdentity'] = original._recipe.identity
                path.write_text(json.dumps(manifest))
                for reopened in classes:
                    adapter = object.__new__(reopened)
                    adapter._manifest_path = path
                    adapter.owner_id, adapter.task_id, adapter.scenario, adapter.limits = 'alice', 'task', 'success', {}
                    if reopened is original:
                        self.assertEqual(adapter._load_manifest(), manifest)
                    else:
                        with self.assertRaises(OpenResearchError): adapter._load_manifest()

    def test_provider_selects_only_fixed_recipes(self):
        kwargs = dict(binary=Path('/unused/orx'), source_archive=Path('/unused/archive'),
                      git_binary=Path('/unused/git'), python_binary=Path('/unused/python'))
        self.assertIs(IterationORXProvider(recipe='seed', **kwargs).adapter_type, IterationSeedORXAdapter)
        self.assertIs(IterationORXProvider(recipe='promoted', **kwargs).adapter_type, IterationPromotedORXAdapter)
        for value in ('../candidate.py', b'arbitrary source', None):
            with self.assertRaises(ValueError): IterationORXProvider(recipe=value, **kwargs)

    def test_evaluation_reads_selected_snapshot_bytes_and_rejects_metric_drift(self):
        root = Path(orx_local.__file__).parent / 'orx_toy'
        for cls in (IterationSeedORXAdapter, IterationPromotedORXAdapter):
            with tempfile.TemporaryDirectory() as directory:
                adapter = object.__new__(cls)
                adapter.scope = Path(directory)
                adapter.task_id, adapter.owner_id, adapter.scenario = 'task', 'alice', 'success'
                adapter.limits = {'outputBytes': 65536}
                adapter._native_run = lambda: {'id': 'original-run', 'status': 'done'}
                adapter.provenance = lambda: {'recipeIdentity': cls._recipe.identity}
                run = adapter.scope / 'orx-store/local-runs/original-run/repo'
                run.mkdir(parents=True)
                for name, source in cls._recipe.sources:
                    (run / name).write_bytes((root / source).read_bytes())
                value = dict(schemaVersion=1, taskId='task', ownerSha256=hashlib.sha256(b'alice').hexdigest(),
                    scenario='success', fileSha256=cls._recipe.files(), sampleCount=7, status='done',
                    metric='mean_squared_error', baseline={'value': cls._recipe.baseline_mse},
                    candidate={'value': 0.0}, improvement=cls._recipe.baseline_mse)
                output = run / 'result.json'
                output.write_text(json.dumps(value))
                result = adapter.evaluation_result()
                self.assertEqual(result['baseline'], value['baseline'])
                self.assertEqual(result['runId'], 'original-run')
                self.assertEqual(result['resultSha256'], hashlib.sha256(output.read_bytes()).hexdigest())
                for change in ({'metric': 'other'}, {'improvement': False}, {'improvement': float('nan')},
                               {'baseline': {'value': 42}}):
                    output.write_text(json.dumps({**value, **change}))
                    with self.assertRaises(OpenResearchError): adapter.evaluation_result()
                output.write_text(json.dumps(value))
                (run / 'baseline.py').write_bytes(b'changed source')
                with self.assertRaises(OpenResearchError): adapter.evaluation_result()

    def test_new_ready_manifest_rejects_forged_source_pins(self):
        cls = IterationPromotedORXAdapter
        with tempfile.TemporaryDirectory() as directory:
            adapter = object.__new__(cls)
            adapter._manifest_path = Path(directory) / 'manifest.json'
            adapter.owner_id, adapter.task_id, adapter.scenario, adapter.limits = 'alice', 'task', 'success', {}
            value = dict(schemaVersion=1, ownerId='alice', taskId='task', scenario='success', limits={},
                upstreamRevision=REVISION, upstreamSourceArchiveSha256=orx_local.SOURCE_ARCHIVE_SHA256,
                phase='READY', recipeIdentity=cls._recipe.identity, sourceCommit=cls._recipe.commit,
                sourceArchiveSha256=cls._recipe.archive_sha256, fileSha256=cls._recipe.files())
            adapter._manifest_path.write_text(json.dumps(value))
            self.assertEqual(adapter._load_manifest(), value)
            for change in ({'sourceCommit': orx_local.RECIPE_SOURCE_COMMIT},
                           {'sourceArchiveSha256': orx_local.RECIPE_ARCHIVE_SHA256},
                           {'fileSha256': orx_local.TOY_FILES}):
                adapter._manifest_path.write_text(json.dumps({**value, **change}))
                with self.assertRaises(OpenResearchError): adapter._load_manifest()
