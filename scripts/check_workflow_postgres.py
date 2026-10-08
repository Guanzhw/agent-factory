"""Required representative synthetic workflow acceptance; skips cannot pass."""
import json
import os
from pathlib import Path
import sys
import unittest


def main():
    if not os.environ.get('FACTORY_TEST_DATABASE_URL'):
        print('WORKFLOW_POSTGRES_REQUIRED', file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'platform/tests'), str(root / 'platform')]
    suite = unittest.defaultTestLoader.discover(str(root / 'platform/tests'),
        pattern='test_workflow_native_postgres.py')
    expected = suite.countTestCases()
    if expected != 4:
        print('WORKFLOW_POSTGRES_CASE_COUNT', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    accepted = result.wasSuccessful() and not result.skipped and result.testsRun == expected
    print(json.dumps({'suite': 'workflow_native_fixture', 'testsRun': result.testsRun,
        'skipped': len(result.skipped), 'requiredCases': expected, 'accepted': accepted,
        'modelLive': False, 'externalBackendVerified': False, 'convertDVerified': False}))
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
