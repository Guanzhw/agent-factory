"""Run only explicit daily selections; manual full runners keep all discovery."""
import argparse
import json
import os
import sys
import time

from check_postgres import collect, run_checks
from check_python import CollectionError, configure_imports
from fast_test_groups import FAST_POSTGRES_TESTS, FAST_PYTHON_TESTS


def inventory(test_directories=None, selections=None):
    selections = selections if selections is not None else {
        'python': FAST_PYTHON_TESTS, 'postgres': FAST_POSTGRES_TESTS}
    if set(selections) != {'python', 'postgres'} or any(not groups for groups in selections.values()):
        raise CollectionError('Both fast lanes must have nonempty explicit groups')
    requirements = {f'{lane}/{group}': selectors for lane, groups in selections.items()
        for group, selectors in groups.items()}
    discovered, expanded = collect(test_directories, requirements)
    lanes = {lane: {group: expanded[f'{lane}/{group}'] for group in groups}
        for lane, groups in selections.items()}
    identities = {lane: set().union(*groups.values()) for lane, groups in lanes.items()}
    overlap = identities['python'] & identities['postgres']
    if overlap:
        raise CollectionError('Fast lanes overlap: ' + ', '.join(sorted(overlap)))
    # The existing full runners still execute this entire discovery, including
    # newly added tests. Unselected tests are deferred, never deleted/filtered.
    full = set(discovered)
    daily = set().union(*identities.values())
    return discovered, lanes, {'full': full, 'fast': identities, 'manualOnly': full - daily}


def execute(lane, discovered, groups, coverage, *, stream=None):
    started = time.perf_counter()
    result, summary = run_checks(discovered, groups, subset=True, stream=stream)
    summary.update(suite=f'fast_{lane}', mode='fast', fullAcceptance=False,
        fullDiscovered=len(coverage['full']), selectedCases=len(coverage['fast'][lane]),
        manualOnlyCases=len(coverage['manualOnly']), elapsedSeconds=round(time.perf_counter() - started, 3))
    return result, summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('python', 'postgres'), required=True)
    parser.add_argument('--collect-only', action='store_true', help='Validate selection without executing tests')
    args = parser.parse_args(argv)
    if args.suite == 'postgres' and not args.collect_only:
        if sys.platform != 'linux' or not os.environ.get('FACTORY_TEST_DATABASE_URL'):
            print('FAST_POSTGRES_REQUIRED: Linux and a disposable FACTORY_TEST_DATABASE_URL are required', file=sys.stderr)
            return 1
    configure_imports()
    started = time.perf_counter()
    try:
        discovered, lanes, coverage = inventory()
    except CollectionError as error:
        print(f'FAST_COLLECTION_FAILED: {error}', file=sys.stderr)
        return 1
    collection_seconds = round(time.perf_counter() - started, 3)
    if args.collect_only:
        print(json.dumps({'mode': 'fast', 'suite': args.suite, 'executed': False,
            'selectionValid': True, 'fullDiscovered': len(coverage['full']),
            'selectedCases': len(coverage['fast'][args.suite]),
            'manualOnlyCases': len(coverage['manualOnly']), 'collectionSeconds': collection_seconds}))
        return 0
    _, summary = execute(args.suite, discovered, lanes[args.suite], coverage)
    summary['collectionSeconds'] = collection_seconds
    print(json.dumps(summary))
    return 0 if summary['accepted'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
