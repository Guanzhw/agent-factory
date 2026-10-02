"""Task-exclusive, pinned actual ORX local experiments for one reviewed toy recipe.

Only project registration is a narrow SQLite provisioner reproducing upstream
create_project's local-only fields. Experiments and run rows are owned by real
ORX CLI commands. No dashboard/starter/session/cloud or arbitrary-command API.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import time
from typing import Any, Iterator
from uuid import UUID, uuid4, uuid5

from .openresearch import BinaryPin, CommandResult, ExperimentBinding, OpenResearchAdapter, OpenResearchError, REVISION
from .orx_containment import TaskWindowsJob

SOURCE_ARCHIVE_SHA256 = "396ef8731e8531f676171640e04b05848c00cb23c9647ccd6cadbcbda9f9a62a"
RECIPE_SOURCE_COMMIT = "169b85d17a7faa5f15ca8bb5d7fe94ae1069b2d5"
RECIPE_ARCHIVE_SHA256 = "3feae56d2102a5d3ce9c1484747961013a0ab34003c450bcb201030c58460938"
STORE_SCHEMA_SHA256 = "21dbed4e11378f0e58792924619f9cc737f29842a499bb944159cb2926b7bc14"
TOY_FILES = {
    "baseline.py": "4e32b23be72edcd3b286b9b51921b65c10c7a4bc1bdeaa8c266f5030bcd44d8a",
    "candidate.py": "db03d04d6c875bf61e83c8933c52b90b36873465b92d1f03b3b8920488661d2b",
    "dataset.json": "aa0d0747a2fdbe2384b1c92988ea3c2272f2768d97eb33dab80056a32da5ca48",
    "evaluator.py": "e6d68ca48015ddf7ab502f9d38b1e742d56a81ef4915b8518ce231afdeff7659",
}
SCENARIOS = frozenset({"success", "evaluator_failure", "long_running"})
_TERMINAL = frozenset({"done", "failed", "cancelled"})


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise OpenResearchError("SOURCE_CHANGED", "A pinned task file is missing or linked")
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _limits(environment: Any) -> dict[str, Any]:
    def value(camel: str, snake: str) -> Any:
        return environment.get(camel) if isinstance(environment, dict) else getattr(environment, snake, None)
    timeout = value("timeoutSeconds", "timeout_seconds")
    output = value("outputBytes", "output_bytes")
    memory = value("memoryBytes", "memory_bytes")
    process = value("maxProcesses", "process_limit")
    cpu = value("cpuPercent", "cpu_percent")
    if (type(timeout) not in {int, float} or not math.isfinite(timeout) or not 5 <= timeout <= 30
            or type(output) is not int or not 8192 <= output <= 1048576
            or type(memory) is not int or not 256 * 1024**2 <= memory <= 1024**3
            or process != 8 or type(cpu) is not int or not 1 <= cpu <= 100):
        raise OpenResearchError("ENVIRONMENT_UNSUPPORTED", "ORX requires timeout5..30s, output8KiB..1MiB, memory256MiB..1GiB and eight processes")
    return {"timeoutSeconds": timeout, "outputBytes": output, "memoryBytes": memory,
            "maxProcesses": process, "cpuPercent": cpu, "cpuSeconds": max(5, math.ceil(timeout * cpu / 100))}


class TaskLocalORXAdapter(OpenResearchAdapter):
    """One original reviewed evaluator, one task-local project/experiment/launch."""
    transport_kind = "pinned_openresearch_cli_local_toy"

    def __init__(self, *, source_archive: Path, git_binary: Path, python_binary: Path,
                 environment: Any, scenario: str, cleanup_only: bool = False, **kwargs: Any):
        if scenario not in SCENARIOS:
            raise OpenResearchError("RECIPE_INVALID", "The scenario must be a reviewed toy recipe")
        self.cleanup_only = cleanup_only
        if cleanup_only and (not Path(kwargs["scope"]).is_dir() or not (Path(kwargs["scope"]) / "factory-orx-project.json").is_file()):
            raise OpenResearchError("NO_LAUNCH_INTENT", "Cleanup requires an existing task project")
        self.limits = _limits(environment)
        self.scenario = scenario
        self.source_archive = source_archive.resolve()
        self.git_binary, self.python_binary = git_binary.resolve(), python_binary.resolve()
        if not all(path.is_absolute() and path.is_file() for path in (source_archive, git_binary, python_binary)):
            raise OpenResearchError("UNVERIFIED_TOOLCHAIN", "Operator-pinned absolute toolchain paths are required")
        kwargs["search_path"] = os.pathsep.join((str(self.git_binary.parent), str(self.python_binary.parent),
                                               str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")))
        kwargs["create_scope"] = not cleanup_only
        super().__init__(**kwargs)
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=str(self.scope / "empty.gitconfig"),
            PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", ORX_NO_UPDATE_CHECK="1", NO_UPDATE_NOTIFIER="1")
        if not cleanup_only:
            (self.scope / "empty.gitconfig").touch(exist_ok=True)
        self.repo = self.scope / "toy-repository"
        self._manifest_path = self.scope / "factory-orx-project.json"
        self._setup_lock = asyncio.Lock()
        self._job: TaskWindowsJob | None = None
        self._trusted_reclaim = False
        self._manifest: dict[str, Any] | None = None

    def _verify_source(self) -> None:
        if _sha(self.source_archive) != SOURCE_ARCHIVE_SHA256:
            raise OpenResearchError("SOURCE_CHANGED", "The reviewed upstream source archive changed")
        for name, expected in TOY_FILES.items():
            if _sha(Path(__file__).parent / "orx_toy" / name) != expected:
                raise OpenResearchError("RECIPE_CHANGED", "The reviewed evaluator source changed")

    async def preflight(self) -> dict[str, str]:
        if not self._trusted_reclaim:
            self._verify_source()
        if self._manifest_path.exists():
            self._load_manifest()  # Validate original limits before reopening/reconfiguring its job.
        if self._job is None:
            self._job = TaskWindowsJob(self.task_id, self.limits)
        return await super().preflight()

    async def _allow(self, operation: str) -> None:
        if self._trusted_reclaim and operation in {"preflight", "experiment:inspect", "experiment:cancel"}:
            return
        await super()._allow(operation)

    async def _spawn(self, argv: tuple[str, ...]) -> asyncio.subprocess.Process:
        # Start suspended, attach before any user recipe or detached child can
        # execute. Detached console avoids upstream Windows MessageBoxW hangs.
        assert self._job is not None
        process = await asyncio.create_subprocess_exec(str(self.binary), *argv,
            cwd=str(self.scope), env=self.env, stdin=asyncio.subprocess.DEVNULL,
            stdout=self._capture_stdout, stderr=self._capture_stderr,
            close_fds=False, creationflags=getattr(subprocess, "DETACHED_PROCESS") | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP") | 0x4)
        try:
            self._job.admit_and_resume(process.pid)
        except BaseException:
            await self._terminate(process)
            raise
        return process

    async def _execute(self, argv: tuple[str, ...], *, timeout: float | None = None,
                       allow_failure: bool = False, operation: str = "preflight") -> CommandResult:
        self._verify_hash()
        async with self._semaphore:
            await self._allow(operation)
            self._verify_hash()
            capture = self.scope / "cli-capture"
            if not capture.resolve().is_relative_to(self.scope) or capture.is_symlink():
                raise OpenResearchError("SCOPE_INVALID", "CLI capture must remain inside the exclusive task")
            capture.mkdir(exist_ok=True)
            nonce = uuid4().hex
            stdout_path, stderr_path = capture / (nonce + ".stdout"), capture / (nonce + ".stderr")
            started = time.monotonic()
            process = None
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                self._capture_stdout, self._capture_stderr = stdout, stderr
                try:
                    process = await self._spawn(argv)
                    self._processes.add(process)
                    deadline = started + (timeout or self.command_timeout)
                    # Native Windows descendants inherit launcher handles. Files
                    # let us await the real CLI exit without false pipe-EOF waits;
                    # detached processes remain separately owned by the task job.
                    while process.returncode is None:
                        if stdout_path.stat().st_size + stderr_path.stat().st_size > self.max_output_bytes:
                            raise OpenResearchError("OUTPUT_LIMIT", "CLI output exceeded task bound")
                        if time.monotonic() >= deadline:
                            raise OpenResearchError("TIMEOUT", "CLI command exceeded task time bound")
                        await asyncio.sleep(0.02)
                    await process.wait()
                    raw_stdout, raw_stderr = stdout_path.read_bytes(), stderr_path.read_bytes()
                    if len(raw_stdout) + len(raw_stderr) > self.max_output_bytes:
                        raise OpenResearchError("OUTPUT_LIMIT", "CLI output exceeded task bound")
                    result = CommandResult(argv, raw_stdout.decode("utf-8", errors="replace"),
                        raw_stderr.decode("utf-8", errors="replace"), process.returncode,
                        time.monotonic() - started, hashlib.sha256(raw_stdout).hexdigest())
                    if result.returncode and not allow_failure:
                        raise OpenResearchError("COMMAND_FAILED", "ORX command failed; inspect task-scoped evidence", result)
                    return result
                finally:
                    if process is not None:
                        await self._terminate(process)
                        self._processes.discard(process)

    @contextmanager
    def _db(self, *, writable: bool = False) -> Iterator[sqlite3.Connection]:
        path = self.scope / "orx-store" / "orx.db"
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(self.scope):
            raise OpenResearchError("STORE_INVALID", "Task-local native ORX store is unavailable")
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode={'rw' if writable else 'ro'}", uri=True, timeout=2)
        connection.row_factory = sqlite3.Row
        shape = {table: [list(row)[1:] for row in connection.execute("pragma table_info(" + table + ")")]
                 for table in ("local_projects", "local_experiments", "runs")}
        if (connection.execute("pragma user_version").fetchone()[0] != 1
                or hashlib.sha256(_canonical(shape)).hexdigest() != STORE_SCHEMA_SHA256
                or connection.execute("select count(*) from sqlite_master where type='trigger'").fetchone()[0]):
            connection.close()
            raise OpenResearchError("STORE_SCHEMA_CHANGED", "The exact reviewed native store schema is required")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _save_manifest(self, value: dict[str, Any]) -> None:
        raw = _canonical(value)
        temp = self.scope / "factory-orx-project.tmp"
        if temp.is_symlink() or self._manifest_path.is_symlink():
            raise OpenResearchError("SCOPE_INVALID", "Task manifest cannot be linked")
        with temp.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self._manifest_path)
        self._manifest = value

    def _load_manifest(self) -> dict[str, Any] | None:
        if not self._manifest_path.exists():
            return None
        if self._manifest_path.is_symlink() or self._manifest_path.stat().st_size > 32768:
            raise OpenResearchError("SCOPE_INVALID", "Invalid task project manifest")
        value = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        if (not isinstance(value, dict) or value.get("schemaVersion") != 1
                or (value.get("ownerId"), value.get("taskId"), value.get("scenario"), value.get("limits"))
                != (self.owner_id, self.task_id, self.scenario, self.limits)
                or value.get("upstreamRevision") != REVISION or value.get("upstreamSourceArchiveSha256") != SOURCE_ARCHIVE_SHA256):
            raise OpenResearchError("BINDING_MISMATCH", "Task project belongs to another immutable binding")
        self._manifest = value
        return value

    def _git(self, *args: str) -> bytes:
        if self.repo.is_symlink() or not self.repo.resolve().is_relative_to(self.scope):
            raise OpenResearchError("SCOPE_INVALID", "Reviewed source must remain inside the exclusive task")
        completed = subprocess.run([str(self.git_binary), "-c", "core.hooksPath=", "-c", "commit.gpgSign=false", *args],
            cwd=self.repo, env=self.env, stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
            creationflags=subprocess.DETACHED_PROCESS if os.name == "nt" else 0)
        if completed.returncode or len(completed.stdout) + len(completed.stderr) > self.max_output_bytes:
            raise OpenResearchError("SOURCE_CHANGED", "The task-owned reviewed Git source could not be verified")
        return completed.stdout

    def _command_text(self) -> str:
        python = str(self.python_binary).replace("\\", "/")
        return " ".join(shlex.quote(value) for value in (python, "-I", "evaluator.py", "--task", self.task_id,
            "--owner-sha", hashlib.sha256(self.owner_id.encode()).hexdigest(), "--scenario", self.scenario,
            "--timeout", str(self.limits["timeoutSeconds"]), "--output-limit", str(self.limits["outputBytes"])))

    async def ensure_experiment(self) -> dict[str, Any]:
        async with self._setup_lock:
            if self.cleanup_only:
                raise OpenResearchError("CLEANUP_ONLY", "A cleanup handle cannot provision or launch")
            await self.preflight()
            await self._allow("experiment:run")
            value = self._load_manifest()
            if value is None:
                # No attachment to an arbitrary store/repository. Admission is
                # exclusive before any provisioning; partial crash fails closed.
                project_id = str(uuid5(UUID(self.task_id), "factory-reviewed-toy-project"))
                value = {"schemaVersion": 1, "ownerId": self.owner_id, "taskId": self.task_id,
                    "scenario": self.scenario, "limits": self.limits, "projectId": project_id,
                    "upstreamRevision": REVISION, "upstreamSourceArchiveSha256": SOURCE_ARCHIVE_SHA256,
                    "phase": "ADMITTED"}
                try:
                    with self._manifest_path.open("xb") as stream:
                        stream.write(_canonical(value)); stream.flush(); os.fsync(stream.fileno())
                except FileExistsError:
                    value = self._load_manifest()
                    assert value is not None
                else:
                    if self.repo.exists() or (self.scope / "orx-store" / "orx.db").exists():
                        raise OpenResearchError("SCOPE_NOT_NEW", "Only a new exclusive task store and repository may be provisioned")
                    await self._command("experiment:inspect", "projects")  # Real CLI owns schema/migrations.
                    self.repo.mkdir()
                    for name in TOY_FILES:
                        (self.repo / name).write_bytes((Path(__file__).parent / "orx_toy" / name).read_bytes())
                    self._git("init", "-q", "-b", "main")
                    self.env.update(GIT_AUTHOR_NAME="Factory toy evaluator", GIT_AUTHOR_EMAIL="toy@example.invalid",
                        GIT_COMMITTER_NAME="Factory toy evaluator", GIT_COMMITTER_EMAIL="toy@example.invalid",
                        GIT_AUTHOR_DATE="2000-01-01T00:00:00Z", GIT_COMMITTER_DATE="2000-01-01T00:00:00Z")
                    self._git("add", "--", *TOY_FILES)
                    self._git("commit", "-q", "-m", "Reviewed original deterministic toy evaluator")
                    command = self._command_text()
                    value.update(sourceCommit=self._git("rev-parse", "HEAD").decode().strip(),
                        sourceArchiveSha256=hashlib.sha256(self._git("archive", "--format=tar", "HEAD")).hexdigest(),
                        command=command, commandSha256=hashlib.sha256(command.encode()).hexdigest(), fileSha256=TOY_FILES,
                        pythonSha256=_sha(self.python_binary), gitSha256=_sha(self.git_binary), phase="PROJECT_REGISTERED")
                    with self._db(writable=True) as db:
                        db.execute("BEGIN IMMEDIATE")
                        for table in ("local_projects", "local_experiments", "runs", "chat_sessions"):
                            if db.execute("select count(*) from " + table).fetchone()[0]:
                                raise OpenResearchError("SCOPE_NOT_NEW", "The native task store already contains records")
                        now = int(time.time() * 1000)
                        # Exact upstream create_project semantics, github sync
                        # explicitly false, no starter warm or agent discovery.
                        db.execute("INSERT INTO local_projects (id,name,slug,github_owner,github_repo,github_sync_enabled,baseline_branch,repo_path,run_command,paper_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            (project_id, "Factory reviewed toy comparison", "factory-toy-" + self.task_id, "", "", 0,
                             "main", str(self.repo), command, None, now, now))
                    self._save_manifest(value)
            if value.get("phase") == "PROJECT_REGISTERED":
                with self._db() as db:
                    experiments = list(db.execute("SELECT * FROM local_experiments"))
                if not experiments:
                    await self._command("experiment:run", "create-experiment", value["projectId"],
                        "--title", "Reviewed toy baseline and candidate", "--baseline", "--run-command", value["command"])
                    with self._db() as db:
                        experiments = list(db.execute("SELECT * FROM local_experiments"))
                if len(experiments) != 1 or experiments[0]["project_id"] != value["projectId"]:
                    raise OpenResearchError("SCOPE_INVALID", "A single authoritative task experiment is required")
                value.update(experimentId=experiments[0]["id"], branchName=experiments[0]["branch_name"], phase="READY")
                self._save_manifest(value)
            if value.get("phase") != "READY":
                raise OpenResearchError("PROVISION_UNKNOWN", "Interrupted provisioning requires operator inspection; no implicit restart")
            self.binding = ExperimentBinding(self.owner_id, self.task_id, value["projectId"], value["experimentId"],
                value["commandSha256"], value["sourceCommit"], "task-local-reviewed-toy")
            self._validate_owned_source()
            return self.provenance()

    def _validate_owned_source(self) -> dict[str, Any]:
        self._verify_source()
        value = self._load_manifest()
        if value is None or value.get("phase") != "READY":
            raise OpenResearchError("UNBOUND_EXPERIMENT", "A reviewed task-owned experiment is required")
        paths = self._git("ls-tree", "-r", "--name-only", value["sourceCommit"]).decode().splitlines()
        if (value["sourceCommit"] != RECIPE_SOURCE_COMMIT or value["sourceArchiveSha256"] != RECIPE_ARCHIVE_SHA256
                or sorted(paths) != sorted(TOY_FILES)
                or _sha(self.git_binary) != value["gitSha256"] or _sha(self.python_binary) != value["pythonSha256"]
                or self._command_text() != value["command"] or self._git("status", "--porcelain").strip()
                or self._git("rev-parse", value["branchName"]).decode().strip() != value["sourceCommit"]
                or hashlib.sha256(self._git("archive", "--format=tar", value["sourceCommit"])).hexdigest() != value["sourceArchiveSha256"]):
            raise OpenResearchError("SOURCE_CHANGED", "Source, reviewed command or toolchain drift was detected")
        for name, expected in TOY_FILES.items():
            if _sha(self.repo / name) != expected:
                raise OpenResearchError("SOURCE_CHANGED", "Task evaluator bytes changed")
        with self._db() as db:
            projects = list(db.execute("SELECT * FROM local_projects"))
            experiments = list(db.execute("SELECT * FROM local_experiments"))
            if (len(projects) != 1 or len(experiments) != 1 or projects[0]["id"] != value["projectId"]
                    or projects[0]["github_sync_enabled"] != 0 or projects[0]["github_owner"] or projects[0]["github_repo"]
                    or projects[0]["repo_path"] != str(self.repo) or experiments[0]["id"] != value["experimentId"]
                    or experiments[0]["run_command"] != value["command"]
                    or experiments[0]["project_id"] != value["projectId"]):
                raise OpenResearchError("COMMAND_CHANGED", "Native project/experiment authority drifted")
        return value

    def source_archive_bytes(self) -> bytes:
        value = self._validate_owned_source()
        paths = self._git("ls-tree", "-r", "--name-only", value["sourceCommit"]).decode().splitlines()
        if sorted(paths) != sorted(TOY_FILES):
            raise OpenResearchError("SOURCE_CHANGED", "Only the four original reviewed recipe files may be exported")
        raw = self._git("archive", "--format=tar", value["sourceCommit"])
        if hashlib.sha256(raw).hexdigest() != value["sourceArchiveSha256"]:
            raise OpenResearchError("SOURCE_CHANGED", "Recipe archive hash changed")
        return raw

    def provenance(self) -> dict[str, Any]:
        value = self._manifest or self._load_manifest()
        if value is None or value.get("phase") != "READY":
            raise OpenResearchError("UNBOUND_EXPERIMENT", "No task-owned reviewed evaluator is available")
        return {"evidenceKind": "actual_orx_local_toy_evaluation", "sourceRevision": REVISION,
            "upstreamSourceArchiveSha256": SOURCE_ARCHIVE_SHA256, "binarySha256": self.pin.sha256 if self.pin else None,
            "upstreamSourceCommit": REVISION, "upstreamArchiveSha256": SOURCE_ARCHIVE_SHA256,
            "recipeSourceCommit": value["sourceCommit"], "recipeArchiveSha256": value["sourceArchiveSha256"],
            "evaluatorSha256": value["fileSha256"]["evaluator.py"], "datasetSha256": value["fileSha256"]["dataset.json"],
            "taskId": self.task_id, "ownerSha256": hashlib.sha256(self.owner_id.encode()).hexdigest(),
            "projectId": value["projectId"], "experimentId": value["experimentId"], "sourceCommit": value["sourceCommit"],
            "sourceArchiveSha256": value["sourceArchiveSha256"], "commandSha256": value["commandSha256"],
            "fileSha256": value["fileSha256"], "scenario": self.scenario, "environment": self.limits,
            "zeroModelCalls": True, "githubSyncEnabled": False, "securitySandbox": False}

    def _native_run(self) -> dict[str, Any] | None:
        value = self._load_manifest() if self._trusted_reclaim else self._validate_owned_source()
        if value is None:
            raise OpenResearchError("UNBOUND_EXPERIMENT", "Task manifest is missing")
        with self._db() as db:
            rows = list(db.execute("SELECT * FROM runs ORDER BY created_at"))
        if len(rows) > 1:
            raise OpenResearchError("RUN_CHANGED", "An exclusive task may launch only once")
        if not rows:
            return None
        row = dict(rows[0]); descriptor = json.loads(row["backend_json"])
        if (row["experiment_id"] != value["experimentId"] or row["project_id"] != value["projectId"]
                or (not self._trusted_reclaim and (row["command"] != value["command"] or row["commit_sha"] != value["sourceCommit"]))
                or descriptor.get("kind") != "local_job"):
            raise OpenResearchError("RUN_CHANGED", "Native run identity/source does not match launch intent")
        # Starting row may precede handle; retain UNKNOWN until authoritative.
        if descriptor.get("jobId") is not None:
            expected = self.scope / "orx-store" / "local-runs" / row["id"]
            if Path(descriptor["jobId"]).resolve() != expected.resolve():
                raise OpenResearchError("RUN_CHANGED", "Native run handle escaped the exclusive task")
            if not self._trusted_reclaim:
                snapshot = Path(descriptor.get("sourcePath", ""))
                if (not snapshot.resolve().is_relative_to(self.scope) or descriptor.get("sourceDigest") != value["sourceArchiveSha256"]
                        or _sha(snapshot) != value["sourceArchiveSha256"]):
                    raise OpenResearchError("SOURCE_CHANGED", "Native snapshot hash differs from reviewed source")
        return row

    async def experiment_status(self) -> dict[str, Any]:
        if not self._trusted_reclaim:
            self._validate_owned_source()
        # Real status CLI is always executed. SQLite is read-only evidence for
        # full hashes/backend identity, never a fabricated run/status writer.
        result = await self._command("experiment:inspect", "exp", "status", self._bound().experiment_id)
        row = self._native_run()
        return {"status": row["status"] if row else "NOT_STARTED", "run_id": row["id"] if row else None,
                "raw": result.stdout, "stdout_sha256": result.stdout_sha256}

    async def launch_experiment(self) -> dict[str, Any]:
        if self.cleanup_only:
            raise OpenResearchError("CLEANUP_ONLY", "A cleanup handle cannot launch")
        return await super().launch_experiment()

    async def reconcile_experiment(self) -> dict[str, Any]:
        result = await super().reconcile_experiment()
        row = self._native_run()
        if row and result["run_id"] != row["id"]:
            raise OpenResearchError("RUN_CHANGED", "Native run differs from task receipt")
        if row:
            result.update(native_status=row["status"], commit_sha=row["commit_sha"],
                          source_archive_sha256=self.provenance()["sourceArchiveSha256"])
            if self._job:
                result["stop_evidence"] = self._job.evidence()
                deadline = time.monotonic() + 2
                while row["status"] in _TERMINAL and not result["stop_evidence"]["allStopped"] and time.monotonic() < deadline:
                    await asyncio.sleep(0.02)
                    result["stop_evidence"] = self._job.evidence()
            self._save_receipt(result)
        return result

    def evaluation_result(self) -> dict[str, Any] | None:
        row = self._native_run()
        if not row or row["status"] not in {"done", "failed"}:
            return None
        path = self.scope / "orx-store" / "local-runs" / row["id"] / "repo" / "result.json"
        if not path.is_file():
            return None
        if path.is_symlink() or path.stat().st_size > self.limits["outputBytes"]:
            raise OpenResearchError("INVALID_OUTPUT", "Evaluator result escaped output bounds")
        if any(_sha(path.parent / name) != expected for name, expected in TOY_FILES.items()):
            raise OpenResearchError("SOURCE_CHANGED", "Actual evaluator snapshot bytes changed")
        value = json.loads(path.read_text(encoding="utf-8"))
        if (value.get("schemaVersion") != 1 or value.get("taskId") != self.task_id
                or value.get("ownerSha256") != hashlib.sha256(self.owner_id.encode()).hexdigest()
                or value.get("scenario") != self.scenario or value.get("fileSha256") != TOY_FILES
                or value.get("sampleCount") != 7 or value.get("baseline") != {"value": 16.0}
                or value.get("candidate") != {"value": 0.0} or value.get("status") != row["status"]):
            raise OpenResearchError("INVALID_OUTPUT", "Evaluator identity, metrics or source hashes failed validation")
        return {**value, "resultSha256": _sha(path), "runId": row["id"],
                "provenance": {**self.provenance(), "resultSha256": _sha(path)}}

    async def reclaim_experiment(self) -> dict[str, Any]:
        # Trusted Factory task cleanup only. Immutable source/identity checks
        # remain; this never authorizes a new launch or releases results.
        self._trusted_reclaim = True
        try:
            if self.binding is None:
                value = self._load_manifest()
                if not value or value.get("phase") != "READY":
                    return {"state": "UNKNOWN", "run_id": None, "stop_evidence": self._job.evidence() if self._job else {"allStopped": False}}
                self.binding = ExperimentBinding(self.owner_id, self.task_id, value["projectId"], value["experimentId"],
                    value["commandSha256"], value["sourceCommit"], "task-local-reviewed-toy")
            await self.preflight()
            receipt = self._load_receipt()
            if receipt is None:
                return {"state": "NOT_STARTED", "run_id": None, "stop_evidence": self._job.evidence() if self._job else {"allStopped": False}}
            await self._command("experiment:cancel", "exp", "cancel", self._bound().experiment_id, allow_failure=True)
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                result = await self.reconcile_experiment()
                if result["state"] in _TERMINAL and result.get("stop_evidence", {}).get("allStopped"):
                    return result
                await asyncio.sleep(0.2)
            # Native cancel remains the authoritative intent/status writer;
            # held task job lets core reclaim an orphaned whole process tree.
            assert self._job is not None
            self._job.terminate()
            stopped = self._job.evidence()
            receipt = self._load_receipt()
            assert receipt is not None
            receipt.update(stop_evidence=stopped, state="UNKNOWN", cleanupNativeStatusPending=True)
            self._save_receipt(receipt)
            return receipt
        except OpenResearchError:
            # If current source/binary/schema prevents a safe native command,
            # the already validated held task job still permits scoped stop.
            # Keep the native status UNKNOWN; do not invent an ORX run update.
            if self._job is None:
                raise
            self._job.terminate()
            receipt = self._load_receipt()
            if receipt is None:
                raise
            receipt.update(stop_evidence=self._job.evidence(), state="UNKNOWN", cleanupNativeStatusPending=True)
            self._save_receipt(receipt)
            return receipt
        finally:
            self._trusted_reclaim = False

    async def cancel_experiment(self, *, timeout_seconds: int = 10) -> dict[str, Any]:
        await self._allow("experiment:cancel")
        return await self.reclaim_experiment()


class TaskLocalORXProvider:
    """Operator-owned handle; no path/command input is read from a user prompt."""
    def __init__(self, *, binary: Path, source_archive: Path, git_binary: Path, python_binary: Path):
        self.binary, self.source_archive = binary, source_archive
        self.git_binary, self.python_binary = git_binary, python_binary

    def create_experiment_adapter(self, *, owner_id: str, task_id: str, scope: Path, authorize: Any,
                                  pin: BinaryPin, max_output_bytes: int, command_timeout: float,
                                  environment: Any, scenario: str, cleanup_only: bool = False) -> TaskLocalORXAdapter:
        return TaskLocalORXAdapter(binary=self.binary, source_archive=self.source_archive,
            git_binary=self.git_binary, python_binary=self.python_binary, scope=scope, owner_id=owner_id, task_id=task_id,
            authorize=authorize, pin=pin, enabled=True, max_output_bytes=max_output_bytes,
            command_timeout=command_timeout, environment=environment, scenario=scenario, cleanup_only=cleanup_only)
