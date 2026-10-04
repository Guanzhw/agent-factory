# Production and research decisions still needed

Current continuation (2026-10-04): [v0.3 scope reconciliation](V03_SCOPE_RECONCILIATION.md)
separates remaining product code from external production inputs. Draft
[PR21](https://github.com/Guanzhw/agent-factory/pull/21) and
[PR22](https://github.com/Guanzhw/agent-factory/pull/22) completed individual stages,
not full-product acceptance. Go is authorized for subscription-only coding tests;
production scientific-provider selection and invoice verification remain separate.
The public-code development example passed live DeepSeek; Luna's second response
was incomplete and remains UNKNOWN with the campaign stopped. No retry occurred.
Older status/gate statements below describe their original stage.

This is a read-only integration assessment, not a request to change accounts or
supply secrets. Collect the following four choices together before implementation.

| Decision | Minimum non-secret input | Existing boundary |
|---|---|---|
| Browser identity entry | Existing OIDC provider or trusted authentication gateway; public issuer/discovery URL, audience/client ID, site/callback domain, session/logout expectations. Say none if none exists. | Current operator HS256 bearer JWT and SQL directory work; no OIDC callback/JWKS integration or production browser session exists. Demo cookie bridge is not production SSO. |
| Identity and responsibilities | Stable provider subject to Factory owner mapping; pilot researcher, material author and separate reviewer IDs; who disables users; remote origin/receiver owner mapping and audience if needed. | SQL roles remain authoritative; no automatic production users/admins, no roles granted solely by JWT, and current revocation remains checked. No shared signing secrets requested. |
| First real research question | One public non-toy question, domain/time scope, allowed sources/full-text licences, desired deliverable and minimum success criteria (source count/comparison dimensions/citations), domain reviewer. | Installed literature query IDs are immutable; a new question requires a governed query contract. Actual PubMed evidence has zero sources after connection failure; synthetic reports do not establish live research. |
| Experiment or literature only | Choose literature-only, or provide public repo + pinned commit, dataset version/licence, baseline command, metric/threshold, target OS/CPU/RAM/GPU/runtime/network allowlist, mutable-file scope and approver. | Existing experiment is a fixed reviewed toy. Real workspace/evaluator/version/licence governance still needs implementation and acceptance. |

Existing production model-provider selection remains separate from the Go coding
profile. No subscription-only billing evidence or live scientific-provider success
has been established. Target machines (32 cores/64 GB or 54 cores/192 GB) also remain
unmeasured; the current controlled cloud fixture is 4 CPUs/16 GiB.
