"""Explicit public-query evidence application; ordinary two-admin publication."""
from pathlib import Path

from .config import Settings
from .connections import TrustedConnectionBinding
from .local_orx_profile import environment_registration, ENVIRONMENT_ADAPTER_ID
from .orx_literature_tools import TOOLS, MODEL_ID, REVISION
from .orx_tools import ORX_ADAPTER_ID, CAPABILITY

APPLICATION_ID = "public-literature-evidence-v2"
PROFILE = "public-literature-evidence-v2"
CONNECTION_NAME = "publicLiterature"
REGISTRATION_REF = "reviewed-public-literature-v2"
PUBLIC_QUERY = {"queryId": "public-rag-v1", "corpus": "pubmed", "limit": 1}


def literature_settings(*, db_url: str, workspace: Path, provider, owner="alice", port=3106):
    trusted = TrustedConnectionBinding(owner, "orx", ORX_ADAPTER_ID, frozenset({CAPABILITY}), PROFILE,
        available=True, opaque_handle=provider, handle_ref=PROFILE)
    return Settings(db_url=db_url, workspace=workspace, port=port, max_workers=1,
        max_tool_calls=8, experiment_timeout_seconds=30, experiment_output_bytes=65536,
        # Match the reviewed ORX profile: vfs may clone the preloaded image.
        # This is conservative admission headroom, not a hard filesystem quota.
        storage_task_reserve_bytes=4 * 1024 * 1024 * 1024,
        temporary_policy="admin-review", policy_revision=PROFILE, material_policy_revision=PROFILE,
        material_review_mode="separate-admin", runtime_tool_contract="orx-evidence-v2",
        trusted_connections={REGISTRATION_REF: trusted}, runtime_adapters=[environment_registration()])


def publish_literature_application(state, *, author, reviewer):
    if author == reviewer:
        raise ValueError("A distinct publication reviewer is required")
    governance, applications, store = state["material_governance"], state["applications"], state["store"]
    state["auth"].require(author, "components:write")
    state["auth"].require(reviewer, "agent_os:admin")
    materials = []
    for kind, name, adapter_id, revision in [("model", "model", MODEL_ID, "1"),
            ("environment", "environment", ENVIRONMENT_ADAPTER_ID, "1"),
            *[("tool", name, adapter_id, REVISION) for name, adapter_id in TOOLS.items()]]:
        identifier = PROFILE + "-" + name
        config = {"connectionName": CONNECTION_NAME, **PUBLIC_QUERY} if kind == "tool" else {}
        material = governance.create_draft(author, {"id": identifier, "kind": kind,
            "name": "公开文献证据 " + name, "description": "书目与有界摘录；不调用模型、不生成科研综合结论。",
            "content": name, "license": "MIT", "compatibility": ["agno:3.1.0"], "dependencies": [],
            "permissions": [CAPABILITY] if kind == "tool" else [],
            "runtimeBinding": {"adapterId": adapter_id, "revision": revision, "config": config},
            "provenance": {"kind": "original", "notice": "Original no-provider public-query workflow."}}, PROFILE + ":draft:" + name)
        review = governance.request_publication(author, identifier, material["version"], PROFILE + ":review:" + name)
        governance.decide_publication(reviewer, review["id"], True, PROFILE + ":approve:" + name)
        materials.append(next(row for row in store.materials(published_only=True) if row["id"] == identifier and row["version"] == material["version"]))
    application = applications.create_draft(author, {"id": APPLICATION_ID, "name": "公开文献来源证据",
        "description": "批准的公开查询、书目、摘录、缺正文状态与可下载证据包；无模型服务。",
        "defaultMode": "bibliography", "modes": {"bibliography": {
            "materialRefs": [{key: item[key] for key in ("id", "version", "sha256")} for item in materials],
            "capabilities": [CAPABILITY], "toolOrder": list(TOOLS), "config": {},
            "connectionRequirements": [{"name": CONNECTION_NAME, "kind": "orx", "requiredCapabilities": [CAPABILITY], "required": True}],
            "budget": {"toolCalls": 8, "maxDepth": 1, "maxChildren": 1, "experimentSeconds": 30, "outputBytes": 65536}}},
        "discoveryKeywords": ["公开文献", "来源证据", "literature evidence"]}, PROFILE + ":application")
    review = applications.request_publication(author, application["id"], application["version"], PROFILE + ":app-review")
    applications.decide_publication(reviewer, review["id"], True, PROFILE + ":app-approve")
    return application
