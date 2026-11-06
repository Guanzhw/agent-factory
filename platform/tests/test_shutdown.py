"""Official CLI wiring and real Uvicorn exits, with no database or provider calls."""
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from agent_factory import shutdown


CLI_FIXTURE = r'''
import asyncio, runpy, signal, sys, threading, time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from fastapi import FastAPI
from agent_factory import shutdown
import agent_factory.main as core
import agent_factory_server.main as deployment

launcher, mode = sys.argv[1:]
settings = SimpleNamespace(host='127.0.0.1', port=0)
core.Settings.from_env = classmethod(lambda cls: settings)

if mode == 'stall':
    real_timer = threading.Timer
    def quick_timer(interval, callback, args=()):
        assert interval == 35
        return real_timer(.1, callback, args=args)
    shutdown.threading.Timer = quick_timer

def fixture_app(settings, *, shutdown_guard=None, **kwargs):
    assert shutdown_guard is shutdown.shutdown_guard
    @asynccontextmanager
    async def lifespan(app):
        # Exercise Uvicorn's own signal handler and shutdown implementation.
        asyncio.get_running_loop().call_later(.5, signal.raise_signal, signal.SIGINT)
        yield
        with shutdown_guard():
            if mode == 'failure':
                raise RuntimeError('synthetic cleanup failure')
            if mode == 'stall':
                time.sleep(60)
        print('CLEAN_SHUTDOWN', flush=True)
    app = FastAPI(lifespan=lifespan)
    app.state.factory = {}
    return app

core.create_app = fixture_app
deployment.create_core_app = fixture_app
runpy.run_module(launcher, run_name='__main__')
'''


class ShutdownTests(unittest.TestCase):
    def test_guard_preserves_the_35_second_budget_and_cancels_on_clean_exit(self):
        with patch.object(shutdown.time, 'monotonic', return_value=100), \
                patch.object(shutdown.threading, 'Timer') as timer:
            with shutdown.shutdown_guard() as deadline:
                self.assertEqual(deadline, 135)
            timer.assert_called_once_with(35, shutdown.shutdown_failed, args=({'reason': 'deadline'},))
            timer.return_value.start.assert_called_once_with()
            timer.return_value.cancel.assert_called_once_with()

    def test_legacy_deployment_exports_are_the_same_policy(self):
        from agent_factory_server import shutdown as legacy
        self.assertIs(legacy.shutdown_guard, shutdown.shutdown_guard)
        self.assertIs(legacy.shutdown_failed, shutdown.shutdown_failed)

    def test_both_official_clis_exit_on_normal_failed_and_stalled_cleanup(self):
        root = Path(__file__).resolve().parents[2]
        env = {**os.environ, 'PYTHONPATH': os.pathsep.join(str(root / part)
            for part in ('platform', 'deployment', 'applications'))}
        for launcher in ('agent_factory', 'agent_factory_server'):
            for mode in ('normal', 'failure', 'stall'):
                with self.subTest(launcher=launcher, mode=mode):
                    result = subprocess.run([sys.executable, '-c', CLI_FIXTURE, launcher, mode],
                        cwd=root, env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0 if mode == 'normal' else 1, result.stdout + result.stderr)
                    self.assertEqual('CLEAN_SHUTDOWN' in result.stdout, mode == 'normal')


if __name__ == '__main__':
    unittest.main()
