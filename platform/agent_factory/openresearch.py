"""Bounded OpenResearch CLI tools; AgentOS remains the agent/session owner.

This adapter is disabled by default. BinaryPin is an operator-approved build
attestation, not a claim that a matching --version proves a source revision.
No model, remote compute, provisioning, login, or arbitrary command interface.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import re
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

REVISION = "f336b121525d99364e2dee4fe90b2784894a54e6"
VERSION = "0.2.13"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LAST = re.compile(r"^  last run: ([A-Za-z0-9][A-Za-z0-9_.:-]{0,199}) "
                   r"\((starting|running|done|failed|cancelled), commit [^,\n]+, ran [^\n]+\)$", re.M)
_TERMINAL = frozenset({"done", "failed", "cancelled"})


class OpenResearchError(RuntimeError):
    def __init__(self, code: str, message: str, result: CommandResult | None = None):
        super().__init__(message)
        self.code = code
        self.result = result  # Scoped evidence only; never automatically feed errors to a model.


@dataclass(frozen=True)
class BinaryPin:
    revision: str
    version: str
    sha256: str


@dataclass(frozen=True)
class ExperimentBinding:
    """Trusted operator-provisioned reference, never constructed from model text.

    Store/config/cache and the provisioned project must be inside this task's
    scope. source_commit is reviewed provenance, not inferred from CLI version.
    Each experiment belongs exclusively to this owner/task; no shared launchers.
    """
    owner_id: str
    task_id: str
    project_id: str
    experiment_id: str
    approved_command_sha256: str
    source_commit: str
    connection_ref: str


@dataclass(frozen=True)
class CommandResult:
    argv: tuple[str, ...]
    stdout: str
    stderr: str
    returncode: int
    elapsed_seconds: float
    stdout_sha256: str


class OpenResearchAdapter:
    def __init__(self, *, binary: Path, scope: Path, owner_id: str, task_id: str,
                 authorize: Callable[[str], Any], pin: BinaryPin | None = None,
                 enabled: bool = False, binding: ExperimentBinding | None = None,
                 search_path: str | None = None, max_output_bytes: int = 1_048_576,
                 command_timeout: float = 30, max_concurrency: int = 1, create_scope: bool = True):
        if not owner_id or str(UUID(task_id)) != task_id:
            raise ValueError("An owned canonical task UUID is required")
        if not scope.is_absolute() or not binary.is_absolute():
            raise ValueError("Scope and executable must be trusted absolute paths")
        if not 1024 <= max_output_bytes <= 8_388_608 or not 0 < command_timeout <= 300:
            raise ValueError("Invalid subprocess bounds")
        if not 1 <= max_concurrency <= 4:
            raise ValueError("Invalid subprocess concurrency")
        self.binary, self.scope = binary.resolve(), scope.resolve()
        self.owner_id, self.task_id = owner_id, task_id
        self.authorize, self.pin, self.enabled = authorize, pin, enabled
        self.binding = binding
        self._version_proof: BinaryPin | None = None
        self.max_output_bytes, self.command_timeout = max_output_bytes, command_timeout
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._experiment_lock = asyncio.Lock()
        self._processes: set[asyncio.subprocess.Process] = set()
        if create_scope:
            self.scope.mkdir(parents=True, exist_ok=True)
        elif not self.scope.is_dir():
            raise ValueError("Cleanup requires an existing task scope")
        self.env: dict[str, str] = {}
        # Deliberately do not inherit provider tokens, proxy credentials, SSH
        # agents, agent session variables, or user credential/config directories.
        for name in ("SystemRoot", "WINDIR", "PATHEXT", "LANG", "LC_ALL"):
            if name in os.environ:
                self.env[name] = os.environ[name]
        default_path = str(Path(os.environ["SystemRoot"]) / "System32") if os.name == "nt" else os.defpath
        trusted_path = search_path if search_path is not None else default_path
        if any(not Path(part).is_absolute() for part in trusted_path.split(os.pathsep)):
            raise ValueError("Search path must contain only trusted absolute directories")
        self.env["PATH"] = trusted_path
        directories = {"HOME": "home", "USERPROFILE": "home", "APPDATA": "config",
                       "LOCALAPPDATA": "cache", "XDG_CONFIG_HOME": "config",
                       "XDG_DATA_HOME": "data", "XDG_CACHE_HOME": "cache",
                       "ORX_DATA_DIR": "orx-store", "ORX_CACHE_DIR": "cache",
                       "TMP": "tmp", "TEMP": "tmp", "TMPDIR": "tmp"}
        for name, relative in directories.items():
            path = (self.scope / relative).resolve()
            if not path.is_relative_to(self.scope):
                raise ValueError("Task directory escapes scope")
            if create_scope:
                path.mkdir(parents=True, exist_ok=True)
            elif not path.is_dir() or path.is_symlink():
                raise ValueError("Cleanup requires existing unlinked task directories")
            self.env[name] = str(path)
        self.env.update(ORX_NO_UPDATE_CHECK="1", NO_UPDATE_NOTIFIER="1", GIT_TERMINAL_PROMPT="0")
        self._receipt_path = self.scope / "factory-orx-receipt.json"

    async def _allow(self, operation: str) -> None:
        result = self.authorize(operation)
        if inspect.isawaitable(result):
            result = await result
        if result is False:
            raise OpenResearchError("FORBIDDEN", "Current task permission was revoked")

    def _verify_hash(self) -> None:
        if not self.enabled:
            raise OpenResearchError("DISABLED", "OpenResearch is not enabled")
        if (self.pin is None or self.pin.revision != REVISION or self.pin.version != VERSION
                or not _SHA.fullmatch(self.pin.sha256)):
            raise OpenResearchError("UNVERIFIED_BINARY", "Exact revision/build provenance is required")
        if not self.binary.is_file():
            raise OpenResearchError("UNVERIFIED_BINARY", "Approved binary is missing")
        with self.binary.open("rb") as binary:
            digest = hashlib.file_digest(binary, "sha256").hexdigest()
        if digest != self.pin.sha256:
            raise OpenResearchError("UNVERIFIED_BINARY", "Binary hash differs from approved build")

    async def preflight(self) -> dict[str, str]:
        await self._allow("preflight")
        self._verify_hash()
        # Reuse only the version fact for the same approved binary bytes.
        # Authority and the complete on-disk hash are verified on every call;
        # no permission, source-integrity or process-liveness proof is cached.
        proof_pin = self.pin
        if self._version_proof != proof_pin:
            result = await self._execute(("--no-telemetry", "--version"))
            if self.pin != proof_pin:
                raise OpenResearchError("UNVERIFIED_BINARY", "Binary pin changed during version verification")
            if result.stdout.strip() != f"orx {VERSION}":
                raise OpenResearchError("VERSION_MISMATCH", "CLI version differs from pinned source")
            self._version_proof = proof_pin
        assert self.pin is not None
        return {"revision": REVISION, "version": VERSION, "binary_sha256": self.pin.sha256}

    async def _spawn(self, argv: tuple[str, ...]) -> asyncio.subprocess.Process:
        kwargs: dict[str, Any] = {"cwd": str(self.scope), "env": self.env,
                                  "stdin": asyncio.subprocess.DEVNULL,
                                  "stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.PIPE}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        return await asyncio.create_subprocess_exec(str(self.binary), *argv, **kwargs)

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name == "nt":
            system = Path(os.environ["SystemRoot"]) / "System32" / "taskkill.exe"
            killer = await asyncio.create_subprocess_exec(str(system), "/PID", str(process.pid), "/T", "/F",
                                                          stdout=asyncio.subprocess.DEVNULL,
                                                          stderr=asyncio.subprocess.DEVNULL,
                                                          creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                await asyncio.wait_for(killer.wait(), 5)
            except TimeoutError:
                killer.kill()
                await killer.wait()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()

    async def _execute(self, argv: tuple[str, ...], *, timeout: float | None = None,
                       allow_failure: bool = False, operation: str = "preflight") -> CommandResult:
        self._verify_hash()
        async with self._semaphore:
            self._verify_hash()
            await self._allow(operation)
            started = time.monotonic()
            process = await self._spawn(argv)
            self._processes.add(process)
            count = 0

            async def read(stream: asyncio.StreamReader | None) -> bytes:
                nonlocal count
                assert stream is not None
                chunks = []
                while chunk := await stream.read(8192):
                    count += len(chunk)
                    if count > self.max_output_bytes:
                        raise OpenResearchError("OUTPUT_LIMIT", "CLI output exceeded task bound")
                    chunks.append(chunk)
                return b"".join(chunks)

            readers = [asyncio.create_task(read(process.stdout)), asyncio.create_task(read(process.stderr))]
            try:
                stdout, stderr = await asyncio.wait_for(asyncio.gather(*readers), timeout or self.command_timeout)
                returncode = await asyncio.wait_for(process.wait(), 5)
                result = CommandResult(argv, stdout.decode("utf-8", errors="replace"),
                                       stderr.decode("utf-8", errors="replace"), returncode,
                                       time.monotonic() - started, hashlib.sha256(stdout).hexdigest())
                if returncode and not allow_failure:
                    raise OpenResearchError("COMMAND_FAILED", f"ORX command exited {returncode}; inspect scoped output", result)
                return result
            except TimeoutError as error:
                raise OpenResearchError("TIMEOUT", "CLI command exceeded task time bound") from error
            finally:
                await self._terminate(process)
                for reader in readers:
                    if not reader.done():
                        reader.cancel()
                await asyncio.gather(*readers, return_exceptions=True)
                self._processes.discard(process)

    async def _command(self, operation: str, *argv: str, **kwargs: Any) -> CommandResult:
        await self.preflight()
        await self._allow(operation)
        return await self._execute(("--no-telemetry", *argv), operation=operation, **kwargs)

    @staticmethod
    def _id(value: str) -> str:
        if not isinstance(value, str) or not _ID.fullmatch(value):
            raise ValueError("Invalid ORX reference")
        return value

    def _bound(self) -> ExperimentBinding:
        binding = self.binding
        if binding is None or (binding.owner_id, binding.task_id) != (self.owner_id, self.task_id):
            raise OpenResearchError("UNBOUND_EXPERIMENT", "A task-owned operator binding is required")
        for value in (binding.project_id, binding.experiment_id, binding.connection_ref):
            self._id(value)
        if not _SHA.fullmatch(binding.approved_command_sha256) or not re.fullmatch(r"[0-9a-f]{40}", binding.source_commit):
            raise OpenResearchError("UNBOUND_EXPERIMENT", "Reviewed command and source provenance are required")
        return binding

    async def discover(self, query: str, *, corpus: str = "keyword", limit: int = 15) -> list[dict[str, Any]]:
        if corpus not in {"keyword", "openalex", "biorxiv", "pubmed"}:
            raise ValueError("Unsupported corpus")
        if not isinstance(query, str) or not query.strip() or len(query) > 4000 or "\x00" in query or query.startswith("-"):
            raise ValueError("Invalid retrieval query")
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("Retrieval limit must be 1..200")
        result = await self._command("discover", "discover", corpus, query, "--limit", str(limit))
        try:
            hits = json.loads(result.stdout)
        except ValueError as error:
            raise OpenResearchError("INVALID_OUTPUT", "Discovery did not emit JSON") from error
        if not isinstance(hits, list) or len(hits) > limit or any(not isinstance(hit, dict) for hit in hits):
            raise OpenResearchError("INVALID_OUTPUT", "Unexpected discovery result shape")
        return hits  # Preserve upstream citation identity; never invent success/citations.

    async def paper(self, paper_id: str, *, full: bool = False) -> CommandResult:
        # Accept canonical source identifiers, not arbitrary URLs/path selectors.
        identifier = (r"(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+/\d{7}(?:v\d+)?|"
                      r"W\d{1,30}|(?:pmid:)?\d{1,20}|10\.\d{4,9}/[A-Za-z0-9._;()/:-]{1,300})")
        if not isinstance(paper_id, str) or not re.fullmatch(identifier, paper_id) or ".." in paper_id.split("/"):
            raise ValueError("Invalid paper reference")
        if full and not re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", paper_id):
            raise ValueError("Full extracted text requires an alphaXiv/arXiv reference")
        extra = ("--source", "alphaxiv", "--full") if full else ()
        return await self._command("paper", "paper", paper_id, *extra)

    async def experiment_status(self) -> dict[str, Any]:
        binding = self._bound()
        result = await self._command("experiment:inspect", "exp", "status", binding.experiment_id)
        text = result.stdout.replace("\r\n", "\n")
        ids = re.findall(r"^  id: +([^\n\r]+)$", text, re.M)
        commands = re.findall(r"^  command: +([^\n\r]+)$", text, re.M)
        if ids != [binding.experiment_id] or len(commands) != 1:
            raise OpenResearchError("INVALID_OUTPUT", "Pinned status fields are missing or ambiguous")
        if hashlib.sha256(commands[0].encode()).hexdigest() != binding.approved_command_sha256:
            raise OpenResearchError("COMMAND_CHANGED", "Experiment command differs from reviewed binding")
        latest = list(_LAST.finditer(text))
        status: dict[str, Any] = {"status": "UNKNOWN", "run_id": None, "raw": result.stdout,
                                  "stdout_sha256": result.stdout_sha256}
        if len(latest) == 1:
            status.update(run_id=latest[0].group(1), status=latest[0].group(2))
        elif len(latest) > 1:
            raise OpenResearchError("INVALID_OUTPUT", "Ambiguous latest run")
        elif re.findall(r"^  last run: \u2014 \(never run\)$", text, re.M) == ["  last run: \u2014 (never run)"]:
            status["status"] = "NOT_STARTED"
        return status

    def _load_receipt(self) -> dict[str, Any] | None:
        if not self._receipt_path.exists():
            return None
        if self._receipt_path.is_symlink() or self._receipt_path.stat().st_size > 16384:
            raise OpenResearchError("INVALID_RECEIPT", "Invalid task receipt")
        value = json.loads(self._receipt_path.read_text(encoding="utf-8"))
        binding = self._bound()
        if not isinstance(value, dict) or (value.get("owner_id"), value.get("task_id"), value.get("experiment_id"),
                                         value.get("command_sha256"), value.get("source_commit"), value.get("connection_ref")) != (
                self.owner_id, self.task_id, binding.experiment_id, binding.approved_command_sha256,
                binding.source_commit, binding.connection_ref):
            raise OpenResearchError("INVALID_RECEIPT", "Receipt belongs to another task")
        return value

    def _save_receipt(self, value: dict[str, Any]) -> None:
        temporary = self.scope / "factory-orx-receipt.tmp"
        if temporary.is_symlink() or self._receipt_path.is_symlink():
            raise OpenResearchError("INVALID_RECEIPT", "Receipt path must remain task-owned")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self._receipt_path)

    async def launch_experiment(self) -> dict[str, Any]:
        """One launch intent per task. UNKNOWN is never automatically resubmitted."""
        async with self._experiment_lock:
            binding = self._bound()
            existing = self._load_receipt()
            if existing is not None:
                return await self.reconcile_experiment()
            before = await self.experiment_status()
            if before["status"] in {"starting", "running"}:
                raise OpenResearchError("ALREADY_RUNNING", "Bound experiment already has an active run")
            if before["status"] == "UNKNOWN":
                raise OpenResearchError("UNKNOWN_RUN", "Current experiment run could not be determined")
            await self._allow("experiment:run")
            receipt = {"owner_id": self.owner_id, "task_id": self.task_id,
                       "project_id": binding.project_id, "experiment_id": binding.experiment_id,
                       "connection_ref": binding.connection_ref, "source_commit": binding.source_commit,
                       "command_sha256": binding.approved_command_sha256, "revision": REVISION,
                       "binary_sha256": self.pin.sha256 if self.pin else None,
                       "previous_run_id": before["run_id"], "run_id": None, "state": "UNKNOWN"}
            # Atomic exclusive intent admission also covers two adapter instances
            # sharing a task directory. A partial crash receipt fails closed.
            try:
                with self._receipt_path.open("x", encoding="utf-8") as stream:
                    json.dump(receipt, stream, sort_keys=True)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                return await self.reconcile_experiment()
            # Persist before the side effect; interruption/failed acknowledgement
            # leaves UNKNOWN. Only supervisor status may establish a new run.
            await self._command("experiment:run", "exp", "run", binding.experiment_id, "--backend", "local")
            return await self.reconcile_experiment()

    async def reconcile_experiment(self) -> dict[str, Any]:
        receipt = self._load_receipt()
        if receipt is None:
            raise OpenResearchError("NO_LAUNCH_INTENT", "No persisted task launch intent")
        status = await self.experiment_status()
        run_id = status["run_id"]
        if run_id is not None and run_id != receipt["previous_run_id"]:
            if receipt["run_id"] is not None and receipt["run_id"] != run_id:
                raise OpenResearchError("RUN_CHANGED", "Unexpected external launch; reconcile manually")
            receipt.update(run_id=run_id, state=status["status"])
        else:
            receipt["state"] = "UNKNOWN"
        self._save_receipt(receipt)
        return receipt

    async def wait_experiment(self, *, timeout_seconds: int = 30, interval_seconds: int = 1) -> dict[str, Any]:
        binding = self._bound()
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
            raise ValueError("Wait timeout must be 1..300 seconds")
        if type(interval_seconds) is not int or not 1 <= interval_seconds <= timeout_seconds:
            raise ValueError("Invalid poll interval")
        if self._load_receipt() is None:
            raise OpenResearchError("NO_LAUNCH_INTENT", "No task run to await")
        # Native wait polls its local store; exit 0 includes failed/cancelled.
        await self._command("experiment:inspect", "exp", "wait", binding.experiment_id,
                            "--timeout", str(timeout_seconds), "--interval", str(interval_seconds),
                            timeout=timeout_seconds + 5, allow_failure=True)
        return await self.reconcile_experiment()

    async def cancel_experiment(self, *, timeout_seconds: int = 10) -> dict[str, Any]:
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
            raise ValueError("Cancel timeout must be 1..300 seconds")
        binding = self._bound()
        # Reclaim has its own current authorization decision, supplied by core.
        await self._allow("experiment:cancel")
        for process in tuple(self._processes):
            await self._terminate(process)
        receipt = self._load_receipt()
        if receipt is None:
            raise OpenResearchError("NO_LAUNCH_INTENT", "No task experiment to cancel")
        receipt["cancel_requested"] = True
        self._save_receipt(receipt)
        await self._command("experiment:cancel", "exp", "cancel", binding.experiment_id, allow_failure=True)
        # Detached supervisor/experiment is outside the launcher group; native
        # cancel intent plus observed status is required for terminal evidence.
        return await self.wait_experiment(timeout_seconds=timeout_seconds)

    async def run_logs(self) -> CommandResult:
        receipt = await self.reconcile_experiment()
        if not receipt["run_id"]:
            raise OpenResearchError("UNKNOWN_RUN", "No authoritative run reference")
        return await self._command("experiment:inspect", "logs", self._id(receipt["run_id"]))
