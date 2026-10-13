"""Run both owned test trees; preserve each unittest discovery and failure exit."""
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ('platform', 'apps/research', 'deployment', 'platform/tests', 'apps/research/tests/python')


def main():
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join([*(str(ROOT / path) for path in SOURCES),
                                       *([env['PYTHONPATH']] if env.get('PYTHONPATH') else [])])
    results = [subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', directory, '-v'],
                             cwd=ROOT, env=env).returncode
               for directory in ('platform/tests', 'apps/research/tests/python')]
    return 1 if any(results) else 0


if __name__ == '__main__':
    raise SystemExit(main())
