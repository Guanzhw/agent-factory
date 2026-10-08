"""24,204 real inert files through inventory, observer and driver staging.

Only source generation and output reservation use existing controlled fixtures.
No package is imported from the synthetic site; no ML/process/DB is executed.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_factory import research_local_driver as driver_module
from agent_factory.process_enforcement import UvResearchProcessSpec
from agent_factory.research_manifest import manifest_fingerprint
from agent_factory.research_staging import InputPin, RootIdentity, pin_bytes
from agent_factory.store import digest
import test_research_local_driver as driver_fixture
import test_research_package_paths as path_fixture


@unittest.skipUnless(os.name == 'posix', 'Real descriptor-safe full site filesystem')
class FullInventoryScaleTests(unittest.TestCase):
    def test_24204_files_observed_and_staged_without_truncation(self):
        fixture = driver_fixture.LocalDriverTests()
        fixture.setUp(); self.addCleanup(fixture.doCleanups)
        journey = path_fixture.CompletePackagePathJourneyTests()
        journey.setUp(); self.addCleanup(journey.doCleanups)
        case = journey.case
        real_module = Path(driver_module.__file__)
        for name in driver_module._RUNTIME_FILES:
            case.write(case.runtime_root / name, (real_module.parent / name).read_bytes())
        existing = sum(path.is_file() for path in case.site.rglob('*'))
        filler = case.site / 'zz_scale_data'; filler.mkdir(mode=0o700)
        for number in range(24204 - existing):
            case.write(filler / f'{number:05d}.txt', b'inert inventory data\n')
        last = sorted(filler.iterdir())[-1]
        built, observer, request = journey.complete()
        self.assertEqual(len(built['inventory']['siteFiles']), 24204)
        contract = json.loads(request['launchSpec']['interpreter_contract'])
        self.assertEqual(len(contract['packageFiles']), 24204)
        self.assertIn(str(last), {row['path'] for row in contract['packageFiles']})
        # Use actual installed-source bytes, not the earlier tiny adapter fixture.
        request['trustedRuntimeFiles'] = [asdict(pin_bytes(name, (case.runtime_root / name).read_bytes()))
            for name in driver_module._RUNTIME_FILES]
        self.assertEqual(observer(request)['status'], 'VERIFIED')

        fixture.manifest['schema'] = 2
        fixture.manifest['dataset']['sampleSetSha256'] = digest({'schema': 1,
            'shards': fixture.manifest['dataset']['shards'],
            'validationShardIds': fixture.manifest['dataset']['validationShardIds']})
        old_lock = fixture.manifest['environment']['lockfileSha256']
        fixture.manifest['environment'].update(deepcopy(request['environment']))
        fixture.manifest['environment']['upstreamLockfileSha256'] = old_lock
        fixture.environment = []
        for label, basename in [('environment-inventory', 'complete.json'),
                                ('environment-kernel', 'complete-kernel.json'),
                                ('environment-lockfile', 'uv.lock')]:
            raw = (case.root / basename).read_bytes()
            fixture.environment.append(InputPin(label, 'environment', str(case.root),
                RootIdentity(**driver_fixture.identity(case.root)), pin_bytes(basename, raw)))
        fixture.record['binding']['executionGuard']['manifestSha256'] = manifest_fingerprint(fixture.manifest)
        environment = {key: str(fixture.cache) for key in
            ('HOME', 'TORCHINDUCTOR_CACHE_DIR', 'TRITON_CACHE_DIR', 'CUDA_CACHE_PATH', 'TMPDIR')}
        environment['PYTHONPYCACHEPREFIX'] = str(fixture.program)
        environment.update({key: '1' for key in
            ('HF_HUB_OFFLINE', 'HF_DATASETS_OFFLINE', 'TRANSFORMERS_OFFLINE', 'PYTHONNOUSERSITE')})
        spec = UvResearchProcessSpec(request['launchSpec']['executable'], request['launchSpec']['sha256'],
            ('-B', str(fixture.program / 'train_baseline.py'), '--config', str(fixture.program / 'run-config.json')),
            str(fixture.program), tuple(sorted(environment.items())),
            (fixture.program.stat().st_dev, fixture.program.stat().st_ino), request['launchSpec']['interpreter_contract'])
        with patch.object(driver_module, '__file__', str(case.runtime_root / real_module.name)):
            driver = fixture.driver(environment_verifier=observer, launch_spec=spec)
            proof = driver(fixture.record)
            config_path = fixture.program / 'run-config.json'
            raw = config_path.read_bytes()
            config = json.loads(raw)
            self.assertEqual(config['binding']['providerJobId'], 'provider-original')
            self.assertEqual(config['comparisonManifest']['environment']['installedInventory'],
                {'sha256': hashlib.sha256(built['inventoryBytes']).hexdigest(), 'sizeBytes': len(built['inventoryBytes'])})
            self.assertEqual(driver(fixture.record), proof)
            original_config = raw
            last.write_bytes(b'changed final inventory member\n')
            self.assertEqual(observer(request)['status'], 'UNKNOWN')
            with self.assertRaises(ValueError): driver(fixture.record)
            self.assertEqual(config_path.read_bytes(), original_config)
            last.unlink()
            self.assertEqual(observer(request)['status'], 'UNKNOWN')
            with self.assertRaises(ValueError): driver(fixture.record)
            self.assertEqual(config_path.read_bytes(), original_config)
