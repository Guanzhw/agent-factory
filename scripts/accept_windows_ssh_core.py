"""Install a supplied core wheel in an isolated Windows environment and run acceptance."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        json.dump({'status': 'NOTRUN', 'wrapperStage': 'installation'}, stream)
    if sys.platform != 'win32':
        output.write_text(json.dumps({'status': 'BLOCKED', 'reason': 'WINDOWS_REQUIRED'}))
        return 1
    checkout = Path(__file__).resolve().parents[1]
    wheel = args.wheel.resolve(strict=True)
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    env.pop('VIRTUAL_ENV', None)
    stage = 'installation'
    environment = None
    try:
        with TemporaryDirectory(prefix='af-installed-core-') as temporary:
            root = Path(temporary) / ('独立核心验收' * 5)
            root.mkdir()
            requirements = root / 'requirements.txt'
            subprocess.run(['uv', 'export', '--frozen', '--no-dev', '--no-emit-project', '--no-hashes',
                            '--output-file', str(requirements)], cwd=checkout, env=env,
                           check=True, timeout=120, stdout=subprocess.DEVNULL)
            environment = root / 'venv'
            subprocess.run(['uv', 'venv', '--python', sys.executable, str(environment)],
                           cwd=root, env=env, check=True, timeout=60)
            python = environment / 'Scripts' / 'python.exe'
            subprocess.run(['uv', 'pip', 'install', '--python', str(python), '-r', str(requirements)],
                           cwd=root, env=env, check=True, timeout=180)
            subprocess.run(['uv', 'pip', 'install', '--python', str(python), '--no-deps', str(wheel)],
                           cwd=root, env=env, check=True, timeout=60)
            runner = root / 'windows_ssh_core_acceptance.py'
            shutil.copyfile(checkout / 'platform/tests/windows_ssh_core_acceptance.py', runner)
            env.update({'TEMP': str(root), 'TMP': str(root)})
            stage = 'acceptance'
            result = subprocess.run([str(python), '-I', str(runner), '--environment', str(environment),
                                     '--checkout', str(checkout), '--output', str(output)],
                                    cwd=root, env=env, timeout=180)
    except Exception as error:
        report = json.loads(output.read_text(encoding='utf-8')) if output.exists() else {}
        report.update(status='FAIL',
                      wrapperStage=stage, failureType=type(error).__name__,
                      freshEnvironmentRemoved=environment is not None and not environment.exists())
        if isinstance(error, subprocess.CalledProcessError):
            report['wrapperExitCode'] = error.returncode
        output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        return 1

    report = json.loads(output.read_text(encoding='utf-8'))
    report['freshEnvironmentRemoved'] = environment is not None and not environment.exists()
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
