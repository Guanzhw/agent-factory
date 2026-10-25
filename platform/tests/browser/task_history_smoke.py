"""Built Chromium task-history regression against synthetic HTTP responses only.

Build with npm run build, then run this script using existing Playwright/Chromium.
No dependency installation, live Factory server, provider call or task execution.
"""
from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
from threading import Thread
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[3]


def summary(number):
    task_id = f'task-{number:03d}'
    return {'id': task_id, 'ownerId': 'alice', 'planId': 'synthetic-plan',
            'definitionId': 'synthetic-definition', 'definitionVersion': 1,
            'input': {'topic': task_id, 'mode': 'literature', 'scenario': 'normal'},
            'status': 'completed', 'createdAt': '2026-10-01T00:00:00Z',
            'updatedAt': '2026-10-01T00:00:00Z', 'observedAt': '2026-10-01T00:00:00Z'}


class SyntheticAPI:
    def __init__(self, base):
        self.base = base
        self.rows = [summary(number) for number in range(150, 0, -1)]
        self.active_workers = 1
        self.requests, self.violations, self.rejections = [], [], []

    def reject(self, route, message):
        self.violations.append(message)
        route.abort()

    def intercept(self, route):
        request = route.request
        url = urlsplit(request.url)
        if f'{url.scheme}://{url.netloc}' != self.base:
            self.reject(route, 'External request: ' + request.url)
            return
        if request.method != 'GET':
            self.reject(route, 'Unexpected mutation: ' + request.url)
            return
        if not url.path.startswith('/api/'):
            if url.path == '/' or url.path.startswith('/assets/'):
                route.continue_()
            else:
                self.reject(route, 'Unexpected static request: ' + request.url)
            return
        path = url.path.removeprefix('/api/factory')
        query = parse_qs(url.query)
        record = {'method': request.method, 'path': path, 'query': query}
        self.requests.append(record)
        values = {
            '/auth/config': {'enabled': False, 'loginPath': '/api/factory/auth/login',
                             'logoutPath': '/api/factory/auth/logout'},
            '/session': {'id': 'alice', 'name': 'Synthetic Alice', 'role': 'user'},
            '/status': {'mode': 'demo', 'activeWorkers': self.active_workers, 'queuedJobs': 0,
                        'maxWorkers': 8, 'integration': 'Synthetic browser fixture'},
            '/execution-targets': [], '/commands': {'items': [], 'nextCursor': None},
        }
        if path == '/materials':
            self.rejections.append(request.url)
            route.fulfill(status=503, json={'message': 'Synthetic catalog unavailable'})
            return
        if path == '/jobs':
            if query.get('limit') != ['50']:
                self.reject(route, 'Expected a bounded 50-row request')
                return
            cursor = query.get('cursor', [None])[0]
            ids = [row['id'] for row in self.rows]
            if cursor is not None and cursor not in ids:
                self.reject(route, 'Unknown synthetic cursor: ' + cursor)
                return
            offset = ids.index(cursor) + 1 if cursor else 0
            items = self.rows[offset:offset + 50]
            result = {'items': items, 'nextCursor': items[-1]['id'] if offset + 50 < len(ids) else None}
            record['returnedIds'] = [row['id'] for row in items]
        elif path.startswith('/jobs/') and path.count('/') == 2:
            task_id = path.rsplit('/', 1)[1]
            row = next((row for row in self.rows if row['id'] == task_id), None)
            if row is None:
                self.reject(route, 'Unknown task: ' + task_id)
                return
            result = {'job': {**row, 'runtime': 'demo', 'attempt': 1, 'allowedActions': [],
                              'binding': {}, 'definition': {'id': 'synthetic-definition', 'version': 1}},
                      'events': [], 'artifacts': [], 'snapshot': {}}
        elif path.startswith('/workflows/task-') and path.count('/') == 2:
            result = {'available': False}
        elif path in values:
            result = values[path]
        else:
            self.reject(route, 'Unconfigured API read: ' + path)
            return
        route.fulfill(status=200, json=result)


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def scenario(browser, base, output):
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, service_workers='block')
    api = SyntheticAPI(base)
    context.route('**/*', api.intercept)

    def websocket(socket):
        api.violations.append('Unexpected WebSocket: ' + socket.url)
        socket.close()
    context.route_web_socket('**/*', websocket)
    page = context.new_page()
    page.set_default_timeout(15000)
    expect.set_options(timeout=15000)
    errors, console_errors = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('console', lambda message: console_errors.append({'text': message.text, 'location': message.location})
            if message.type == 'error' else None)
    try:
        page.goto(base + '/?tab=tasks', wait_until='networkidle')
        rows = page.locator('.task-row')
        expect(rows).to_have_count(50)
        expect(page.locator('.sync-state')).to_contain_text('部分区域更新失败')
        earlier = page.get_by_role('button', name='加载更早任务', exact=True)
        earlier.focus()
        expect(earlier).to_be_focused()
        page.keyboard.press('Enter')
        expect(rows).to_have_count(100)
        old = rows.filter(has=page.locator('strong', has_text='task-060'))
        old.focus()
        expect(old).to_be_focused()
        page.keyboard.press('Space')
        detail = page.get_by_role('region', name='任务详情', exact=True)
        expect(detail.get_by_role('heading', name='task-060', exact=True)).to_be_visible()
        expect(old).to_have_attribute('aria-pressed', 'true')
        newer = rows.filter(has=page.locator('strong', has_text='task-150'))
        newer.focus()
        page.keyboard.press('Enter')
        expect(detail.get_by_role('heading', name='task-150', exact=True)).to_be_visible()
        page.go_back()
        expect(detail.get_by_role('heading', name='task-060', exact=True)).to_be_visible()
        expect(old).to_have_attribute('aria-pressed', 'true')
        assert parse_qs(urlsplit(page.url).query)['task'] == ['task-060']
        page.screenshot(path=str(output / 'history-keyboard-back.png'), full_page=True)

        before = {path: sum(row['path'] == path for row in api.requests)
                  for path in ['/status', '/execution-targets', '/materials']}
        api.rows[0:0] = [summary(number) for number in range(255, 150, -1)]
        api.active_workers = 7
        # Use the actual timer, not an injected React hook or a manual refresh.
        expect(rows).to_have_count(205)
        expect(page.locator('.worker-metrics b').first).to_have_text('7')
        expect(detail.get_by_role('heading', name='task-060', exact=True)).to_be_visible()
        visible_ids = rows.locator('strong').all_text_contents()
        assert visible_ids == [row['id'] for row in api.rows[:205]], visible_ids
        assert len(set(visible_ids)) == 205
        for path, count in before.items():
            assert sum(row['path'] == path for row in api.requests) > count, path
        expect(page.locator('.sync-state')).to_contain_text('部分区域更新失败')
        earlier.focus()
        page.keyboard.press('Enter')
        expect(rows).to_have_count(255)
        assert rows.locator('strong').all_text_contents() == [row['id'] for row in api.rows]
        expect(earlier).to_have_count(0)
        expect(old).to_have_attribute('aria-pressed', 'true')
        expect(detail.get_by_role('heading', name='task-060', exact=True)).to_be_visible()
        page.screenshot(path=str(output / 'history-complete.png'), full_page=True)
        assert not errors, errors
        assert not api.violations, api.violations
        expected_console = [error for error in console_errors
                            if error['location'].get('url') in api.rejections and
                            error['text'] == 'Failed to load resource: the server responded with a status of 503 (Service Unavailable)']
        assert len(expected_console) == len(console_errors), console_errors
        return {'result': 'passed', 'tasks': 255, 'insertedBetweenPolls': 105,
                'keyboard': ['Enter', 'Space'], 'browserBack': True,
                'apiRequests': api.requests, 'injectedCatalogFailures': len(api.rejections),
                'expectedConsoleErrors': expected_console, 'pageErrors': errors,
                'externalRequests': 0, 'mutations': 0, 'modelCalls': 0}
    except Exception:
        page.screenshot(path=str(output / 'failure.png'), full_page=True)
        (output / 'failure.json').write_text(json.dumps({'requests': api.requests,
            'violations': api.violations, 'pageErrors': errors, 'consoleErrors': console_errors,
            'body': page.locator('body').inner_text()}, ensure_ascii=False, indent=2))
        raise
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=ROOT / 'dist')
    parser.add_argument('--browser', help='Existing Chromium executable')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not (args.dist / 'index.html').is_file():
        parser.error('Requires existing dist/index.html; run npm run build first')
    output = args.output or Path(tempfile.mkdtemp(prefix='af-task-history-browser-'))
    output.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(args.dist)))
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=args.browser, headless=True)
            try:
                result = scenario(browser, f'http://127.0.0.1:{server.server_port}', output)
                (output / 'results.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
                print(json.dumps({'result': result['result'], 'output': str(output), 'liveRuntimeVerified': False}))
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
