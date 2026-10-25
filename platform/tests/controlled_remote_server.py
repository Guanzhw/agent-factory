"""Owned loopback server lifecycle shared by remote contract fixtures."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import sysconfig
import time
import httpx
from controlled_remote_worker import MANAGER, ORIGIN_OWNER, RECEIVER_OWNER, token

PROJECT = Path(__file__).resolve().parents[2]


def loopback_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class OwnedServer:
    def __init__(self, configuration, directory):
        self.configuration, self.directory = configuration, Path(directory)
        self.path = self.directory / (configuration["role"] + "-server.json")
        self.path.write_text(json.dumps(configuration), encoding="utf-8")
        self.url = "http://127.0.0.1:" + str(configuration["port"])
        self.process = self.log = None
        self.starts = []

    def start(self):
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("Owned fixture server is already running")
        environment = {**os.environ, "FACTORY_REMOTE_PROCESS_CONFIG": str(self.path),
                       "PYTHONPATH": os.pathsep.join([str(PROJECT / path) for path in
                           ("platform", "platform/tests", "deployment")] + [sysconfig.get_path("purelib")]),
                       "AGNO_TELEMETRY": "false"}
        if self.log is not None:
            self.log.close()
        self.log = (self.directory / (self.configuration["role"] + "-server.log")).open("ab")
        flags = (getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) if os.name == "nt" else 0
        # On Windows the venv executable is a redirector with a different
        # child PID. Run real CPython with the same pinned environment path
        # so the retained Popen identity owns the actual service directly.
        interpreter = getattr(sys, "_base_executable", sys.executable)
        self.process = subprocess.Popen([interpreter, "-m", "controlled_remote_worker"], cwd=PROJECT, env=environment,
            stdin=subprocess.DEVNULL, stdout=self.log, stderr=subprocess.STDOUT, creationflags=flags)
        self.starts.append(self.process.pid)
        deadline = time.monotonic() + 25
        with httpx.Client(timeout=1, trust_env=False) as client:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise AssertionError("Owned fixture startup failed: " + self.log_tail())
                try:
                    if client.get(self.url + "/api/health").status_code == 200:
                        return self
                except httpx.HTTPError:
                    pass
                time.sleep(.04)
        raise AssertionError("Owned fixture did not start: " + self.log_tail())

    def log_tail(self):
        return (self.directory / (self.configuration["role"] + "-server.log")).read_text(encoding="utf-8", errors="replace")[-5000:]

    def stop(self):
        # Popen identity is created/retained by this fixture; never enumerate or
        # kill arbitrary host processes. This workflow has no subprocess tools.
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(5)
        if self.log is not None:
            self.log.close()

    def request(self, method, path, *, actor=None, fixture=False, **kwargs):
        actor = actor or (ORIGIN_OWNER if self.configuration["role"] == "origin" else RECEIVER_OWNER)
        headers = {"Authorization": "Bearer " + token(self.configuration["jwtKey"], actor)}
        if fixture:
            headers["X-Fixture-Control"] = self.configuration["controlKey"]
        # One public instance request may await prepare, dispatch and detail,
        # each with the production handoff client's 20-second read deadline.
        # The outer fixture must allow those phases and current-authority checks
        # to finish; bounded state waits and all admission/effect proofs remain.
        read_seconds = 75 if method.upper() == "POST" and path == "/api/factory/instances" else 30
        timeout = httpx.Timeout(connect=3, read=read_seconds, write=5, pool=3)
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False) as client:
            return client.request(method, self.url + path, headers=headers, **kwargs)

    def facts(self, task=None):
        response = self.request("GET", "/__fixture/state", fixture=True, actor=MANAGER, params={"taskId": task} if task else {})
        if response.status_code != 200:
            raise AssertionError(response.text)
        return response.json()

    def control(self, op, **kwargs):
        response = self.request("POST", "/__fixture/control", fixture=True, actor=MANAGER, json={"op": op, **kwargs})
        if response.status_code != 200:
            raise AssertionError(response.text)
        return response.json()
