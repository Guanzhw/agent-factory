"""The research application's service graph, owned and closed by its assembly.

Historical trusted adapters receive the original Factory store. This local
association lets them reach their application services without adding business
members or an extensible service locator to the core Store. It is not a public
application SDK or a registration mechanism.
"""
from dataclasses import dataclass
from typing import Any


@dataclass
class ResearchServices:
    factory_store: Any
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


_services: dict[int, ResearchServices] = {}


def services_for(store) -> ResearchServices:
    key = id(store)
    if key not in _services:
        _services[key] = ResearchServices(store)
    return _services[key]


def release_services(store) -> None:
    _services.pop(id(store), None)
