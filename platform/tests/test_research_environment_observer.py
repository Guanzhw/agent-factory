"""Synthetic temp installation only; no interpreter, package or GPU execution."""
import base64
import zlib
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from agent_factory import research_environment_observer as module

from agent_factory.research_environment_observer import ResearchEnvironmentObserver
from agent_factory.research_staging import FilePin, InputPin, RootIdentity
from agent_factory.store import digest
from test_research_manifest import example_manifest  # pyright: ignore[reportMissingImports]


# Exact reviewed virtualenv startup source, inert compressed fixture; never executed.
# uv0.12.19 / virtualenv MIT attribution and license text: THIRD_PARTY_NOTICES.md.
_UV_STARTUP_SOURCE = zlib.decompress(base64.b85decode(
    'c%0o>TW{kw7Jm1yAe4vN14~ZQooy#*fDJmA2FMPINv1D@fj~>N#f>bgBo)Q8*#ExYAt_n5>|pnyeJFv%vPhlFcfNCxqbT~7+pG|V'
    '*@9cfwP3uiODS@OuezzM+z4hBwgr2V+BUpoqQaG`Hlngg6h)JX+|){2mZ{2$XIsi;cSo7-'
    '%52SK^4smFhtD^6?>_#P{(AH9^DpW9+q-'
    'w{8po2F+alphL!Z+$UCC0U>1;BY<YL8YvN6r2u~YgtyP7a8Qca(4ajUViG>n&}Y7J|Q&}1|0S;=(+pNxVRT(29l*}xIbc)!i9R23'
    'tQUT$G+ZLSuJTxGCpYYSB+O0O5+Cl?nBSs4p8_{_y~QrJy-mUsH&J&7?%G|9xtye9+H3NT7DFa)xjb-'
    '{8~eP`K*Kf+Q`8Np=Lf$1MQioG-'
    '0%vmYycLrac>EMPnb<)AZ*cq$T@BE6ry*z*I?w+w$u#8ugvK}svO>iq<!g%0AtC})rYhe+B?2)g*lW-CQQH?b+7cW@oG^#RBYp#t'
    '*y>J&>gQyd32?bBfWkZN1<6|B@&w<0esS)LB&Rzjdpz!L|V@p?o9JI7BO=*c=M@=~KeE)cd$u*;c2~bE?O?HBbnVm*qKblQ;kE~c'
    '!Yk^oq6vJ@hieM**{1#iQC!s6D+CpfTT%9I5gY3~<OSsMkE1dY!N&gC~j%L$*luXFH#6PujZKX6@a!<5rR3k;8Hk!lulG|`u2%Za'
    'V=+b0b*4AC--12CEF|9|jg*mGZko4aq`ajXW11opz0F+#@9TC^1TJny9hHxq5zd$?o1WHj2DE2WK;F8p;o<jbdeN>g04H#e>T?HZ'
    'pF8vRzgEz;hI5}gtzM2(EJ^Bo(L-}-Bv{89Ok5fq3l|pd$Ys?cbo37L@wcw9kT6KQ-'
    'W0d_s5bBUxN74#KC4GB)|M2<Y_U_)t9u`M^9ZKlR#SQM)R;lh5B%Um83s1c5!WV3O^VJP9tgO~?Q^&lD{ie_WBP+QvEPYRvQ1=!2'
    'hHZr9E?Ou_v=uswFU<}vh;vjA!gAJI-XZAQieqY1mK6uK*Dkb^P{c}=J$^a=$|Ru)By-42?r?KDn=`}}7)mR7DZfE{$-'
    'l{ROHtuZO6EbYw<0_Xj_EBET;m+9MKFMRJrCNJBI9T(WHdEM{H+B@X=5UK?mK4YVi$s23EYOhr2q)pSjPxYot?_%))j0NmnZ5IUe'
    '&!2eT>%97R@rr)Mim{YrY6n023C{7%*vZ@#CA<E}3(HPLX#~2pr(`<?F8gfBO9X{Ni#~O(`^~sYMowU<dQuMQ+aEKkD7J%ciTHn4'
    '3=@&d)FV^g3f78m<ArniGMU=9!~>E<F}`qsdW9ALL-Gr4{5g5+-'
    '}34HShDkr7cCC@YaC13eGaH_^6O0kB0yrL%Gza<Z|v6eN%eE2**Wh})vx=r?=1!32)7gJ7Z}t4tU(RQ3Nw;PTDi-'
    ';5(b%j)fZne17fx-3A14xR6hi|0(#mVHD--f6A$zMxRmTs{oyYo98pABVblmHRHXJ7k=IeaUBoyy<hyr_W(E2MCTk2_2iU>uYv?H'
    '7?HwoS%$N1g;(?@#x%HNIsZdD`VtRmeOv0w%Jw%0fs$XIA0$wU78xXLE-'
    '0>P>n%mW1g)X6Ds6mp91qE%G44w<P)8B{?R}rHnl~AA?d3|JNB$qFO7^_Zg=pxYLKvBREtUhb~ODI{o(fRn8uR&k|TFMoiSC5&@*'
    'UWv}z+Wr`gSqE#ER#mGrNlzB>O~i8&%_WfhUWy0Lz!fDcD>#vVW6il3L@1yHezy<<tBL2~5z)6HbXfA1QKZzC-'
    'f#Yp<x#A+4$Rv){57;hTu2WCVp_EyA(uf#}UPqz*yN4<Sct+d)8K2_%0UPnN5a|+A&<gVFKwsgmPYV6ByQ4MxR0FyD{_jByJ&&ko'
    'jQFZ7gKrKDk7wG-cJkAVS$Vc}a$U*beII)Lo7q_-;hhfXb)1nr&p?~rD-(FuV&I;AWrE-'
    '}W6Eosg=`oXfGfY~EHs!U12L(6WT0JGh5|SY_MiTKXveb9^=(sPmD1d2zaPJZFbf86)AZkRyy8|ah;vE3O(A368_1a!GsCy9@*mK'
    'OBK#<;~(`c=nQ6Xle;dIPs5oLC*`2O~v7vY`mrDa}pc;02kly1$*p4n*-Xob#nWBvSmtUVoDHO-'
    '2!{pa}IGn%uZ%I2*xu2AcRVy2-'
    '+W!N`acVnhcxu3pIemJQiG((rIhkHmO%$=ta?I2b6+Uc;xx|{znRHQNtw}s04F={}CDX^P|`E~GqguByl^G}-'
    '$hC_kZoun?@X?kQfIGg}>KejN8HPX^NM%7kS8Qx0S2F-`~iqSUAX~)LAaoybgIFy*C#tW%2)832OI7EZrd^-'
    'GI2*e=Yd>~vp@1%xwbw346_f!23pVJP?z+WsV$DN%_=w}Cd6-?ca5qLci+D^~s-3#Lsb>_cFFim~'
))


