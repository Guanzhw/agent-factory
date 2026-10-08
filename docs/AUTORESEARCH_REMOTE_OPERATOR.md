# Remote AutoResearch operator handoff

This entrypoint assembles a controller and a scientific receiver from fixed,
reviewed Python modules. JSON cannot name arbitrary factories or import modules.
It does **not** initialize databases, install scientific dependencies, approve a
research task, or establish that a GPU/model run succeeded.

Preserve the [accepted original baseline](RESEARCH_BASELINE_ACCEPTANCE.md), its
private receipts/database, and its sealed scientific package. That acceptance is
not acceptance of this remote workflow. See also the
[local adapter contract](RESEARCH_LOCAL_ADAPTER.md) and
[candidate handoff](RESEARCH_CANDIDATE_HANDOFF.md).

## Environment and roles

Use separate uv projects/environments for the updated Factory control plane and
original scientific interpreter. The updated control-plane checkout uses its
`pyproject.toml` and `uv.lock`: Python >=3.12, Agno 3.1.0, FastAPI, uvicorn,
SQLAlchemy, psycopg, HTTPX and the remaining exact locked dependencies. For a
**new dedicated control-plane checkout only**, an operator can install with:

```sh
uv sync --frozen --link-mode copy
```

Do not run that command in the retained research environment. Copy mode here
avoids package hardlinks; it does not turn uv's interpreter symlink into a copy.
The scientific interpreter still requires its existing validated interpreter
contract, inventory and startup profile. Do not upgrade it to satisfy control
plane imports. No installation was performed as part of this documentation.

| Role | Owns | Must not do |
|---|---|---|
| Controller | Goal session, ORX/OpenCode launcher, bounded authorized model broker, origin authority, remote child orchestration | Import receiver files by assuming a shared filesystem; run local scientific training |
| Receiver | Native scientific phases and original process/GPU custody; fixed preparation/training/evaluation adapters | Construct a parent research model, launch ORX, or access the controller's model credential |
| Retained baseline | Original task/plan/lease/evaluation rows and sealed scientific bytes | Be reinitialized, migrated into the controller, or used as the new active task database |

Controller and receiver each need an already initialized PostgreSQL database
with the exact AutoResearch policy and existing principals. `--check` is a
read-only compatibility gate, not a bootstrap command. It returns BLOCKED or
NOT_CHECKED for incompatible/uninitialized policy; it never repairs it. Required
settings include `admin-review`, `separate-admin`, tool contract
`autoresearch-session-v1`, plan revision `autoresearch-goal-plan-v1` and material
revision `autoresearch-goal-material-v1`. Use the existing administrative
provisioning process; this entrypoint does not seed identities or grant rights.

The receiver also opens the distinct retained-baseline database through its
original `task-research-bootstrap-v1` policy verification. The baseline context
factory rejects the same database name as the active receiver database, even
across hosts. Keep controller, receiver and retained baseline databases distinct.
Connection aliases are not proof of distinct physical servers. Original retained
row/plan/lease lineage is checked separately.

Original tokenizer preparation belongs to the retained baseline database/root.
The receiver's new task database must not install that original preparation
provider as a generally allocatable target. Its preparation phase verifies the
existing artifact against the original preparation state; new training and
evaluation custody belong to the active receiver. Baseline score reads are
fresh original-custody verification through the retained reader, not a score
copied from a JSON configuration.

## Private configuration

Start from the **synthetic, non-runnable** shape examples:

- [Controller](examples/autoresearch-controller.synthetic.json)
- [Receiver](examples/autoresearch-receiver.synthetic.json)

Their `.invalid` hosts, paths, hashes, manifests and identities are placeholders.
They passed strict JSON/project-shape validation only. Do not change a digest to
make a failed check pass or treat these examples as scientific input evidence.
No example contains a credential value. Replace every placeholder from actual
operator-reviewed original records, not from guesses.

The complete top-level keys are `schema`, `role`, `workspace`, `port`,
`databaseRef`, `jwtRef`, `handoffBearerRef`, `project`, `publication`.
Unknown keys, duplicate JSON keys and nonfinite values are rejected. References
are environment-variable **names**; an operator process manager supplies their
existing values privately. Never put credentials in JSON, command arguments,
source control, diagnostic reports or public logs. Supply a minimal environment;
receiver has no reason to receive a model credential. Do not print the environment.

