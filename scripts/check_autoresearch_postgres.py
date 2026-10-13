"""Required native session-admission/ledger fixtures; skips cannot pass CI."""
import json
import os
from pathlib import Path
import sys
import unittest


def main():
    if not os.environ.get('FACTORY_TEST_DATABASE_URL'):
        print('AUTORESEARCH_POSTGRES_REQUIRED', file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / path) for path in
        ('platform', 'apps/research', 'deployment', 'platform/tests', 'apps/research/tests/python')]
    suite = unittest.defaultTestLoader.loadTestsFromName('test_autoresearch_postgres')
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_autoresearch_session_control_postgres'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_autoresearch_scientific_children_postgres'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_remote_scientific_integration'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_remote_scientific_debit_postgres'))
    expected = suite.countTestCases()
    if expected != 11:
        print('AUTORESEARCH_POSTGRES_CASE_COUNT', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    accepted = result.wasSuccessful() and not result.skipped and result.testsRun == expected
    print(json.dumps({'suite': 'autoresearch_native_fixture', 'testsRun': result.testsRun,
        'skipped': len(result.skipped), 'requiredCases': expected, 'accepted': accepted,
        'liveModelVerified': False, 'scientificConclusionVerified': False}))
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
