"""Build and import the standalone Factory wheel without application packages."""
from email.parser import Parser
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
APPLICATION_PACKAGES = {'agent_factory_research', 'agent_factory_server'}

IMPORT_CORE = '''
import importlib, importlib.abc, importlib.util, json, pathlib, sys
sys.path[:0] = sys.argv[1:3]
assert all(importlib.util.find_spec(name) is None for name in
    ('agent_factory_research', 'agent_factory_server'))
attempts = []
class RejectApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'agent_factory_research', 'agent_factory_server'}:
            attempts.append(fullname)
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, RejectApplication())
modules = {name: importlib.import_module(name) for name in json.loads(sys.argv[3])}
from agent_factory.config import Settings
from agent_factory.main import create_app
settings = Settings(db_url='postgresql://synthetic:synthetic@127.0.0.1/unused',
                    jwt_key='synthetic-distribution-only-key-' * 2)
assert callable(create_app)
assert not settings.runtime_adapters
assert not settings.usage_pricing
assert not settings.native_workflows
assert not any(hasattr(settings, name) for name in
    ('autoresearch_presets', 'research_evaluators', 'platform_openresearch', 'ssh_openresearch'))
assert not attempts, attempts
print(json.dumps({'files': {name: str(pathlib.Path(module.__file__).resolve())
    for name, module in modules.items()}, 'applicationImportAttempts': attempts}))
'''

RUN_CORE = '''
import importlib.abc, importlib.util, json, pathlib, sys
sys.path[:0] = sys.argv[1:3]
assert all(importlib.util.find_spec(name) is None for name in
    ('agent_factory_research', 'agent_factory_server'))
class RejectApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'agent_factory_research', 'agent_factory_server'}:
            raise AssertionError('Core startup imported application code: ' + fullname)
sys.meta_path.insert(0, RejectApplication())
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from agent_factory.config import Settings
from agent_factory.main import create_app
values = json.loads(sys.stdin.read())
engine = create_engine(values['database'])
def tables():
    with engine.connect() as connection:
        return sorted(row[0] for row in connection.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema NOT IN ('pg_catalog','information_schema')")))
snapshots = {'before': tables()}
assert snapshots['before'] == []
settings = Settings(db_url=values['database'], workspace=pathlib.Path(values['workspace']),
    web_directory=pathlib.Path(values['workspace']) / 'no-web',
    jwt_key='synthetic-distribution-only-key-' * 2, max_workers=1)
app = create_app(settings)
native = app
while not hasattr(getattr(native, 'state', None), 'factory'):
    native = native.app
state = native.state.factory
snapshots['assembled'] = tables()
try:
    with TestClient(app) as client:
        assert getattr(native.state, 'queue_worker', None) is not None
        headers = {'Authorization': 'Bearer ' + state['auth']._issue_native_token('alice')}
        for route in ('/api/factory/materials', '/api/factory/applications'):
            response = client.get(route, headers=headers)
            assert response.status_code == 200, (route, response.status_code)
            assert response.json() == [], (route, response.json())
        assert client.get('/api/factory/openresearch/capabilities', headers=headers).status_code == 404
        snapshots['running'] = tables()
    snapshots['stopped'] = tables()
finally:
    state['store'].engine.dispose()
    state['store'].native_db.db_engine.dispose()
    engine.dispose()
prefixes = ('af_orx', 'af_autoresearch', 'af_openresearch', 'af_inference',
            'af_research', 'af_literature', 'af_synthesis', 'af_comparison', 'af_remote_scientific')
for phase, names in snapshots.items():
    assert not any(name.startswith(prefixes) for name in names), (phase, names)
assert 'af_tasks' in snapshots['running'] and 'af_materials' in snapshots['running']
assert not any(name.startswith(('agent_factory_research', 'agent_factory_server')) for name in sys.modules)
print('CORE_DISTRIBUTION_SMOKE=' + json.dumps(snapshots))
'''


class CorePackageDistributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = TemporaryDirectory(prefix='factory-core-distribution-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name).resolve()
        result = subprocess.run([sys.executable, '-I', '-B', '-c',
            'import sys; from hatchling.build import build_wheel; print(build_wheel(sys.argv[1]))',
            str(cls.root)], cwd=ROOT / 'platform', capture_output=True, text=True, check=True)
        cls.wheel = cls.root / result.stdout.strip()
        cls.site = cls.root / 'installed'
        with zipfile.ZipFile(cls.wheel) as archive:
            archive.extractall(cls.site)
        # Reuse only third-party dependencies. Do not process editable-install
        # .pth files or expose any source/application package from this checkout.
        cls.dependencies = cls.root / 'dependencies'
        cls.dependencies.mkdir()
        for directory in {sysconfig.get_path('purelib'), sysconfig.get_path('platlib')}:
            for source in Path(directory).iterdir():
                if (source.name.startswith(('agent_factory', 'department_agent_factory'))
                        or source.suffix == '.pth' or source.name == '__pycache__'):
                    continue
                target = cls.dependencies / source.name
                if not target.exists():
                    target.symlink_to(source, target_is_directory=source.is_dir())

    def test_wheel_contains_only_core_sources_and_no_application_dependency(self):
        source = {path.relative_to(ROOT / 'platform').as_posix(): path.read_bytes()
            for path in (ROOT / 'platform/agent_factory').rglob('*.py')}
        with zipfile.ZipFile(self.wheel) as archive:
            actual = {name: archive.read(name) for name in archive.namelist()
                if name.startswith('agent_factory/') and name.endswith('.py')}
            self.assertEqual(actual, source)
            self.assertTrue(all(name.startswith(('agent_factory/', 'department_agent_factory_core-'))
                for name in archive.namelist()))
            self.assertFalse(any(name.startswith('agent_factory/runtime_packages/') for name in archive.namelist()))
            metadata_name = next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
            metadata = Parser().parsestr(archive.read(metadata_name).decode())
        self.assertEqual(metadata['Name'], 'department-agent-factory-core')
        dependencies = metadata.get_all('Requires-Dist', [])
        self.assertIn('agno==3.1.0', dependencies)
        self.assertFalse(any('research' in name.lower() or 'factory-server' in name.lower()
            for name in dependencies))

    def test_all_installed_core_modules_import_with_application_packages_absent(self):
        modules = []
        for path in (self.site / 'agent_factory').rglob('*.py'):
            if path.name == '__main__.py':
                continue
            parts = path.relative_to(self.site).with_suffix('').parts
            modules.append('.'.join(parts[:-1] if path.name == '__init__.py' else parts))
        modules.sort()
        result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', IMPORT_CORE,
            str(self.site), str(self.dependencies), json.dumps(modules)], cwd=self.root,
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        observed = json.loads(result.stdout)
        self.assertEqual(set(observed['files']), set(modules))
        self.assertEqual(observed['applicationImportAttempts'], [])
        for name, filename in observed['files'].items():
            self.assertTrue(Path(filename).is_relative_to(self.site / 'agent_factory'), (name, filename))
        for name in APPLICATION_PACKAGES:
            self.assertFalse((self.site / name).exists())
            self.assertFalse((self.dependencies / name).exists())

    @unittest.skipUnless(os.getenv('FACTORY_TEST_DATABASE_URL'), 'Requires isolated PostgreSQL/native queue acceptance')
    def test_installed_core_lifespan_never_creates_research_tables_or_seeds(self):
        from pg_fixture import IsolatedPostgres  # pyright: ignore[reportMissingImports]

        with IsolatedPostgres(os.environ['FACTORY_TEST_DATABASE_URL']) as database:
            result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', RUN_CORE,
                str(self.site), str(self.dependencies)], cwd=self.root, capture_output=True, text=True,
                input=json.dumps({'database': database.url, 'workspace': str(self.root / 'workspace')}), timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        marker = 'CORE_DISTRIBUTION_SMOKE='
        output = next(line.removeprefix(marker) for line in result.stdout.splitlines() if line.startswith(marker))
        snapshots = json.loads(output)
        self.assertEqual(snapshots['before'], [])
        self.assertEqual(snapshots['running'], snapshots['stopped'])
        self.assertIn('af_tasks', snapshots['running'])
        self.assertIn('af_materials', snapshots['running'])


if __name__ == '__main__':
    unittest.main()
