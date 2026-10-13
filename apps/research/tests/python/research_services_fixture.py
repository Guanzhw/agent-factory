"""Explicit research service ownership for portable test stores."""
from agent_factory_research.services import services_for


def with_research_services(store, **services):
    graph = services_for(store)
    for name, value in services.items():
        if not hasattr(graph, name):
            raise AssertionError('Unknown research fixture service: ' + name)
        setattr(graph, name, value)
    return store
