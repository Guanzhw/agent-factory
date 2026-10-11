"""Application interface v1: data and scoped ports, never an execution engine.

The interface version is independent of application definition contracts v1/v2.
Agno and the selected external executor still own execution and continuation.
"""
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt

INTERFACE_VERSION = 1


class ApplicationStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    interfaceVersion: StrictInt = Field(default=1, ge=1, le=1)
    requestId: str = Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_.:-]+$')
    application: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')
    mode: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')
    goal: str = Field(min_length=2, max_length=2000)
    applicationRef: dict | None = None
    inputValues: dict | None = None
    materialChoices: dict = Field(default_factory=dict, max_length=30)
    connectionRefs: dict = Field(default_factory=dict, max_length=30)


@dataclass(frozen=True)
class ApplicationIdentity:
    owner_id: str
    task_id: str
    run_id: str
    application_id: str
    application_version: int


class ApplicationExecutionContext(Protocol):
    """Injected into a trusted native function as ``application_context``.

    Resource values are inert references, never credentials or runtime handles.
    Returned mappings are independent snapshots. Every write rechecks current
    authority for this exact original native run. This is a dependency boundary
    for reviewed Python code, not a sandbox for untrusted application code.
    """
    @property
    def identity(self) -> ApplicationIdentity: ...
    @property
    def inputs(self) -> Mapping[str, Any]: ...
    @property
    def resources(self) -> Mapping[str, Any]: ...
    def emit_event(self, name: str, message: str, data: Mapping[str, Any] | None = None) -> None: ...
    def write_artifact(self, name: str, content: str | bytes, media_type: str = 'application/json') -> dict[str, Any]: ...


class ApplicationLifecycle(Protocol):
    """Small owner-scoped client port; implementations must never auto-retry writes.

    start/cancel acknowledge original intent, not completion/verified stop.
    request reads the original request after a lost acknowledgement. Events
    retain their opaque replay cursor; artifacts retain integrity metadata.
    Pause/continue are optional executor-specific extensions and are deliberately
    absent from this required port. No shared recovery semantics are promised.
    """
    async def inputs(self, application_id: str) -> dict[str, Any]: ...
    async def resources(self) -> dict[str, Any]: ...
    async def start(self, request: Mapping[str, Any]) -> dict[str, Any]: ...
    async def request(self, request_id: str) -> dict[str, Any]: ...
    async def query(self, task_id: str) -> dict[str, Any]: ...
    async def cancel(self, task_id: str, command_id: str) -> dict[str, Any]: ...
    async def events(self, task_id: str, cursor: str | None = None) -> dict[str, Any]: ...
    async def artifacts(self, task_id: str) -> list[dict[str, Any]]: ...
    async def artifact(self, task_id: str, artifact_id: str) -> bytes: ...
