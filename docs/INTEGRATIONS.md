# Research integration contracts

Current milestone: project/environment initialization and evaluation of reusable open-source foundations. **Runtime selection is pending that evaluation.** The contracts below are exploratory source-checked preparation, not the selected production implementation or evidence of a completed live integration. No provider credentials were read, no model request was made, and no cloud compute was provisioned.

## OpenCode

The explored legacy dependency is exactly `@opencode-ai/sdk@1.18.34`, imported through `@opencode-ai/sdk/v2`. Its npm package was downloaded and its generated declarations inspected. **The `/v2` suffix denotes the legacy OpenCode 1 network API/client generation; it does not mean the current OpenCode 2 runtime.** The separately named `@opencode/sdk@2.0.21` describes an **in-process host**, while `@opencode/client@2.0.21` is the new generated-client target based on OpenCode's Effect HTTP API. The registry describes the latter as a private generation target, so supported external network-client consumption still needs verification. These package families are not drop-in replacements. The legacy contract below is exploratory only; choosing a foundation requires evaluating the current runtime and reusable applications first. Registry metadata was checked on 2026-10-01.

- Registry metadata: https://registry.npmjs.org/@opencode-ai%2fsdk/1.18.34, https://registry.npmjs.org/@opencode%2fsdk/2.0.21 and https://registry.npmjs.org/@opencode%2fclient/2.0.21
- Official current OpenCode 2 SDK documentation: https://opencode.ai/v2/docs/build/sdk
- Official current OpenCode 2 network client documentation: https://opencode.ai/v2/docs/build/client
- Legacy SDK documentation: https://opencode.ai/docs/sdk/
- Inspected package: `dist/v2/client.d.ts`, `dist/v2/gen/sdk.gen.d.ts`, and `dist/v2/gen/types.gen.d.ts` from the exact 1.18.34 tarball (npm shasum `089fd889265a012cf30ecfe9c75a816b234487f0`).

The `/v2` import has flat call arguments. Do not copy examples using the older `{ path, body }` argument shape. The inspected `client.session` interface supports:

```ts
const client = createOpencodeClient({ baseUrl, directory: workspace, throwOnError: true });
const created = await client.session.create({
  directory: workspace,
  title: `research:${job.id}`,
  permission: [{ permission: '*', pattern: '*', action: 'deny' }],
});
// Validate created.data before using it; do not assume a session exists after an API failure.
const result = await client.session.prompt({
  sessionID: created.data!.id,
  directory: workspace,
  model: { providerID, modelID },
  parts: [{ type: 'text', text: researchBriefWithRetrievedEvidence }],
}, { signal });
await client.session.abort({ sessionID, directory: workspace });
```

This is an exploratory legacy call contract, not a wired live workflow or a committed runtime choice. A client-only connection makes no paid request. Server startup and credential setup remain administrator-owned. If the chosen foundation uses an external OpenCode server, Factory should attach to its owned service rather than starting another copy through a research adapter or ORX. An embedded foundation instead needs an explicit in-process ownership/lifecycle contract.

Before the live milestone is accepted, the core must implement explicit opt-in, budget authorization, connection ownership, provider/model checks, bounded execution time/steps, SDK errors, session ID persistence, cancellation during session creation and prompting, a terminal-state reconciler, and artifact capture. Secrets belong in the trusted runtime/provider configuration, never in agent instructions, knowledge, job input, or artifacts. External evidence is untrusted content and cannot change permissions. Deny-all sessions let Factory-controlled tools retrieve evidence; any later model tool grants need their own scoped policy and acceptance tests.

## OpenResearch / ORX

The required upstream revision is exactly `f336b121525d99364e2dee4fe90b2784894a54e6`. Its [Cargo.toml](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/Cargo.toml) declares CLI package version `0.2.13`. Version alone cannot prove the commit: deployment must record the source revision and binary SHA-256, then verify the binary checksum plus `orx --version` before use. A different binary must fail the preflight. Do not use a floating latest installer or automatically update the integration binary.

The exact [CLI definitions](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/main.rs), [discovery implementation](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/discover.rs), and [experiment implementation](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/src/commands/exp.rs) were read at that revision. The intended narrow portable command boundary is:

