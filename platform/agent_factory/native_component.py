"""Immutable native component coordinates; no execution or progress state."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .auth import EXECUTOR_ID


class NativeWorkflowPin(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    kind: Literal['workflow'] = 'workflow'
    id: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,100}$')
    revision: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,100}$')
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


def component_identity(plan):
    pin = plan.get('nativeComponent')
    if pin is None:
        return 'agent', EXECUTOR_ID
    checked = NativeWorkflowPin.model_validate(pin)
    return checked.kind, checked.id
