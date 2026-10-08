"""Explicit delegated cgroup protocol; caller supplies locked durable custody.

The caller commits each supplied ticket synchronously and retains UNKNOWN
custody. No operation adopts a directory or retries an uncertain kernel effect.
Tests against fake ports do not certify host enforcement or hostile-code isolation.
"""
from copy import deepcopy
import inspect as inspect_module
import uuid
from typing import Any

try:
    from .delegated_cgroup_fs import DelegatedCgroupConfig, DelegatedCgroupError, LinuxDelegatedCgroupFS, digest, require
except ImportError:  # Standalone isolated guardian.
    from delegated_cgroup_fs import DelegatedCgroupConfig, DelegatedCgroupError, LinuxDelegatedCgroupFS, digest, require  # pyright: ignore[reportMissingImports]

BACKEND = "delegated-cgroup-v2"


def _sync(callback, *args):
    value = callback(*args)
    if inspect_module.isawaitable(value):
        if inspect_module.iscoroutine(value):
            value.close()
        raise DelegatedCgroupError("DELEGATED_CGROUP_ASYNC_CALLBACK")
    require(value is None)


class DelegatedCgroupBackend:
    def __init__(self, config, fs=None):
        require(type(config) is DelegatedCgroupConfig)
        self.config = config
        self.fs = fs if fs is not None else LinuxDelegatedCgroupFS(config)

    def validate(self):
        self.fs.validate()
        self._root()

    def _root(self):
        expected = {"device": self.config.root_device, "inode": self.config.root_inode, "bootId": self.config.boot_id}
        require(self.fs.root_identity() == expected)
        return expected

    def new_ticket(self, binding):
        require(type(binding) is dict and bool(binding))
        identity = uuid.uuid4().hex
        return {"schema": 1, "backend": BACKEND, "id": identity, "name": "af-" + identity,
                "bindingSha256": digest(binding), "configSha256": self.config.fingerprint,
                "rootPin": {"device": self.config.root_device, "inode": self.config.root_inode, "bootId": self.config.boot_id},
                "pin": None, "state": "NEW", "attachIdentity": None,
                "createAttempted": False, "attachAttempted": False, "killAttempted": False,
                "releaseAttempted": False, "limitsVerified": False, "attached": False}

    def _ticket(self, ticket: dict[str, Any]):
        require(type(ticket) is dict and ticket.get("schema") == 1 and ticket.get("backend") == BACKEND)
        require(ticket.get("configSha256") == self.config.fingerprint and ticket.get("rootPin") == self._root())
        require(type(ticket.get("id")) is str and len(ticket["id"]) == 32
                and all(c in "0123456789abcdef" for c in ticket["id"]))
        require(ticket.get("name") == "af-" + ticket["id"])
        if ticket.get("pin") is not None:
            require(ticket["pin"]["name"] == ticket["name"] and ticket["pin"]["configSha256"] == self.config.fingerprint)
        return deepcopy(ticket)

    def _commit(self, ticket, persist, state):
        ticket["state"] = state
        _sync(persist, deepcopy(ticket))

    def _failed(self, ticket, persist):
        self._commit(ticket, persist, "UNKNOWN")

    def prepare(self, ticket, *, persist, before_effect):
        item = self._ticket(ticket)
        require(item["state"] == "NEW" and not item["createAttempted"])
        self.validate()
        _sync(before_effect)
        item["createAttempted"] = True
        self._commit(item, persist, "CREATE_INTENT")
        try:
            _sync(before_effect)
            item["pin"] = self.fs.create(item["name"])
            self._commit(item, persist, "CONFIGURE_INTENT")
            for name, value in self.config.controls().items():
                _sync(before_effect)
                self.fs.write(item["pin"], name, value)
            require(self.inspect(item)["limitsReadbackVerified"])
            item["limitsVerified"] = True
            self._commit(item, persist, "READY")
            return item
        except Exception:
            self._failed(item, persist)
            raise DelegatedCgroupError("DELEGATED_CGROUP_PREPARE_UNKNOWN") from None

    def attach_before_exec(self, ticket, pid_birth, *, persist, before_effect):
        item = self._ticket(ticket)
        require(item["state"] == "READY" and not item["attachAttempted"])
        self.validate()
        require(self.inspect(item)["limitsReadbackVerified"])
        require(type(pid_birth) is dict and pid_birth.get("bootId") == self.config.boot_id)
        _sync(before_effect)
        item["attachIdentity"] = deepcopy(pid_birth)
        item["attachAttempted"] = True
        self._commit(item, persist, "ATTACH_INTENT")
        try:
            _sync(before_effect)
            self.fs.attach(item["pin"], pid_birth)
            item["attached"] = True
            self._commit(item, persist, "ATTACHED")
            return item
        except Exception:
            self._failed(item, persist)
            raise DelegatedCgroupError("DELEGATED_CGROUP_ATTACH_UNKNOWN") from None

    def inspect(self, ticket):
        result = {"backend": BACKEND, "state": "UNKNOWN", "populated": None,
                  "limitsReadbackVerified": False, "releasedProof": False, "capacityHeld": True, "attached": False}
        try:
            item = self._ticket(ticket)
            if item["state"] == "RELEASED":
                require(item["releaseAttempted"] and item["pin"] is not None and self.fs.absent(item["pin"]))
                return dict(result, state="RELEASED", populated=False, releasedProof=True, capacityHeld=False,
                            limitsReadbackVerified=False, attached=item["attached"])
            require(item["pin"] is not None)
            require(self.fs.read(item["pin"], "cgroup.type") == "domain")
            lines = self.fs.read(item["pin"], "cgroup.events").splitlines()
            events = dict(line.split() for line in lines)
            require(events.get("populated") in {"0", "1"})
            populated = events["populated"] == "1"
            try:
                verified = all(self.fs.read(item["pin"], key).split() == value.split()
                               for key, value in self.config.controls().items())
            except Exception:
                verified = False
            return dict(result, state=item["state"] if populated else "EMPTY", populated=populated,
                        limitsReadbackVerified=verified, attached=item["attached"])
        except Exception:
            return result

    def kill(self, ticket, *, persist, before_effect):
        item = self._ticket(ticket)
        require(item["pin"] is not None and not item["releaseAttempted"])
        proof = self.inspect(item)
        require(proof["populated"] is not None)
        if proof["populated"] is False:
            self._commit(item, persist, "EMPTY")
            return item
        require(not item["killAttempted"])
        _sync(before_effect)
        item["killAttempted"] = True
        self._commit(item, persist, "KILL_INTENT")
        try:
            _sync(before_effect)
            self.fs.write(item["pin"], "cgroup.kill", "1")
            state = "EMPTY" if self.inspect(item)["populated"] is False else "UNKNOWN"
            self._commit(item, persist, state)
            return item
        except Exception:
            self._failed(item, persist)
            raise DelegatedCgroupError("DELEGATED_CGROUP_KILL_UNKNOWN") from None

    def release(self, ticket, *, persist, before_effect):
        item = self._ticket(ticket)
        require(not item["releaseAttempted"] and self.inspect(item)["populated"] is False)
        _sync(before_effect)
        item["releaseAttempted"] = True
        self._commit(item, persist, "REMOVE_INTENT")
        try:
            _sync(before_effect)
            self.fs.remove(item["pin"])
            self._commit(item, persist, "RELEASED")
            return item
        except Exception:
            self._failed(item, persist)
            raise DelegatedCgroupError("DELEGATED_CGROUP_RELEASE_UNKNOWN") from None