Configuration must be an owned, single-link regular file, mode **0600**, in an
owned **0700** parent directory, maximum 2 MiB. Paths are absolute; traversal and
symlink components are rejected. Use private new copies/CoW staging for mutable
input preparation; never chmod a shared package or data cache to bypass custody.
Program/cache/custody directories must be distinct and satisfy their existing
private root contracts. Scientific receiver stage roots belong below its active
workspace and outside the retained workspace and research venv.

Common project fields pin the project ID, owner, goal, full original comparison
manifest, microbatch, bounded limits, pinned upstream root and applicationRef. The optional
`applicationSnapshot` is null initially, then the complete original governed
application snapshot imported explicitly on the other endpoint.
Controller additionally supplies exact receiver mapping/revision/project pin,
ORX/OpenCode binary and image pins, existing model credential reference,
explicit billing authorization, and the ordered 15 scientific runtime file pins.
Receiver additionally supplies original baseline file/database references,
`scientificRuntime` root identity and exact file pins, retained preparation
snapshot/reference, stage roots and exact trusted-origin mapping/fingerprint.
The role-specific examples enumerate every current field.

Controller runtime hashes compute **declared commitments only**. Receiver must
verify the same actual sealed `site-packages/agent_factory` root, files, selected
interpreter, package inventory and environment. `ScientificRuntimePin` never
imports that old package into the updated control plane. Matching the original
scientific bytes preserves the original driver fingerprint; new controller
source is not silently substituted. Do not repin the old baseline to the latest
checkout or rewrite its manifest.

## Check, explicitly publish, then serve

Run from the dedicated updated checkout with its already installed locked
control-plane environment. The private process environment supplies only the
credential references needed by the selected role. The following paths are
operator placeholders, not files created by these instructions:

```sh
uv run --offline --no-sync python scripts/autoresearch_operator.py --help
uv run --offline --no-sync python scripts/autoresearch_operator.py \
  --config /private/operator/controller.json --check
uv run --offline --no-sync python scripts/autoresearch_operator.py \
  --config /private/operator/receiver.json --check
```

`--check` reads the configured database reference, validates settings and current
policy, and does not construct services or read model credentials. It is not a
connectivity test of the receiver, GPU compatibility test, retained-baseline
verification, or model/billing authorization proof.

With both policies compatible and the existing distinct publication identities
approved for this action, first explicitly publish on the controller:

```sh
uv run --offline --no-sync python scripts/autoresearch_operator.py \
  --config /private/operator/controller.json --prepare
```

`--prepare` **writes governance records** using the named author and reviewer:
material drafts, publication requests/decisions and application publication. The
author needs `components:write`; importing a snapshot additionally requires
`agent_os:admin` for the author. The distinct reviewer needs `agent_os:admin`.
Listing two names is not evidence of independent human review. This operator
command is an explicit publication action, not a request for later approval.
It does not approve a task plan or start research. Receiver construction also
reads the retained baseline and reconstructs its services; existing service
constructors may perform idempotent metadata operations. Only the compatibility
preflights are strictly read-only.

Both endpoints must publish the **same full definition**: `research` plus
`remote-scientific-preparation`, `remote-scientific-training` and
`remote-scientific-evaluation`, including the exact parent materials and budgets.
Receiver parent registrations are catalogue-only and all their factories deny
construction. They are not claims of a working receiver-side parent provider.
Scientific phase mappings use their distinct original adapter IDs.

The first preparation returns `publication.applicationRef` **and** the full
`publication.applicationSnapshot`. Application hashes include `createdAt`:
creating the same definition twice is not sufficient to obtain the same hash.
Explicitly copy the complete returned snapshot into the receiver's private
`project.applicationSnapshot`; keep its `applicationRef` null until local
publication. Review this operator transfer; there is no automatic network copy
or inherited publication approval. Do not manufacture timestamps or hashes.

```sh
uv run --offline --no-sync python scripts/autoresearch_operator.py \
  --config /private/operator/receiver.json --prepare
```

