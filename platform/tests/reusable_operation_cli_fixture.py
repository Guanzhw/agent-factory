"""Synthetic CLI subprocess: explicit token injection, public business counter only."""
import json
import os
from pathlib import Path
import sys


def main():
    token = os.environ.get('REUSABLE_FIXTURE_TOKEN')
    accounts = {'synthetic-operation-token-' + name: name for name in ('alice', 'bob', 'alice-second')}
    if token not in accounts:
        raise SystemExit(77)
    arguments = json.loads(sys.stdin.buffer.read(8192))
    result = {'owner': accounts[token], 'value': arguments['value']}
    with Path(sys.argv[1]).open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(result) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
