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


# uv0.11.7 official startup source; same virtualenv MIT notice as above.
# https://github.com/astral-sh/uv/blob/0.11.7/crates/uv-virtualenv/src/_virtualenv.py
_UV_0117_STARTUP_SOURCE = zlib.decompress(base64.b85decode(
    'c$}?QU2oeq6n*!vAe4v7g(W-bifzFHENIg<Kvon@+LxjbXo<F1%Op!uR-9q~efN^ohrfb7Oh95;BJVvs_uNA|ilR@{<|Q-'
    '4medle8KFv5oD~GV>RMR7X2eQ(&B%spThod#0e4cYnXqXTMWYd4E2%A!roA&;Ga7xp{rvFd`tIiA*X+~v!<!G;yW6`Pas|UuMQxe'
    '>kX*!Bw%`@Zvhip%D%gT3gp(EA*cktfFGmC}%z~e9;ZbdQWeBY**%(qArV(B)#ey$ufNvxKrg~W;JOh|1q1|h0xfBF5`naXF%3My'
    'Th0Foe)|OJFQZJ{k()05v7sf&w_$=6CTH1AWR<!w(ornoWH0j92yhi|X0gQ1o00Ob=Wl0JtURbiGD?rMGVT21rXW66mlaA8tAe#x'
    'Pn0;a3%Oeh4lUk)MJ%pSQA%D_K^7dl(+C4oZ4I?=fLRwFk=O!#Ga6)J(eIx6tAWLSU1o?_CK@wpkXhGK2@Pa*q&}EcWktwPT%Y1N'
    'GTLUFW-cl@{=JOgEOAm*6_Phr6-^GSiiwSuNbOH-6U#=Rw3*x{_GgDU<#dQ?IiTU01mXj-j15;ojlL~Qy5_20z;e9k7^-'
    '~rkQkp?6BCKH;af!4eMgA38$_>-PkfvnX^--G%$5ec-sphbBGPuHsZ*BDNfa+)~O}b8^bAz8Tv|Z|F^-'
    'EhwP3F`KEshkl2&9cB0KTF&+?I?MOdGs4x#r5c+k#pe4LHVY#kK%v(GrsVjiLXEb{DX4!}driB<Y2?tmK@w5;Vw5$$x<C$Oa^Z9#'
    'HObGT<duQpFH|LOx2t#sdY|T8kirpr!wyI#|syDUQy_t+%pL%9ZaB6`ay_(OMQYPREiig@oendd!Aab?d5g&FHFat9BiJ7<NA}2<'
    'f1;j<gk+O7`~l{^85R?cKevJs^%cA4>7g)eV-ftd#8|h<MW6re1j4sdsDm=G_fqST2@Htr98{|B`7SBd@42BzuQWs5?i#CTnJ?s}'
    '@)iz6zU&w`NBdgmY34!3xqLZyEGEh*N4^Re}PySFW_9U}BZbSKnse2}d@8$pT`gcknPCPYBc%IOLYoia$a4iazmbi&dc;$%~NJqX'
    '=_BV|q&%)i4gwLNS1KH3`|~ET^!kAZXkR;cv-6lr}-37k+chUF||~1%t<sZ_a=OZLCv-mrkE@zIBET=CZ+k!l$}ttgF$I+p?agxm'
    '-`xR?%sY0w`h1jR7T1&wu;<wQJ@ANXN>%C`b<Q_3eA_|DV6So1I_uZi=PJjAD5(!ItKUtK5XZ`oZt6TsK|zVXi;FpUp0YcGuMhM0'
    '+4gDhltN{V3zgxa%KhgKBk^^+ntF5LmoJoZ_%Cxw;~=%R^JxV|sKjA~3Wsor7^_q2vHtNn`k&SKMxWjcp@C07D+m-'
    'C7?moHz_$gWXWUWNkoCa9|QxZ!SOu9r2SR$>bbPE*l){)`#0LTPq8;hS3+bMl`T}bkPvpeB0CKG?<bPvH^X9D(dc-_Wt(nSjGz75'
    'cJDL5s!&fEI1XOQmkC_++}vBmWFPL6czsK_WXAJ4Ts$;YPg6npQ^3j%3uvgaweWX=3352@By&J62GuC$RIs3|FnfI=+D;1ym>W{C'
    '|LpJCXtK8Z!n2-'
    ';bdJ~e@uglB_2g$=z<+2?Bv$+<fON&sfCtnsE^2<*|q|NJp{{gII_1`biH<XCym|M4Y)uL0ysGo{BDn3bxnCN(CY2sY!?C2;>6At'
    'b`9aMGw_0bbn`$QxQib)_VDWK)-'
    '=tqYz5m)6;lTPC9_{%pHI(9*(8;8otdCAl1A!7C3P@NCRmeE#bE^{HPl)iBd`=>Fbx|adt`a$_m=4RTJXXGW`V+;DY()>7FK~!BM'
    'jaSI2jU7o)8SI^bk~+?Rh}$@pFLZ7@Q!G4$^7177kRX8D=<LGrUkT{RVJ<``3B+CGp&4o?Y;y?Ti>7O%TucGzoaI$DAokuB|_{u^'
    'X+WejYbo3Qs72{Y`T7XyJzyI-5shoKfqkB&N<wG}<Sw+QW@+xj$Z|zn;tx4wkN4_uoMi!D;7IqwTe-JJjq&?GHMC8Z@aKj#Q;Ay3'
    'Knag&4S-'
    'gj3VtR1Qz$@Nl?U`$uW!s*q*J_Uv8MgCE{)xMy$;<mYiYb@vg2dfo4_cvt!V6SzGhLo19%_!|h%rJ4I>1cz;=Z9JQ_r`H(d_b-'
    'N3Gui'
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

    def uv_fixture(self, profile=module.UV_STARTUP_PROFILE, *, cfg_version=None, source=None,
                   declared_profile=None, declared_files=None):
        from agent_factory.research_interpreter import capture_interpreter_contract
        version, pins = module.UV_STARTUP_PROFILES[profile]
        if source is None:
            source = _UV_STARTUP_SOURCE if version == '0.12.19' else _UV_0117_STARTUP_SOURCE
        cfg = self.write(self.venv / 'pyvenv.cfg', f'include-system-site-packages = false\nuv = {cfg_version or version}\n'.encode())
        project_pin = self.write(self.root / 'pyproject.toml', b'[project]\nname="synthetic"\nversion="0.0.1"\n')
        lock_pin = self.write(self.root / 'uv.lock', b'version = 1\n# synthetic installed lock, not upstream provenance\n')
        interpreter = self.venv / 'bin' / 'python'
        managed = self.root / 'managed'
        managed.mkdir(mode=0o700)
        target = managed / 'python'
        interpreter.rename(target)
        target.chmod(0o700)
        interpreter.symlink_to(target)
        self.write(self.site / '_virtualenv.py', source)
        self.write(self.site / '_virtualenv.pth', b'import _virtualenv')
        inventory = json.loads((self.root / 'inventory.json').read_bytes())
        info = self.root.stat()
        inventory.update(schema=2, interpreterMode='research-uv-interpreter-v1',
            project={'root': str(self.root), 'rootIdentity': {'device': info.st_dev, 'inode': info.st_ino},
                     'pyprojectToml': project_pin, 'uvLock': lock_pin},
            startupProfile=declared_profile or profile, startupFiles=deepcopy(pins if declared_files is None else declared_files))
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
        paths += [str(self.site / name) for name in pins]
        self.request['launchSpec']['interpreter_contract'] = capture_interpreter_contract(
            executable=str(interpreter), sha256=inventory['python']['sha256'], project_root=str(self.root),
            venv_root=str(self.venv), approved_interpreter_roots=[str(managed)],
            pyvenv_cfg=str(self.venv / 'pyvenv.cfg'), pyproject_toml=str(self.root / 'pyproject.toml'),
            uv_lock=str(self.root / 'uv.lock'), package_inventory=str(self.root / 'inventory.json'), package_files=paths)

    def test_uv_pinned_chain_exact_startup_and_adapted_lock_static_identity(self):
        self.uv_fixture()
        self.assertEqual(self.observer(self.request)['status'], 'VERIFIED')
        self.assertEqual(self.observer(self.request), self.observer(deepcopy(self.request)))

    def test_uv_0117_exact_profile_static_identity(self):
        self.uv_fixture('uv0117-virtualenv-startup-v1')
        self.assertEqual(self.observer(self.request)['status'], 'VERIFIED')
        self.assertEqual(self.observer(self.request), self.observer(deepcopy(self.request)))

    def test_uv_profiles_reject_cross_version_cross_bytes_and_renamed_claims(self):
        profiles = ('uv0117-virtualenv-startup-v1', module.UV_STARTUP_PROFILE)
        for profile in profiles:
            other = profiles[1] if profile == profiles[0] else profiles[0]
            other_version, other_pins = module.UV_STARTUP_PROFILES[other]
            other_source = _UV_STARTUP_SOURCE if other_version == '0.12.19' else _UV_0117_STARTUP_SOURCE
            for options in ({'cfg_version': other_version}, {'source': other_source},
                            {'declared_profile': 'uv-unreviewed-startup-v1'},
                            {'declared_profile': other}, {'declared_files': other_pins}):
                with self.subTest(profile=profile, changed=next(iter(options))):
                    case = ResearchEnvironmentObserverTests()
                    case.setUp()
                    try:
                        case.uv_fixture(profile, **options)
                        self.assertEqual(case.observer(case.request)['status'], 'UNKNOWN')
                    finally:
                        case.doCleanups()

    def test_uv_new_startup_file_or_modified_script_at_final_recheck_unknown(self):
        original = module._uv_interpreter
        # This legacy fixture contains only uv startup files. Complete setuptools
        # profiles use the full-site fixture in test_research_inventory_profile.
        for profile in ('uv0117-virtualenv-startup-v1', module.UV_STARTUP_PROFILE):
            for modification in ('new-pth', 'modified-script'):
                with self.subTest(profile=profile, modification=modification):
                    case = ResearchEnvironmentObserverTests()
                    case.setUp()
                    try:
                        case.uv_fixture(profile)
                        self.assertEqual(case.observer(case.request)['status'], 'VERIFIED')
                        calls = []
                        def final_mutation(*args, **kwargs):
                            calls.append(True)
                            if len(calls) == 2:
                                if modification == 'new-pth':
                                    case.write(case.site / 'late-injection.pth', b'import unreviewed')
                                else:
                                    path = case.site / '_virtualenv.py'
                                    path.write_bytes(path.read_bytes() + b'\n# changed')
                            return original(*args, **kwargs)
                        with patch.object(module, '_uv_interpreter', side_effect=final_mutation):
                            self.assertEqual(case.observer(case.request)['status'], 'UNKNOWN')
                        self.assertEqual(len(calls), 2)
                    finally:
                        case.doCleanups()

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
