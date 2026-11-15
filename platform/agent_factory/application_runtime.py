"""Trusted application callbacks resolved from each run's saved execution inputs."""
from dataclasses import dataclass, field
import json
from typing import Callable, Protocol

from agno.agent import Agent
from agno.exceptions import InputCheckError
from agno.models.base import Model
from agno.models.message import Message
from agno.run import RunContext
from agno.session.agent import AgentSession
from agno.tools.function import Function


@dataclass
class ApplicationTools:
    functions: list[Function] = field(default_factory=list)
    include_personal: bool = True


@dataclass
class ApplicationRuntime:
    instructions: Callable[[RunContext, dict], list[str]] | None = None
    tools: Callable[[RunContext, dict, Agent], ApplicationTools] | None = None
    prepare_history: Callable[[RunContext, dict, AgentSession, Agent], None] | None = None
    before_model: 'BeforeModel | None' = None
    effect_prefixes: tuple[str, ...] = ()
    on_retry_blocked: Callable[[dict], None] | None = None


class BeforeModel(Protocol):
    def __call__(self, context: RunContext, execution: dict, messages: list[Message] | None,
                 auxiliary: Callable[[], Model], /, *, auxiliary_request: bool = False) -> None: ...


def execution_instructions(execution, inputs):
    text = execution.get('instructions', [])
    if isinstance(text, str):
        text = [text]
    return [*text, json.dumps({'goal': execution['normalizedGoal'], **inputs}, ensure_ascii=False)]


def resolve_application_runtime(runtimes, execution):
    application = execution.get('application')
    # Explicit plain snapshots stay plain if an application later installs hooks.
    # Historical research jobs already depended on its QA tools and context policy.
    if not execution.get('applicationRuntime', application == 'research-chat'):
        return None
    runtime = runtimes.get(application)
    if runtime is None:
        raise InputCheckError(f'APPLICATION_RUNTIME_UNAVAILABLE: {application}')
    return runtime
