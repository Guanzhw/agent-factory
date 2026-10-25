"""The research application's service graph, owned and closed by its assembly.

Each assembly owns this graph and explicitly passes it to its constructors
and trusted adapter factories. No process-global Store lookup or service locator
is involved. Rebinding a registration never captures a previous server graph.
"""
from dataclasses import dataclass, replace
from typing import Any, Callable


@dataclass
class ResearchServices:
    factory_store: Any = None
    installed: bool = False
    closed: bool = False
    synthesis_sources: Any = None
    comparisons: Any = None
    autoresearch: Any = None
    autoresearch_session_control: Any = None
    autoresearch_children: Any = None
    research_runtime: Any = None
    research_evaluation: Any = None
    remote_scientific: Any = None
    remote_scientific_receiver: Any = None
    workspace: Any = None


    def bind_store(self, store):
        if self.closed or self.factory_store is not None and self.factory_store is not store:
            raise ValueError('RESEARCH_STORE_MISMATCH')
        self.factory_store = store
        return self

    def require_store(self, store, *, ready=False):
        if self.closed or self.factory_store is not store:
            raise ValueError('RESEARCH_STORE_MISMATCH')
        if ready and not self.installed:
            raise ValueError('RESEARCH_SERVICES_NOT_READY')
        return self

    def release(self):
        self.installed = False
        self.closed = True


@dataclass(frozen=True)
class ResearchFactory:
    """An immutable bindable factory; never capture another server's graph."""
    builder: Callable
    research: ResearchServices | None = None

    def bind(self, research):
        return replace(self, research=research)

    def __call__(self, context, *args, **kwargs):
        if self.research is None:
            raise ValueError('RESEARCH_SERVICES_NOT_READY')
        self.research.require_store(context.store, ready=True)
        return self.builder(context, self.research, *args, **kwargs)


def bind_registrations(entries, research):
    # Rebinding an already bound ResearchFactory returns a fresh value. This
    # matters when scripts reuse the first app's shallow-copied settings.
    return [replace(entry, factory=entry.factory.bind(research))
            if isinstance(entry.factory, ResearchFactory) else entry for entry in entries]


def bind_preset(preset, research):
    fields = ('runtime_factory', 'context_reader', 'candidate_validator', 'candidate_builder', 'experiment')
    changes = {name: value.bind(research) for name in fields
               if isinstance(value := getattr(preset, name, None), ResearchFactory)}
    return replace(preset, **changes) if changes else preset
