"""Run PostgreSQL discovery once; selected acceptance cases must actually pass.

No model/provider request is made by this runner. Tests retain their existing
synthetic fixtures and platform skips; only required selectors reject skips.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import unittest

from check_python import CollectionError, cases, configure_imports, discover_tests, report_test_failures
from postgres_requirements import REQUIRED_TESTS


def collect(test_directories, requirements, *, loader=None):
    if not requirements:
        raise CollectionError('No required groups configured')
    loader = loader or unittest.TestLoader()
    discovered = discover_tests(test_directories, loader=loader)
    required = {}
    for group, selectors in requirements.items():
        if not selectors:
            raise CollectionError(f'{group}: no required selectors')
        selected = set()
        for selector in selectors:
            found = {case.id() for case in cases(loader.loadTestsFromName(selector))}
            if loader.errors:
                raise CollectionError(f'{group}: {selector}\n' + '\n'.join(loader.errors))
            if not found:
                raise CollectionError(f'{group}: selector has no tests: {selector}')
            missing = found - discovered.keys()
            if missing:
                raise CollectionError(f'{group}: required tests absent from discovery: ' + ', '.join(sorted(missing)))
            selected.update(found)
        required[group] = selected
    return discovered, required


class AcceptanceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.successful_ids = set()

    def addSuccess(self, test):
        self.successful_ids.add(test.id())
        super().addSuccess(test)


def run_checks(discovered, required, *, subset=False, stream=None, resultclass=None):
    """Consume discovered so unittest can release each completed test instance."""
    selected = set().union(*required.values()) if subset else set(discovered)
    # One original instance per ID, even when multiple groups select it.
    suite = unittest.TestSuite(case for identity, case in discovered.items() if identity in selected)
    discovered.clear()
    result = unittest.TextTestRunner(stream=stream, verbosity=2,
        resultclass=AcceptanceResult if resultclass is None else resultclass).run(suite)
    groups = {group: {'requiredCases': len(identities),
        'passed': len(identities & result.successful_ids),
        'notPassed': sorted(identities - result.successful_ids)}
        for group, identities in required.items()}
    accepted = not result.shouldStop and result.wasSuccessful() and all(not group['notPassed'] for group in groups.values())
    return result, {'suite': 'postgres_acceptance', 'testsRun': result.testsRun,
        'selected': len(selected), 'skipped': len(result.skipped),
        'failures': len(result.failures), 'errors': len(result.errors), 'shouldStop': result.shouldStop,
        'groups': groups, 'accepted': accepted,
        'modelLive': False, 'externalRemoteVerified': False, 'realCredentialsUsed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', action='append', choices=tuple(REQUIRED_TESTS),
        help='Run only this required group; repeat to select several groups')
    parser.add_argument('--summary-file', type=Path, help='Write completion JSON after the runner returns')
    args = parser.parse_args(argv)
    if not os.environ.get('FACTORY_TEST_DATABASE_URL'):
        print('POSTGRES_REQUIRED: set FACTORY_TEST_DATABASE_URL to a disposable database', file=sys.stderr)
        return 1
    if sys.platform != 'linux' and not args.group:
        print('POSTGRES_REQUIRED: full acceptance requires Linux', file=sys.stderr)
        return 1
    configure_imports()
    requirements = {group: REQUIRED_TESTS[group] for group in args.group} if args.group else REQUIRED_TESTS
    try:
        discovered, required = collect(None, requirements)
    except CollectionError as error:
        print(f'POSTGRES_COLLECTION_FAILED: {error}', file=sys.stderr)
        return 1
    result, summary = run_checks(discovered, required, subset=bool(args.group))
    report_test_failures(result)
    if (os.environ.get('GITHUB_ACTIONS') == 'true' and not summary['accepted']
            and not result.failures and not result.errors):
        message = json.dumps(summary, sort_keys=True).replace('%', '%25')
        print(f'::error::PostgreSQL required acceptance did not pass: {message}')
    if args.summary_file is not None:
        args.summary_file.write_text(json.dumps(summary) + '\n', encoding='utf-8')
    print(json.dumps(summary))
    return 0 if summary['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