| Operation | Argument array after executable | Contract |
|---|---|---|
| Version preflight | `--version` | Match `0.2.13`; also verify binary provenance |
| Project inventory | `--no-telemetry projects --json` | JSON local project records |
| Literature search | `--no-telemetry discover keyword <query> --limit <n>` | JSON retrieval results; `n` in 1–200 |
| Alternative corpora | `--no-telemetry discover openalex\|biorxiv\|pubmed <query> --limit <n>` | Corpus selected from an allowlist |
| Read paper | `--no-telemetry paper <paper-id>` | Preserve output and source identity |
| Read extracted text | `--no-telemetry paper <arxiv-id> --source alphaxiv --full` | Full-text route is alphaXiv-only |
| Inspect experiment | `--no-telemetry exp status <experiment-id>` | No invented JSON flag |
| Launch local experiment | `--no-telemetry exp run <experiment-id> --backend local` | Requires approved, provisioned experiment |
| Await terminal state | `--no-telemetry exp wait <experiment-id> --timeout <seconds> --interval <seconds>` | Completion alone is not success; inspect status |
| Cancel experiment | `--no-telemetry exp cancel <experiment-id>` | Cancels detached run through ORX supervisor |
| Run evidence | `--no-telemetry runs <project-id>` / `--no-telemetry logs <run-id>` | Capture outputs; validate IDs/terminal status |

Each token is a separate subprocess argument with `shell:false`. Query text is data, not a shell command. The future adapter must bound output, duration and concurrency, disable update notifications (`ORX_NO_UPDATE_CHECK=1`), and use an isolated deployment-owned ORX store. Upstream discovery returns JSON; several other commands produce human-readable output, so do not pretend they share one JSON schema. Status/evidence parsing needs captured fixtures from the pinned binary.

ORX project/experiment provisioning requires a separate reviewed deployment contract. The inspected CLI has project `view` and `edit`, and `create-experiment`, but no general `project create` command. Do not fabricate one. New experiments inherit run commands unless explicitly configured; executing an inherited command needs approval and source/commit capture. The first local integration can bind server-owned project/experiment references, then add native provisioning once its upstream API is verified. ORX worktrees and immutable run archives must be linked to Factory provenance.

The adapter must exclude `orx agent spawn`, `orx exp wake`, login, installer/update, global skill installation, feedback, publication, managed compute, and arbitrary shell execution. Factory owns agent sessions and resumption; ORX owns experiment supervision. Killing the short `exp run` CLI does **not** cancel its detached experiment, so Factory cancellation must also call `exp cancel` and reconcile status after restart. Remote/cloud backends need a separately authorized budget and credentials and remain unexecuted.

Windows preconditions and beta limits are documented in the pinned [Windows guide](https://github.com/alphaXiv/OpenResearch/blob/f336b121525d99364e2dee4fe90b2784894a54e6/docs/windows.md): Git for Windows supplies the required Bash/coreutils, local experiments are supported, and persistent remote-host mode has a Unix socket limitation. The environment milestone should detect these requirements; it should not mutate global user tools or credentials. Source download through Git was blocked here by local TLS configuration, so the exact source files were inspected through their fixed-revision public URLs. A complete source checkout/build and ORX binary verification remain pending.

## Runtime boundary and verification status

`Runtime.run(context): Promise<void>` receives a snapshotted job, isolated workspace, abort signal, event emitter and artifact collector. `Runtime.cancel(jobId): Promise<void>` requests cancellation. The agent core is responsible for queueing, clarification/approval, retries, ownership, time limits, terminal state and persistence; runtime entry occurs only after required answer and approval transitions. Artifact storage must validate names, sizes and hashes at the core boundary.

An uncommitted exploratory utility was drafted in the staging workspace and has **not** been included in the requested project initialization. It used explicitly invented literature fixtures and a seeded child-Node regression experiment for cancellation/reproducibility checks. This is not a deliverable, selected implementation, or live research acceptance evidence. Runtime implementation should follow the reusable-foundation decision.

Pending integration acceptance: mock-SDK contracts; pinned ORX command fixtures; live source retrieval and citation checks; approved model execution with usage/cost capture; project/experiment provisioning; experiment archive/evaluator/provenance; cancellation and restart reconciliation; scoped tools; credentials/connection ownership; budget enforcement. No live or paid verification is claimed by initialization.
