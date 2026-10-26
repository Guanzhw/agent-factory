# Integration boundaries

The selected core is **Agno AgentOS 3.1.0**, upstream `ab1d6007f09163c3adadbe06f998dc481b77a09a`, with PostgreSQL. Dependencies are locked in `uv.lock` and `package-lock.json`. The former legacy OpenCode SDK/Express foundation has been removed; it is not the current engine.

The factory adds immutable plans, task bindings, semantic fingerprints, material dependency preflight and evidence metadata through public Agno hooks. Native Registry, authorization, run/session/tool lifecycle and durable queue are reused. See [ADR](decisions/0001-native-plan-envelope.md).

Default core composition installs no application, model instance or synthetic seed. Research uses an explicit deployment entrypoint; members select their own configured resources. The historical Auto-Research acceptance used a labeled deterministic model, invented literature and a fixed synthetic sorting fixture. That evidence did not establish real discovery, scientific evaluation or paid model compatibility; synthetic fixtures remain test-only.

The historical [OpenResearch](OPENRESEARCH.md) integration used exact source/CLI contracts and task-scoped adapter hygiene. Factory session ownership was retained. ORX's own OpenCode chat adapter, spawn/wake session ownership, provisioning and service startup were omitted. Installed ORX was not automatically updated or trusted by matching version text.

[Remote resources](REMOTE_RESOURCES.md) separates compute allocation, Agno HTTP runtime attachment and optional A2A. No arbitrary endpoint/credential is accepted from prompts or request bodies. Actual native metadata tests and explicit synthetic lifecycle tests are distinguished. Live remote runtime execution and provisioned compute are not yet accepted.


Material-driven execution is documented in [MATERIAL_ASSEMBLY.md](MATERIAL_ASSEMBLY.md).
Operators register native Model/tool/knowledge/environment factories through
`Settings.runtime_adapters` and trusted owner handles through
`Settings.trusted_connections` before `create_app`. The authenticated
`/api/factory/runtime-adapters` endpoint returns only installed descriptors; it
cannot register or construct a factory. Startup registers the built-in personal-model
adapter and restores configured member-tool adapters, but does not configure a
demo model, application, provider credentials or paid-model binding automatically.

[test_execution_bindings.py](../platform/tests/test_execution_bindings.py) shows
controlled native factory contracts. The removed `test_orx_factory_postgres.py`
belongs to historical controlled ORX discovery evidence, not current reproduction.
These synthetic examples are not production provider recipes. Missing items are
reported per exact selected material and owner pin.
Live configuration and scientific acceptance remain separate authorized work.

Governed Factory-to-Factory execution now uses immutable receiver-local binding
proofs and authenticated current origin authorization over actual HTTP. It allows
exact non-demo plans when both approved application/material/adapter/connection/
policy preflights pass. The controlled providers used in acceptance do not prove
live model/ORX or production TLS/host authorization. See REMOTE_BINDINGS.md.
