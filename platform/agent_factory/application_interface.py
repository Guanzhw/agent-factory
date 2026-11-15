"""Direct application input; Agno owns execution and continuation."""
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

ApplicationRequestId = Annotated[str, Field(min_length=1)]


class ApplicationStart(BaseModel):
    model_config = ConfigDict(extra='forbid')
    interfaceVersion: object | None = Field(default=None, exclude=True)
    requestId: ApplicationRequestId
    mode: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    inputValues: dict | None = None
    connectionRefs: dict = Field(default_factory=dict)
    instructions: list[str] | None = None
