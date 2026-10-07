"""Exact PR50 independent installation handoff; never opens databaseUrlFile or starts work."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import ast
from email.parser import BytesParser
import hashlib
import importlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import re
import sys
import zipfile

HEAD = '997013114a8c533c84078d174b220e541ea19f9a'
MANIFEST = '88ef46197ef41845edaf4c99e531a12fd12e69c8f29a811150dab9324de8febb'
SOURCE_FILES = 603
PACKAGE_FILES = 135

def need(ok):
    if not ok:
        raise ValueError('INSTALL_CLOSURE_REJECTED')

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def save(p, value):
    with p.open('xb') as f:
        os.chmod(p, 0o600)
        f.write(value if isinstance(value, bytes) else (json.dumps(value, sort_keys=True, indent=2)+'\n').encode())

def versions(site):
    rows = {}
    for p in sorted(site.glob('*.dist-info/METADATA')):
        m = BytesParser().parsebytes(p.read_bytes())
        name = re.sub('[-_.]+', '-', m['Name']).lower()
        need(name not in rows and bool(re.fullmatch('[a-z0-9][a-z0-9-]*', name)))
        need(bool(re.fullmatch('[A-Za-z0-9.+!_-]+', m['Version'])))
        rows[name] = m['Version']
    return rows

def source(args):
    need(sha(args.manifest) == MANIFEST)
    m = json.loads(args.manifest.read_bytes())
    need(m['head'] == HEAD and len(m['files']) == SOURCE_FILES)
    need(len({row['path'] for row in m['files']}) == SOURCE_FILES)
    for row in m['files']:
        need(not Path(row['path']).is_absolute() and '..' not in Path(row['path']).parts)
        p = args.source / row['path']
        need(p.is_file() and not p.is_symlink() and sha(p) == row['sha256'])
    rows = {r['path'][len('platform/'):]: r['sha256'] for r in m['files']
            if r['path'].startswith('platform/agent_factory/')}
    need(len(rows) == PACKAGE_FILES)
    for name in rows:
        if name.endswith('.py'):
            ast.parse((args.source/'platform'/name).read_bytes())
    return rows

def verify_wheel(path, rows):
    with zipfile.ZipFile(path) as z:
        dist = 'department_agent_factory-0.2.0.dist-info/'
        need(len(z.namelist()) == len(set(z.namelist())))
        need(all(n.startswith(('agent_factory/', dist)) and '..' not in Path(n).parts for n in z.namelist()))
        metadata = BytesParser().parsebytes(z.read(dist+'METADATA'))
        need(metadata['Name'] == 'department-agent-factory' and metadata['Version'] == '0.2.0')
        names = [n for n in z.namelist() if n.startswith('agent_factory/') and not n.endswith('/')]
        need(set(names) == set(rows) and len(names) == len(rows))
        need(all(hashlib.sha256(z.read(n)).hexdigest() == rows[n] for n in rows))

def main():
    a = argparse.ArgumentParser()
    a.add_argument('mode', choices=['source', 'snapshot', 'wheel', 'final'])
    for key in ['old-site', 'evidence', 'source', 'manifest', 'wheel', 'project', 'venv', 'config']:
        a.add_argument('--'+key, type=Path)
    args = a.parse_args()
    need(sys.dont_write_bytecode and sys.flags.isolated)
    if args.mode == 'source':
        source(args)
        print('EXACT_PR50_SOURCE_PASS')
        return
    if args.mode == 'snapshot':
        v = versions(args.old_site)
        need(len(v) == 95 and v.get('department-agent-factory') == '0.2.0')
        save(args.evidence/'old-versions.json', v)
        save(args.evidence/'constraints.txt', ''.join(f'{k}=={v[k]}\n' for k in sorted(v)).encode())
        print('OLD_95_VERSIONS_CAPTURED')
        return
    rows = source(args)
    payload_sha = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    verify_wheel(args.wheel, rows)
    if args.mode == 'wheel':
        save(args.evidence/'wheel-verification.json', {'head':HEAD,'wheelSha256':sha(args.wheel),
             'sourceManifestSha256':MANIFEST,'packageFiles':len(rows),'sourceFiles':SOURCE_FILES,
             'packagePayloadSha256':payload_sha})
        print('EXACT_SOURCE_WHEEL_PASS')
        return
    need(sys.dont_write_bytecode and sys.version_info[:3] == (3,12,13))
    need(Path(sys.prefix) == args.venv and Path(sys.base_prefix) != args.venv)
    site = args.venv/'lib/python3.12/site-packages'
    need(not any(site.rglob('*.pyc')))
    need(versions(site) == json.loads((args.evidence/'old-versions.json').read_bytes()))
    actual = {str(p.relative_to(site)) for p in (site/'agent_factory').rglob('*') if p.is_file()}
    need(actual == set(rows))  # Fresh -B install: no stale files or pyc accepted.
    need(all(not (site/n).is_symlink() and (site/n).stat().st_nlink == 1 and sha(site/n) == h for n,h in rows.items()))
    for p in site.glob('*.dist-info/direct_url.json'):
        need(not json.loads(p.read_bytes()).get('dir_info',{}).get('editable',False))
    # Verify every direct Factory import/symbol across both entrypoints, including
    # lazy function-local imports. Imports instantiate no app and submit no work.
    roots = set()
    symbols = []
    for name in ('run_research_baseline.py','bootstrap_research_control.py'):
        tree = ast.parse((args.source/'scripts'/name).read_bytes())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('agent_factory'):
                roots.add(node.module)
                symbols.extend((node.module,n.name) for n in node.names if n.name != '*')
            elif isinstance(node, ast.Import):
                roots.update(n.name for n in node.names if n.name.startswith('agent_factory'))
    roots.update('agent_factory.'+p.stem for p in (site/'agent_factory').glob('research_bootstrap_*.py'))
    roots.add('agent_factory.research_torch_runtime')
    with open(os.devnull, 'w') as sink, redirect_stdout(sink), redirect_stderr(sink):
        for name in sorted(roots):
            importlib.import_module(name)
    for module,name in symbols:
        need(hasattr(sys.modules[module],name))
    for name,module in list(sys.modules.items()):
        if name == 'agent_factory' or name.startswith('agent_factory.'):
            origin = module.__file__
            need(isinstance(origin, str) and Path(origin).is_relative_to(site/'agent_factory'))
    need('torch' not in sys.modules)  # No scientific runtime/GPU startup here.
    from agent_factory.main import create_app
    from agent_factory.config import Settings
    from agent_factory.research_bootstrap_policy import development_settings, REVISION
    need('diagnostics' in inspect.signature(create_app).parameters)
    s = development_settings(Settings(db_url='sqlite://',workspace=args.evidence/'unused',max_workers=1,temporary_policy='admin-review'))
    need(s.material_policy_revision == s.policy_revision == REVISION == 'task-research-bootstrap-v1')
    need(s.runtime_tool_contract == 'research-bootstrap-v1' and s.plan_review_ttl_seconds == 86400)
    sys.path.insert(0,str(args.source/'scripts'))  # Scripts only; never platform/PYTHONPATH.
    import run_research_baseline as runner
    c = runner.config_from_bytes(runner.read_private(args.config,2*1024**2))
    need(Path(sys.executable).resolve() == Path(c['interpreterTarget']))
    need(sha(Path(c['interpreterTarget'])) == c['interpreterSha256'])
    c.update(projectRoot=str(args.project),venvRoot=str(args.venv),
             workspace=str(args.evidence/'diagnostic-workspace'),requestId='pr50-install-closure-diagnostic')
    c = runner.config_from_bytes(json.dumps(c).encode())
    need(not Path(c['workspace']).exists())
    runner.runtime_identity(c)
    save(args.evidence/'diagnostic-config.json',c)
    from agent_factory.research_bootstrap_inventory import build_inventory
    from agent_factory.research_interpreter import capture_interpreter_contract
    inv = build_inventory(project_root=c['projectRoot'],venv_root=c['venvRoot'],
        interpreter_target=c['interpreterTarget'],interpreter_sha256=c['interpreterSha256'],
        approved_interpreter_roots=c['approvedInterpreterRoots'],inventory_path=args.evidence/'inventory.json',
        startup_profile='uv0117-setuptools82-local-v1')
    save(args.evidence/'inventory.json',inv['inventoryBytes'])
    save(args.evidence/'kernel.json',inv['kernelBytes'])
    contract = capture_interpreter_contract(**inv['captureKwargs'])
    save(args.evidence/'interpreter-contract.json',contract.encode())
    need(not any(site.rglob('*.pyc')))
    save(args.evidence/'installation-identity.json',{'head':HEAD,'wheelSha256':sha(args.wheel),
         'sourceManifestSha256':MANIFEST,'packagePayloadSha256':payload_sha,
         'packageFiles':len(rows),'packageCount':len(versions(site)),'packageVersions':versions(site),'importsChecked':sorted(roots),
         'projectRoot':str(args.project),'venvRoot':str(args.venv),
         'pins':{n:sha(p) for n,p in {'pyproject':args.project/'pyproject.toml','uvLock':args.project/'uv.lock',
          'inventory':args.evidence/'inventory.json','kernel':args.evidence/'kernel.json',
          'interpreterContract':args.evidence/'interpreter-contract.json','config':args.evidence/'diagnostic-config.json'}.items()},
         'databaseOpened':False,'executionVerified':False})
    print('INSTALLATION_CLOSURE_PASS_NO_DATABASE_NO_EXECUTION')

if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except Exception:
        print('INSTALL_CLOSURE_BLOCKED',file=sys.stderr)
        raise SystemExit(2) from None
