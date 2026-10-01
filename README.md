# Agent Factory

A departmental platform built around **reusable materials → scenario-specific agent definitions → scoped execution**. Auto-Research is the first planned application. Public project, MIT license.

The current delivery is **M1: project and development environment initialization**. It provides a running local API and foundation page, shared contracts, dependency lockfile, tests and CI. Factory and research features remain explicit acceptance checkpoints. Platform selection is on hold while existing open-source implementations are evaluated; this scaffold does not commit to a custom core.

## Start on Windows

Requires Node.js 22.13+ and npm. Node 24 is used by CI. No model account, payment or global package installation is needed to run M1.

```powershell
Set-Location D:\CodeSpace\agent-factory
npm ci --ignore-scripts
npm run check
npm start
```

Open http://127.0.0.1:3100. The API binds to loopback. Build before starting (`npm run build`) after changing the frontend. For frontend development run `npm run dev:web` in a second terminal; Vite proxies `/api` to the API on port 3100. API development runs with `npm run dev`.

```powershell
# Terminal 1
npm run dev
# Terminal 2
npm run dev:web
```

`GET /api/health` reports local service health; `GET /api/status` reports the actual implementation checkpoint. Model calls are disabled. There is no research submission UI in M1.

## Delivery checkpoints

| Milestone | Acceptance | Current status |
|---|---|---|
| M1 | Safe project directory, public MIT repo, pinned install, lint/typecheck/tests/build, local startup and capability preflight | Foundation implemented; see verification record |
| M2 | Material catalog, composition, versioned definitions, manager/user roles, credentials/data bindings, durable jobs/scheduling/events/cancel/artifacts/audit | Planned, awaiting reuse-first platform decision |
| M3 | Auto-Research literature and executable experiments, real OpenCode integration, narrow ORX tools, approval/evidence/report frontends | Planned; live models need explicit budget approval |
| M4 | Recovery, security/isolation, complete browser workflows, deployment and operational acceptance | Planned |

See [acceptance matrix](docs/ACCEPTANCE.md), [architecture](docs/ARCHITECTURE.md), [integration contracts](docs/INTEGRATIONS.md) and [security assumptions](docs/SECURITY.md).

## Integration status

OpenResearch target: `alphaXiv/OpenResearch` at `f336b121525d99364e2dee4fe90b2784894a54e6`. The user's existing ORX installation is not automatically replaced. A verified matching binary and deployment-owned state are required before integration.

The exploratory import check uses pinned `@opencode-ai/sdk@1.18.34` and its `/v2` network client export. This is distinct from the current OpenCode 2 packages `@opencode/sdk` and `@opencode/client`. The final runtime choice remains open during reuse evaluation. Constructing the checked client makes no network or model request. This import check does not prove a live OpenCode server or research workflow is compatible.

## Contribution

Run `npm run check` before opening a draft pull request. Commit only new project code, docs and synthetic fixtures. Keep `.env`, credentials, user/company data, generated research and workspaces out of Git. No deployment, access grants, or paid services are enabled by this scaffold.
