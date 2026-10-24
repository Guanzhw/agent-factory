"""Trusted settings for the installed research application; never loaded from HTTP."""
from dataclasses import dataclass, field
from typing import Callable
import os
from agent_factory.config import Settings


@dataclass
class ResearchSettings(Settings):
    source_synthesis_enabled: bool = False
    research_evaluators: dict = field(default_factory=dict)
    autoresearch_presets: dict = field(default_factory=dict)
    personal_agent_commands_enabled: bool = False
    managed_orx_profiles_factory: Callable | None = field(default=None, repr=False)
    autoresearch_children_factory: Callable | None = field(default=None, repr=False)
    remote_scientific_factory: Callable | None = field(default=None, repr=False)
    platform_openresearch: object | None = field(default=None, repr=False)
    ssh_openresearch: object | None = field(default=None, repr=False)

    def __post_init__(self):
        if type(self.personal_agent_commands_enabled) is not bool:
            raise ValueError('Personal command enablement must be an explicit boolean')
        if self.personal_agent_commands_enabled:
            from .personal_command_profile import registrations, pricing
            entries = registrations()
            if any(a.adapter_id in {e.adapter_id for e in entries} for a in self.runtime_adapters):
                raise ValueError('Personal command adapters cannot be replaced')
            self.runtime_adapters = [*self.runtime_adapters, *entries]
            self.usage_pricing = (*self.usage_pricing, pricing())
        if type(self.source_synthesis_enabled) is not bool or (self.source_synthesis_enabled and not self.demo):
            raise ValueError("The source synthesis fixture requires demo mode")
        super().__post_init__()

    @classmethod
    def from_env(cls):
        # The deployment preserves the existing operator variable. The core
        # environment reader does not know any installed application.
        settings = super().from_env()
        settings.source_synthesis_enabled = os.getenv("FACTORY_SOURCE_SYNTHESIS_ENABLED", "false") == "true"
        if settings.source_synthesis_enabled and not settings.demo:
            raise ValueError("The source synthesis fixture requires demo mode")
        return settings