@unittest.skipUnless(os.name == 'posix', 'POSIX nofollow static inventory')
class ResearchEnvironmentObserverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.venv = self.root / 'venv'
        self.site = self.venv / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
        self.site.mkdir(parents=True, mode=0o700)
        python = self.write(self.venv / 'bin' / 'python', b'synthetic interpreter bytes, never executable')
        cfg = self.write(self.venv / 'pyvenv.cfg', b'include-system-site-packages = false\n')
        packages = []
        for name in ('torch', 'tiktoken', 'pyarrow'):
            root = self.site / name
            init = self.write(root / '__init__.py', b'' if name == 'pyarrow' else b'# synthetic package, never imported\n')
            rows = [{'path': '__init__.py', **init}]
            if name == 'torch':
                rows.append({'path': 'version.py', **self.write(root / 'version.py', b"__version__ = '2.9.1+cu128'\ncuda: str = '12.8'\n")})
            packages.append({'module': name, 'version': '2.9.1' if name == 'torch' else 'synthetic', 'root': str(root), 'files': rows})
        self.program_root = self.root / 'program'
        self.program_root.mkdir(mode=0o700)
        self.runtime_root = self.site / 'agent_factory'
        adapter = self.write(self.runtime_root / 'research_torch_runtime.py', b'# fixed adapter bytes\n')
        inventory = {'schema': 1, 'python': {'path': str(self.venv / 'bin' / 'python'), **python},
            'venv': {'root': str(self.venv), 'sitePackages': str(self.site), 'pyvenvCfg': cfg}, 'packages': packages}
        kernel = {'schema': 1, 'backend': 'pytorch-sdpa', 'torchVersion': '2.9.1', 'cudaVersion': '12.8',
            'torchFiles': packages[0]['files'], 'adapterSha256': adapter['sha256']}
        inventory_pin = self.input('environment-inventory', 'inventory.json', inventory)
        kernel_pin = self.input('environment-kernel', 'kernel.json', kernel)
        self.observer = ResearchEnvironmentObserver(inventory_pin, kernel_pin)
        manifest = example_manifest()
        manifest['environment']['installedInventory'] = {'sha256': inventory_pin.file.sha256, 'sizeBytes': inventory_pin.file.size_bytes}
        manifest['environment']['runtimeKernel'] = {'sha256': kernel_pin.file.sha256, 'sizeBytes': kernel_pin.file.size_bytes}
        manifest['dataset']['shards'][1]['sha256'] = '9' * 64
        manifest['dataset']['sampleSetSha256'] = digest({'schema': 1, 'shards': manifest['dataset']['shards'],
            'validationShardIds': manifest['dataset']['validationShardIds']})
        self.request = {'environment': manifest['environment'], 'runtimeKernel': manifest['environment']['runtimeKernel'],
            'sampleSetSha256': manifest['dataset']['sampleSetSha256'], 'configurationFingerprint': self.observer.configuration_fingerprint,
            'launchSpec': {'executable': str(self.venv / 'bin' / 'python'), 'sha256': python['sha256'], 'argv': ['-B', str(self.program_root / 'train.py'), '--config', str(self.program_root / 'run-config.json')],
                'working_directory': str(self.program_root), 'environment': [('PYTHONPYCACHEPREFIX', str(self.program_root))]},
            'trustedRuntimePackage': str(self.runtime_root), 'trustedRuntimeFiles': [{'basename': 'research_torch_runtime.py',
                'sha256': adapter['sha256'], 'size_bytes': adapter['sizeBytes']}],
            'runtimeConfig': {'comparisonManifest': manifest, 'dataset': {'shards': [row | {'basename': row['id'] + '.parquet'} for row in manifest['dataset']['shards']],
                'validationShardIds': manifest['dataset']['validationShardIds']}},
            'environmentPins': [asdict(inventory_pin), asdict(kernel_pin)]}

    def write(self, path, raw):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(raw)
        path.chmod(0o600)
        return {'sha256': hashlib.sha256(raw).hexdigest(), 'sizeBytes': len(raw)}

    def input(self, label, name, value):
        identity = self.write(self.root / name, json.dumps(value, sort_keys=True, separators=(',', ':')).encode())
        info = self.root.stat()
        return InputPin(label, 'environment', str(self.root), RootIdentity(info.st_dev, info.st_ino),
            FilePin(name, identity['sha256'], identity['sizeBytes']))

    def uv_fixture(self):
        from agent_factory.research_interpreter import capture_interpreter_contract
        cfg = self.write(self.venv / 'pyvenv.cfg', b'include-system-site-packages = false\nuv = 0.12.19\n')
        project_pin = self.write(self.root / 'pyproject.toml', b'[project]\nname="synthetic"\nversion="0.0.1"\n')
        lock_pin = self.write(self.root / 'uv.lock', b'version = 1\n# synthetic installed lock, not upstream provenance\n')
        interpreter = self.venv / 'bin' / 'python'
        managed = self.root / 'managed'
        managed.mkdir(mode=0o700)
        target = managed / 'python'
        interpreter.rename(target)
        target.chmod(0o700)
        interpreter.symlink_to(target)
        self.write(self.site / '_virtualenv.py', _UV_STARTUP_SOURCE)
        self.write(self.site / '_virtualenv.pth', b'import _virtualenv')
        inventory = json.loads((self.root / 'inventory.json').read_bytes())
        info = self.root.stat()
        inventory.update(schema=2, interpreterMode='research-uv-interpreter-v1',
            project={'root': str(self.root), 'rootIdentity': {'device': info.st_dev, 'inode': info.st_ino},
                     'pyprojectToml': project_pin, 'uvLock': lock_pin},
            startupProfile=module.UV_STARTUP_PROFILE, startupFiles=deepcopy(module.UV_STARTUP_FILES))
        inventory['venv']['pyvenvCfg'] = cfg
        first = self.input('environment-inventory', 'inventory.json', inventory)
        self.observer = ResearchEnvironmentObserver(first, self.observer._kernel)
        self.request['environment']['installedInventory'] = {'sha256': first.file.sha256, 'sizeBytes': first.file.size_bytes}
        upstream = self.request['environment']['lockfileSha256']
        self.request['environment'].update(lockfileSha256=lock_pin['sha256'], upstreamLockfileSha256=upstream)
        self.request['runtimeConfig']['comparisonManifest']['schema'] = 2
        self.request['configurationFingerprint'] = self.observer.configuration_fingerprint
        lock = InputPin('environment-lockfile', 'environment', str(self.root), RootIdentity(info.st_dev, info.st_ino),
                        FilePin('uv.lock', lock_pin['sha256'], lock_pin['sizeBytes']))
        self.request['environmentPins'] = [asdict(first), asdict(self.observer._kernel), asdict(lock)]
        paths = [str(Path(package['root']) / row['path']) for package in inventory['packages'] for row in package['files']]
        paths += [str(self.runtime_root / row['basename']) for row in self.request['trustedRuntimeFiles']]
        paths += [str(self.site / name) for name in module.UV_STARTUP_FILES]
        self.request['launchSpec']['interpreter_contract'] = capture_interpreter_contract(
            executable=str(interpreter), sha256=inventory['python']['sha256'], project_root=str(self.root),
            venv_root=str(self.venv), approved_interpreter_roots=[str(managed)],
            pyvenv_cfg=str(self.venv / 'pyvenv.cfg'), pyproject_toml=str(self.root / 'pyproject.toml'),
            uv_lock=str(self.root / 'uv.lock'), package_inventory=str(self.root / 'inventory.json'), package_files=paths)

    def test_uv_pinned_chain_exact_startup_and_adapted_lock_static_identity(self):
        self.uv_fixture()
        self.assertEqual(self.observer(self.request)['status'], 'VERIFIED')
        self.assertEqual(self.observer(self.request), self.observer(deepcopy(self.request)))

    def test_uv_cfg_lock_project_package_and_link_drift_unknown(self):
        for relative in ('venv/pyvenv.cfg', 'uv.lock', 'pyproject.toml',
                         'package', 'link'):
            with self.subTest(path=relative):
                case = ResearchEnvironmentObserverTests()
                case.setUp()
                try:
                    case.uv_fixture()
                    self.assertEqual(case.observer(case.request)['status'], 'VERIFIED')
                    if relative == 'link':
                        path = case.venv / 'bin' / 'python'
                        path.unlink()
                        path.symlink_to(case.root / 'managed' / 'missing')
                    else:
                        path = case.site / 'torch' / '__init__.py' if relative == 'package' else case.root / relative
                        path.write_bytes(path.read_bytes() + b'# altered\n')
                    self.assertEqual(case.observer(case.request)['status'], 'UNKNOWN')
                finally:
                    case.doCleanups()

    def test_uv_missing_inventory_coverage_or_wrong_lock_declaration_unknown(self):
        self.uv_fixture()
        self.assertEqual(self.observer(self.request)['status'], 'VERIFIED')
        request = deepcopy(self.request)
        contract = json.loads(request['launchSpec']['interpreter_contract'])
        contract['packageFiles'].pop()
        request['launchSpec']['interpreter_contract'] = json.dumps(contract, sort_keys=True, separators=(',', ':'))
        self.assertEqual(self.observer(request)['status'], 'UNKNOWN')
        request = deepcopy(self.request)
        request['environmentPins'][-1]['file']['sha256'] = '0' * 64
        self.assertEqual(self.observer(request)['status'], 'UNKNOWN')

    def test_uv_startup_modified_extra_or_shadowed_unknown(self):
        self.uv_fixture()
        self.assertEqual(self.observer(self.request)['status'], 'VERIFIED')
        for name in ('_virtualenv.abi3.so', '_virtualenv.pyc', 'other.pth'):
            path = self.site / name
            self.write(path, b'import unreviewed')
            self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
            path.unlink()
        self.write(self.site / '_virtualenv.py', _UV_STARTUP_SOURCE + b'\n# altered')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_static_declared_scope_verified_without_executing_interpreter(self):
        receipt = self.observer(self.request)
        self.assertEqual(receipt['status'], 'VERIFIED')
        self.assertEqual(receipt['requestSha256'], digest(self.request))
        self.assertEqual(set(receipt), {'schema', 'status', 'requestSha256', 'observationSha256'})
        self.assertEqual(receipt, self.observer(deepcopy(self.request)))

    def test_interpreter_file_and_package_extra_or_modified_bytes_unknown(self):
        target = self.venv / 'bin' / 'python'
        original = target.read_bytes()
        target.write_bytes(b'changed')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        target.write_bytes(original)
        extra = self.site / 'torch' / 'injected.py'
        self.write(extra, b'not inventoried')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        extra.unlink()
        (self.site / 'torch' / 'version.py').write_bytes(b"__version__='2.9.1'\ncuda='wrong'\n")
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_earlier_file_mutation_during_later_scan_is_rechecked_at_receipt(self):
        read = module._read
        def later_mutation(path, *args, **kwargs):
            result = read(path, *args, **kwargs)
            if str(path).endswith('research_torch_runtime.py'):
                python = self.venv / 'bin' / 'python'
                python.write_bytes(b'x' * python.stat().st_size)
            return result
        with patch.object(module, '_read', side_effect=later_mutation):
            self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_runtime_package_outside_selected_venv_cannot_be_attested(self):
        request = deepcopy(self.request)
        request['trustedRuntimePackage'] = str(self.root / 'other-package')
        self.assertEqual(self.observer(request)['status'], 'UNKNOWN')

    def test_actual_pinned_torch_version_literals_must_match_kernel_claim(self):
        pin = self.write(self.site / 'torch' / 'version.py', b"__version__ = '2.9.1'\ncuda = 'wrong'\n")
        inventory = json.loads((self.root / 'inventory.json').read_bytes())
        inventory['packages'][0]['files'][1] = {'path': 'version.py', **pin}
        kernel = json.loads((self.root / 'kernel.json').read_bytes())
        kernel['torchFiles'] = inventory['packages'][0]['files']
        first = self.input('environment-inventory', 'inventory.json', inventory)
        second = self.input('environment-kernel', 'kernel.json', kernel)
        self.observer = ResearchEnvironmentObserver(first, second)
        for selected, key in ((first, 'installedInventory'), (second, 'runtimeKernel')):
            self.request['environment'][key] = {'sha256': selected.file.sha256, 'sizeBytes': selected.file.size_bytes}
        self.request['runtimeKernel'] = self.request['environment']['runtimeKernel']
        self.request['configurationFingerprint'] = self.observer.configuration_fingerprint
        self.request['environmentPins'] = [asdict(first), asdict(second)]
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_pth_customization_and_symlink_interpreter_are_unsupported(self):
        path = self.site / 'injection.pth'
        self.write(path, b'import arbitrary_startup\n')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        path.unlink()
        self.write(self.site / 'sitecustomize.py', b'pass')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        (self.site / 'sitecustomize.py').unlink()
        python = self.venv / 'bin' / 'python'
        python.rename(python.with_name('actual'))
        python.symlink_to('actual')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_startup_extensions_and_runtime_shadow_modules_are_rejected(self):
        for root, name in ((self.site, 'sitecustomize.cpython-312-x86_64-linux-gnu.so'),
                           (self.site, 'usercustomize.pyd'),
                           (self.site, 'agent_factory.abi3.so'),
                           (self.runtime_root, 'research_torch_runtime.abi3.so'),
                           (self.runtime_root, 'research_torch_runtime.pyc')):
            with self.subTest(name=name):
                path = root / name
                self.write(path, b'synthetic never-loaded module')
                self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
                path.unlink()
        path = self.runtime_root / 'research_torch_runtime'
        path.mkdir()
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')
        path.rmdir()
        self.assertEqual(self.observer(self.request)['status'], 'VERIFIED')

    def test_bytecode_read_prefix_requires_B_and_empty_cache_tree(self):
        for change in ('argv', 'environment'):
            request = deepcopy(self.request)
            request['launchSpec'][change] = []
            self.assertEqual(self.observer(request)['status'], 'UNKNOWN')
        request = deepcopy(self.request)
        request['launchSpec']['environment'] = [('PYTHONPYCACHEPREFIX', str(self.root))]
        self.assertEqual(self.observer(request)['status'], 'UNKNOWN')
        cache = self.program_root / 'some-absolute-path'
        cache.mkdir()
        self.write(cache / 'module.pyc', b'synthetic cache never loaded')
        self.assertEqual(self.observer(self.request)['status'], 'UNKNOWN')

    def test_forged_sample_split_reused_shards_and_bad_request_unknown(self):
        changed = deepcopy(self.request)
        changed['sampleSetSha256'] = '0' * 64
        self.assertEqual(self.observer(changed)['status'], 'UNKNOWN')
        changed = deepcopy(self.request)
        dataset = changed['runtimeConfig']['comparisonManifest']['dataset']
        dataset['shards'][1]['sha256'] = dataset['shards'][0]['sha256']
        dataset['sampleSetSha256'] = digest({'schema': 1, 'shards': dataset['shards'], 'validationShardIds': dataset['validationShardIds']})
        changed['sampleSetSha256'] = dataset['sampleSetSha256']
        changed['runtimeConfig']['dataset']['shards'][1]['sha256'] = dataset['shards'][1]['sha256']
        self.assertEqual(self.observer(changed)['status'], 'UNKNOWN')
        changed = deepcopy(self.request)
        changed['untrusted'] = 'ignored?'
        self.assertEqual(self.observer(changed)['status'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
