# Reusable CLI/MCP identity bindings

Status: implementation design ready for review; runtime changes and whole-workflow acceptance remain pending.
Implementation baseline: planning `84c827c` merged with main `9a933aa`; no dependency on #97/#99.
OpenSpec: [reuse-member-tool-operations](../../openspec/changes/reuse-member-tool-operations/proposal.md).
Source and bounded probe baseline: `13f36d25fe4c7552c507875dab4a75d566c438ab` (production behavior inherited from PR #95).

## Product purpose

Agent Factory provides reusable identity, tool and workflow execution foundations for a trusted team. Members should be able to use their preferred Agent/client to compose CLI tools, MCP tools and skill materials, selecting their own external-account connections or explicitly shared connections for each task. Agno AgentOS and PostgreSQL remain the selected execution and persistence foundation; applications package useful workflows on top.

Account administrators manage accounts. Members connect resources and publish materials/applications themselves; owners choose personal/team sharing. The task actor, credential owner and selected execution connection remain distinct.

## Verified foundation

A bounded synthetic probe exercised the production SQLite encrypted vault, configuration/binding HTTP routers, hashed MaterialDefinition objects, ExecutionBindings preflight/build/resolve, and actual official MCP protocol calls to a loopback server. It used synthetic authentication and directly invoked the resolved adapter after binding resolution.

| Case | Observed result |
| --- | --- |
| Same installed-adapter material, Alice's own connection | Remote identity Alice |
| Same material, Bob's own connection | Remote identity Bob |
| Same material, Bob explicitly selects Alice's shared connection | Remote identity Alice; actor remains Bob |
| Member-created materials, each member uses their own material/connection | Both resolve and call with their own identity |
| Alice's member-created material, Bob selects Alice's shared connection | Remote identity Alice |
| Alice's member-created material, Bob selects his equivalent personal MCP connection | Preflight `CONNECTION_ADAPTER_MISMATCH`; build HTTP 409; no dispatch |
| Retained shared handle after Alice withdraws sharing | Credential resolution HTTP 409 `CONNECTION_NOT_CONFIGURED`; no dispatch |

Six MCP business calls returned the expected identity across eight cases. Shared resource inspection omitted credential references and revisions. This establishes the custody/binding/MCP layer; it does not establish published application execution, a native Agno workflow, PostgreSQL, production authentication, CLI execution, or restart recovery.

## Owning contracts and concrete gap

- `platform/agent_factory/personal_tool_contract.py:48-109,126-130`: operation descriptors, invocation context and the adapter extension contract. Core owns connection resolution and effect receipts; adapters own protocol/process behavior.
- `platform/agent_factory/personal_tools.py:262-285`: members can configure different credential connections for the same installed adapter.
- `platform/agent_factory/personal_tools.py:310-325,226`: each member-created resource receives a fresh adapter identity, which is embedded in its runtime binding.
- `platform/agent_factory/personal_tools.py:382-390,427-447`: resource owner and requesting actor stay distinct; use checks current membership/sharing and resolves the owner's credential.
- `platform/agent_factory/execution_bindings.py:194-211,303-306` and `connections.py:476-477`: material binding requires the expected adapter identity.
- `platform/agent_factory/composition.py:217-221`: skill/prompt materials contribute instructions. `delegation.py:48-81` preserves root material/connection scope for the supported remote-child path.
- `platform/agent_factory/personal_tool_execution.py:63-65,96-119`: the native factory also requires the selected handle's adapter object to match the registered operation; native call identities retain completed/UNKNOWN effects. Whole-workflow behavior still needs acceptance below.

The adapter mismatch is correct under today's contract. The product gap is that a member-authored reusable operation remains coupled to its original resource registration: another member cannot select an independently saved equivalent operation connection while retaining the same material.

## Minimum implementation contract, not implemented

A member explicitly creates a public immutable operation version with a fixed destination. Its hash includes the complete descriptor semantics and dispatch recipe: MCP URL/remoteToolName, or CLI executable, fixed arguments, argument mapping, stdin mode, working directory, non-secret environment, credential injection names and output format. Schema, permissions and limits are included. Descriptor equality alone is insufficient. Private resource configurations are not automatically published; arguments/environment may contain secrets. Public creation shows the complete recipe and keeps credentials in separately selected accounts.

Keep both exact `connection_adapter_ref` and native adapter object-identity checks. Alice and Bob create independent account resources referencing one operation version, adapterId and process-local adapter instance; their tasks retain the same published material id/version/hash. A second account does not require republishing. Bob can explicitly select Alice's shared account. Revoking Alice's account must not revoke Bob's; material withdrawal still blocks subsequent calls through the fresh material guard.

Add an immutable operation table and narrow create/list/read operation APIs plus an account-creation API under the existing personal-tools router. Reuse vault, sharing, material publication and native effects. Restore the operation first, then its accounts; missing or mismatched state fails explicitly. Never select an arbitrary active account to reconstruct the public operation. Existing installed adapters, member resources, plans and effects remain unchanged. Preserve original UNKNOWN identities and never redispatch to resolve uncertainty.

Two stages: (1) core operation/account API, canonical hashing and restore with portable regression tests; (2) UI and real native CLI/MCP two-user PG/restart acceptance. Detailed file ownership and checks are in [tasks.md](../../openspec/changes/reuse-member-tool-operations/tasks.md); architecture and API shape are in [design.md](../../openspec/changes/reuse-member-tool-operations/design.md). No production implementation or acceptance run has occurred for this change.

## Platform-independent acceptance, pending

- [ ] Publish one member-authored reusable operation/workflow, run it through real native Agno and disposable PostgreSQL, and use a synthetic authenticated external client through the normal API entrypoint.
- [ ] Compose a real local CLI call and a loopback MCP call; Alice and Bob select independently saved personal resources while retaining the same published material/version/hash, without republishing the operation. Include a second account for one member; the already-working installed-adapter path alone cannot satisfy this check.
- [ ] Bob explicitly selects Alice's shared connection for one step and his own for another; remote identity observations and task ownership match those selections.
- [ ] Verify binding continuity across two steps and one supported child path, including worker restart; incompatible schemas/versions fail before dispatch.
- [ ] Withdraw sharing, revoke a credential or disable the actor between steps; prove no next business call and no implicit account substitution.
- [ ] Lose acknowledgements and restart around each step; completed operations are not replayed, UNKNOWN retains its original identity, and remote counters prove no duplicate effects.
- [ ] Inspect model-visible content, public projections, errors and logs for synthetic secrets; preserve useful actor/connection/effect provenance and shared credential-reference hiding.

These checks need no named external platform. Keep PR #96 limited to tests/CI. History (#97), shutdown custody (#98), application composition (#99), remote runtime handoff (#100) and research rounds (#101) retain their own scopes; ordinary CLI/MCP integration does not depend on all of them. Runtime implementation follows the bounded OpenSpec scope above; no additional routine approval gate is introduced.
