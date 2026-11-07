"""Application interface v1: data and scoped ports, never an execution engine.

The interface version is independent of application definition contracts v1/v2.
Agno and the selected external executor still own execution and continuation.
"""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictInt

INTERFACE_VERSION = 1
ApplicationRequestId = Annotated[str, Field(min_length=8, max_length=80, pattern=r'^[A-Za-z0-9_.:-]+$')]


class ApplicationStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    interfaceVersion: StrictInt = Field(default=1, ge=1, le=1)
    requestId: ApplicationRequestId
    mode: str = Field(min_length=1, max_length=100, pattern=r'^[A-Za-z0-9_.:-]+$')
    goal: str = Field(min_length=1)
    inputValues: dict | None = None
    connectionRefs: dict = Field(default_factory=dict)
    instructions: list[str] | None = None
