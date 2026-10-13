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

from postgres_requirements import REQUIRED_TESTS


class CollectionError(ValueError):
    pass


def cases(suite):
    """Keep discovery order and unittest's inherited method identities."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from cases(item)
        else:
            yield item


def collect(test_directory, requirements, *, loader=None):
    if not requirements:
        raise CollectionError('No required groups configured')
    loader = loader or unittest.TestLoader()
    discovered = {}
    for case in cases(loader.discover(str(test_directory))):
        discovered.setdefault(case.id(), case)
    if loader.errors:
        raise CollectionError('\n'.join(loader.errors))
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


def run_checks(discovered, required, *, subset=False, stream=None):
    """Consume discovered so unittest can release each completed test instance."""
    selected = set().union(*required.values()) if subset else set(discovered)
    # One original instance per ID, even when multiple groups select it.
    suite = unittest.TestSuite(case for identity, case in discovered.items() if identity in selected)
    discovered.clear()
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=AcceptanceResult).run(suite)
    groups = {group: {'requiredCases': len(identities),
        'passed': len(identities & result.successful_ids),
        'notPassed': sorted(identities - result.successful_ids)}
        for group, identities in required.items()}
    accepted = result.wasSuccessful() and all(not group['notPassed'] for group in groups.values())
    return result, {'suite': 'postgres_acceptance', 'testsRun': result.testsRun,
        'skipped': len(result.skipped), 'groups': groups, 'accepted': accepted,
        'modelLive': False, 'externalRemoteVerified': False, 'realCredentialsUsed': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', action='append', choices=tuple(REQUIRED_TESTS),
        help='Run only this required group; repeat to select several groups')
    args = parser.parse_args(argv)
    if not os.environ.get('FACTORY_TEST_DATABASE_URL'):
        print('POSTGRES_REQUIRED: set FACTORY_TEST_DATABASE_URL to a disposable database', file=sys.stderr)
        return 1
    if sys.platform != 'linux' and (not args.group or 'research_candidate_postgres' in args.group):
        print('POSTGRES_REQUIRED: full/candidate acceptance requires Linux', file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'platform/tests'), str(root / 'platform')]
    requirements = {group: REQUIRED_TESTS[group] for group in args.group} if args.group else REQUIRED_TESTS
    try:
        discovered, required = collect(root / 'platform/tests', requirements)
    except CollectionError as error:
        print(f'POSTGRES_COLLECTION_FAILED: {error}', file=sys.stderr)
        return 1
    _, summary = run_checks(discovered, required, subset=bool(args.group))
    print(json.dumps(summary))
    return 0 if summary['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
