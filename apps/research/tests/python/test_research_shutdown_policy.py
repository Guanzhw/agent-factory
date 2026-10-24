"""Real deployment guard thread/exit probes with an accelerated test clock.

The Timer factory must receive the unchanged production 35 seconds. Only this
probe schedules its real thread after .05 seconds; real 35-second behavior is
covered separately by test_research_shutdown_postgres.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest


PROBE = r'''
import asyncio
import sys
import threading
import time

sys.path.insert(0, sys.argv[1])
from agent_factory_server import shutdown

real_timer = threading.Timer

def accelerated_timer(interval, function, args=None, kwargs=None):
    assert interval == 35, 'Production shutdown deadline must remain 35 seconds'
    print('PRODUCTION_TIMER_SECONDS=35', flush=True)
    return real_timer(.05, function, args=args, kwargs=kwargs)

shutdown.threading.Timer = accelerated_timer

async def main():
    with shutdown.shutdown_guard():
        if sys.argv[2] == 'blocked':
            print('EVENT_LOOP_SYNCHRONOUSLY_BLOCKED', flush=True)
            time.sleep(10)
    # Longer than the accelerated timer: proves context exit cancels it.
    time.sleep(.15)
    print('NORMAL_GUARD_RETURNED', flush=True)

asyncio.run(main())
'''


class ResearchShutdownPolicyTests(unittest.TestCase):
    def probe(self, scenario):
        project = Path(__file__).resolve().parents[4]
        environment = {name: os.environ[name] for name in
                       ('SystemRoot', 'WINDIR', 'PATH', 'LANG', 'LC_ALL', 'TEMP', 'TMP', 'TMPDIR')
                       if name in os.environ}
        process = subprocess.Popen([sys.executable, '-I', '-c', PROBE,
            str(project / 'deployment'), scenario], cwd=project, env=environment,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            output, errors = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            output, errors = process.communicate(timeout=3)
            self.fail('Production guard did not exit within the probe bound; fixture kill is not '
                      f'acceptance.\nstdout: {output}\nstderr: {errors}')
        self.assertEqual(errors, '')
        self.assertIn('PRODUCTION_TIMER_SECONDS=35', output)
        return process.returncode, output

    def test_guard_exits_nonzero_while_event_loop_is_synchronously_blocked(self):
        code, output = self.probe('blocked')
        self.assertEqual(code, 1)
        self.assertIn('EVENT_LOOP_SYNCHRONOUSLY_BLOCKED', output)
        self.assertNotIn('NORMAL_GUARD_RETURNED', output)

    def test_normal_guard_exit_cancels_real_timer_thread(self):
        code, output = self.probe('normal')
        self.assertEqual(code, 0)
        self.assertIn('NORMAL_GUARD_RETURNED', output)


if __name__ == '__main__':
    unittest.main()
