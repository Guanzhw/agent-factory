"""Original synthetic catalog; no private knowledge or executable user scripts."""
from fastapi import HTTPException


def seed_catalog(store, seeds=()):
    existing = {item["id"] for item in store.materials()}
    for mid, kind, name, content, permissions in seeds:
        if mid not in existing:
            store.add_material({"id": mid, "kind": kind, "name": name, "description": content, "content": content,
                "license": "MIT", "origin": "factory synthetic fixture", "dependencies": [], "compatibility": ["agno:3.1.0", "mode:demo"],
                "permissions": permissions, "inputSchema": {}, "outputSchema": {}, "archived": False}, "demo-bootstrap", seed=True)


def create_plan(store, owner, goal, mode, application=None, *,
                application_ref=None, material_choices=None, connection_refs=None, input_values=None):
    """Use governed composition and preserve trusted child-plan storage hooks."""
    service = getattr(store, "composition", None)
    if service is None:
        raise HTTPException(503, "Governed composition service is unavailable")
    ancestors = getattr(store, "ancestors", None)
    if application_ref is None and ancestors:
        application_ref = ancestors[0].get("applicationRef")
    return service.create_plan(owner, goal, mode, application,
        application_ref=application_ref, material_choices=material_choices,
        connection_refs=connection_refs, plan_store=store, **({'input_values': input_values} if input_values is not None else {}))