The receiver first verifies that the snapshot's complete normalized definition
matches the locally generated four-mode application and exact material refs.
It calls the existing trusted `ApplicationService.import_snapshot`, preserving
source timestamp/version/hash, then creates and approves a **separate local**
publication review. Import itself grants no execution authority. Conflicting
existing versions fail closed. A snapshot from a different project, budget,
material version or tool scope cannot be substituted.

Compare the returned `publication.applicationRef` values (`id`, `version`,
`sha256`), then put that exact common reference into **both private configs**
before serving. Commands never rewrite those files. Keep the imported snapshot
unchanged for idempotent receiver preparation. If material histories or an
existing same-version application differ, stop and reconcile through governance;
do not overwrite immutable versions or silently replace withdrawn materials.

```sh
uv run --offline --no-sync python scripts/autoresearch_operator.py \
  --config /private/operator/receiver.json --serve
uv run --offline --no-sync python scripts/autoresearch_operator.py \
  --config /private/operator/controller.json --serve
```

Serving requires a non-null current approved applicationRef. Both servers bind
only `127.0.0.1` at the configured port, with access logs disabled. Cross-host
routing therefore requires an already authorized authenticated tunnel/reverse
proxy and HTTPS endpoint. This command creates no public listener, tunnel,
firewall rule, TLS termination or persistent remote access. Neither cloud
loopback PostgreSQL nor a local URL implies target connectivity.

## Review and execution boundaries

User submission creates a current immutable plan subject to **admin review**.
Publication alone cannot start it. Pending review is a real waiting state, not
failure and not permission to auto-approve. Parent scope, origin authority,
receiver mappings, plan/material currency and each native scientific phase stay
bound to their original identities. Cancellation/UNKNOWN evidence must retain
custody until positive original cleanup; restarting is not permission to replay
an uncertain launch or model request.

Completion of the three subordinate phases alone does not complete the parent
research journey. The agent must call `research_result` to consume the verified
independent result, then record its next decision through `research_decision`.
Do not synthesize those acceptance flags from completed leases or a stop action.
A controlled model fixture must keep `modelExecuted` false even when its real
native child phases and evidence checks succeed.

An evaluator reads the completed training checkpoint through a separate
scientific-custody proof. The origin requires the same still-active paused
parent, current review/material policy, the original completed training child,
and its exact successful reclaimed lease/checkpoint. The proof grants only
that original custody read; it contains no execution capabilities, cannot
reactivate the child, and does not debit another tool call. Receiver checkpoint
bytes are still read and verified normally after that proof.

After cancellation or an explicit denial of current execution authority, receipt
cleanup reuses only previously validated scientific artifact claims. These are
historical claims, not a fresh scientific verification or a renewed execution
grant. Original native, process lease and GPU stop evidence must still be read
fresh; retained artifact claims alone cannot release capacity. While authority
remains active, artifact verification failures are errors and cannot fall back
to retained claims.

Controller model usage additionally requires its existing explicit subscription
and billing authorization. `billingAuthorized: false` is deliberately used in
the example. Do not turn it on based on a zero balance or catalogue readiness.
The bounded request limit is a task budget, not a provider subscription promise.
No credential/model call is needed to inspect CLI help.

This handoff documents executable assembly, not a new scientific result. The
accepted local baseline remains separately recorded. Synthetic configuration
checks and CI do not prove remote networking, actual provider usage, GPU
training/evaluation, successful candidate improvement, or production identity.

## Validation scope and remaining operator gates

The three-database integration fixture uses actual PostgreSQL/native services,
original preparation and bounded stdlib process/checkpoint/evaluation paths.
Its inter-endpoint transport is controlled ASGI, model decisions are synthetic,
and environment/device observations are explicit fixtures. It does not prove
cross-host TLS, a paid model call, GPU compatibility or a scientific improvement.
The separate concrete `_receiver` bootstrap test exercises real assembler and
receiver constructors with sealed synthetic files while mocking database/archive
and device boundaries; it is not a substitute for live retained-custody checks.

Before operating on the actual target, supply the existing three database
connections and exact policy states, reviewed private original snapshots and
sealed package/interpreter pins, current author/reviewer identities, and an
already authorized reachable origin/receiver route. The operator entrypoint
cannot create these facts. A missing or incompatible fact remains a blocker;
changing stored policy, regenerating baseline identities, installing into the
sealed venv, or replaying UNKNOWN work is not a recovery procedure.
