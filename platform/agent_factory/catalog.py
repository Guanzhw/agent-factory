"""Original synthetic catalog; no private knowledge or executable user scripts."""
from fastapi import HTTPException


SEEDS = [
    ("research-skill", "skill", "Evidence-led investigation", "Define a question, compare evidence, record provenance and uncertainty.", []),
    ("research-prompt", "prompt", "Auto-Research", "Investigate the user's bounded question. Label synthetic fixtures. Report evaluator and evidence provenance, never claim a real scientific result.", []),
    ("synthetic-knowledge", "knowledge", "Synthetic research corpus", "Two invented candidates; baseline=10 and candidate=8. Lower is better. This is a fixture, not literature.", []),
    ("literature-tool", "tool", "Literature fixture adapter", "literature_search", ["research:read"]),
    ("experiment-tool", "tool", "Bounded experiment", "run_experiment", ["experiment:synthetic"]),
    ("question-tool", "tool", "Clarify research scope", "ask_scope", ["question:ask"]),
    ("checksum-tool", "tool", "Checksum", "checksum", ["checksum:read"]),
    ("demo-model", "model", "Deterministic native tool model", "No network model calls. Agno owns the tool loop; deterministic model responses only.", []),
    ("local-environment", "environment", "Bounded local fixture", "Single-server synthetic tool environment; no arbitrary code, network, credentials or installation.", []),
]


def seed_catalog(store):
    existing = {item["id"] for item in store.materials()}
    for mid, kind, name, content, permissions in SEEDS:
        if mid not in existing:
            store.add_material({"id": mid, "kind": kind, "name": name, "description": content, "content": content,
                "license": "MIT", "origin": "factory synthetic fixture", "dependencies": [], "compatibility": ["agno:3.1.0", "mode:demo"],
                "permissions": permissions, "inputSchema": {}, "outputSchema": {}, "archived": False}, "demo-bootstrap", seed=True)


def create_plan(store, owner, goal, mode, application="research", *,
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
