"""Run the research service, or use an existing member's session from a terminal."""
import argparse
from getpass import getpass
import os
import sys
import time
from urllib.parse import quote
from uuid import uuid4

import httpx


def commands():
    parser = argparse.ArgumentParser(prog='agent-factory', description='Start the service or operate a research session.')
    parser.add_argument('--url', default=os.getenv('FACTORY_LOCAL_LOGIN_ORIGIN', 'https://127.0.0.1:3100'),
                        help='HTTPS origin of the running service')
    parser.add_argument('--user', help='local account (prompts for password); alternatively set FACTORY_ACCESS_TOKEN')
    actions = parser.add_subparsers(dest='action')
    for name, description in [('worktree', 'Attach a repository in a separate session worktree'),
                              ('diff', 'Print the current patch and its review ID'),
                              ('review', 'Review the patch and its line comments using the session model'),
                              ('apply', 'Apply a displayed revision to the original checkout'),
                              ('fork', 'Continue a completed conversation in a new session')]:
        action = actions.add_parser(name, help=description)
        action.add_argument('session', help='research session ID')
        if name == 'worktree':
            action.add_argument('repository', help='absolute repository path on the service host')
        if name == 'apply':
            action.add_argument('revision', help='review ID printed by diff')
        if name == 'fork':
            action.add_argument('--turn', help='fork through this completed turn (default: latest completed)')
        if name in {'review', 'fork'}:
            action.add_argument('--request-id', help='reuse this ID to retry the same request')
    return parser


def operate(client, args):
    path = '/api/factory/research/sessions/' + quote(args.session, safe='')
    if args.action == 'worktree':
        result = client.post(path + '/git', json={'repositoryPath': args.repository}).raise_for_status().json()
        print(result['workspacePath'])
    elif args.action == 'apply':
        client.post(path + '/git/apply', json={'reviewId': args.revision}).raise_for_status()
        print('Applied', args.revision)
    elif args.action == 'fork':
        body = {'requestId': args.request_id or str(uuid4())}
        if args.turn:
            body['turnId'] = args.turn
        print(client.post(path + '/fork', json=body).raise_for_status().json()['id'])
    else:
        state = client.get(path + '/git').raise_for_status().json()
        if not state['configured']:
            raise SystemExit('Attach a repository with agent-factory worktree first.')
        if args.action == 'diff':
            print('Review ID:', state['reviewId'])
            print(state['diff'], end='')
            return
        request_id = args.request_id or str(uuid4())
        print('Review request:', request_id, file=sys.stderr, flush=True)
        detail = client.post(path + '/git/review', json={'requestId': request_id, 'reviewId': state['reviewId']}
                             ).raise_for_status().json()
        while True:
            turn = next(item for item in detail['turns'] if item['requestId'] == request_id)
            if turn['status'] == 'completed':
                print(turn['result'])
                return
            if turn['status'] in {'failed', 'canceled'}:
                raise SystemExit(turn.get('failure') or turn['status'])
            time.sleep(1)
            detail = client.get(path).raise_for_status().json()


def main(argv=None):
    args = commands().parse_args(argv)
    if not args.action:
        from .research import main as serve
        return serve()
    origin = args.url.rstrip('/')
    if httpx.URL(origin).scheme != 'https':
        raise SystemExit('Use the HTTPS origin of the running service.')
    try:
        with httpx.Client(base_url=origin, headers={'Origin': origin}, timeout=None) as client:
            token = os.getenv('FACTORY_ACCESS_TOKEN')
            if token and not args.user:
                client.headers['Authorization'] = 'Bearer ' + token
                operate(client, args)
                return
            user = args.user or input('Username: ')
            client.post('/api/factory/auth/local-login', json={'username': user, 'password': getpass()}
                        ).raise_for_status()
            session = client.get('/api/factory/auth/session').raise_for_status().json()
            client.headers['X-Factory-CSRF'] = session['csrfToken']
            try:
                operate(client, args)
            finally:
                client.post('/api/factory/auth/logout').raise_for_status()
    except httpx.HTTPStatusError as error:
        raise SystemExit(f'HTTP {error.response.status_code}: {error.response.text}') from None
    except httpx.RequestError as error:
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main()
