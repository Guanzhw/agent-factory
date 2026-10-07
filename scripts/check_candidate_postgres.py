"""Run required synthetic candidate PG acceptance; any skip is a failure."""
import json
import os
from pathlib import Path
import sys
import unittest


def main():
    if sys.platform != 'linux' or not os.environ.get('FACTORY_TEST_DATABASE_URL'):
        print('CANDIDATE_POSTGRES_REQUIRED: Linux and disposable PostgreSQL required', file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'platform/tests'), str(root / 'platform')]
    suite = unittest.TestSuite(unittest.defaultTestLoader.discover(str(root / 'platform/tests'), pattern=pattern)
        for pattern in ('test_research_candidate_postgres.py', 'test_research_candidate_baseline_postgres.py',
                        'test_research_candidate_command_postgres.py', 'test_research_candidate_execute_postgres.py',
                        'test_candidate_database_auth_postgres.py'))
    expected = suite.countTestCases()
    if expected != 9:
        print('CANDIDATE_POSTGRES_REQUIRED: expected nine acceptance cases', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    accepted = result.wasSuccessful() and not result.skipped and result.testsRun == expected
    print(json.dumps({'suite': 'research_candidate_postgres', 'testsRun': result.testsRun,
                      'skipped': len(result.skipped), 'requiredCases': expected, 'accepted': accepted}))
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
