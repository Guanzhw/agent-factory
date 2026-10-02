# Durable token and amount ledger

The Factory admits each native Model provider primitive through a PostgreSQL
reservation before calling it. Agno remains the owner of model retries, tool
loops, native runs and queue tickets. The ledger does not launch a model, create
credentials, authorize a paid provider, or act as a second scheduler.

The installed defaults are two explicit local contracts: `DemoModel` and
`LocalORXWorkflowModel`. Their registered provider/model identities and zero
tariff are fixed. Both return authoritative zero provider usage because they
make no provider request. A real ORX evaluator subprocess is separate from model
usage. A zero tariff is not evidence of autonomous scientific discovery.

## Immutable approval and prices

New composition plans freeze `usageBudget` before the plan fingerprint. Schema
version 1 includes currency, amount in integer currency micro-units, total token
ceiling, exact provider/model, adapter ID/revision, pricing revision/digest,
input/output prices per million tokens, per-attempt input/output caps, model
binding digest and policy revision. The whole commitment has a SHA-256 digest.
Money uses integer arithmetic; USD 1 is 1,000,000 micro-units. Each attempt's
charge is the ceiling of the combined input/output price numerator, divided by
1,000,000. No exchange rate or floating-point conversion is used.

Pricing revisions and policy bodies are immutable persisted configurations.
Reusing a revision for changed contents is rejected. New active pricing may be
installed under a new revision, but an old plan cannot silently adopt it. An
unregistered model, mismatched returned Model identity, changed rate/currency,
or changed immutable binding is rejected before the provider primitive.

Historical local zero-cost plans gain an independent migration record pinned
to their original plan hash. Their plan bytes, material hashes and fingerprints
remain unchanged. This migration cannot turn an unknown or non-local historical
adapter into an approved provider. Historical reads retain the original account
and usage facts after current pricing or policy changes. A missing unpriced
historical commitment is reported as unavailable rather than creating a paid
approval. Rotating policy does not create a fresh per-user balance; a change to
the original user ceiling requires a separately designed, explicit migration.

## Admission, settlement and recovery

`DelegatingModel` wraps the selected fresh native Model's `invoke`, `ainvoke`,
`invoke_stream` and `ainvoke_stream`. Agno's native retry loop calls the wrapped
primitive again, so every actual retry has its own durable attempt. These hooks
reserve before the call; run-level aggregate metrics are not an admission gate.
Adapters must disable hidden provider SDK retries and register a trusted guard
that enforces the actual input and output request limits. Only the two installed
local implementations bypass this provider-specific contract.

One short PostgreSQL advisory transaction serializes the intersection of task,
every persisted ancestor, root and the owner's lifetime account. It checks
`settled + held + reservation <= original ceiling` for both tokens and money.
Every affected account is updated in the same transaction. A provider call is
rejected inside a borrowed uncommitted Store transaction: its reservation must
be committed before invocation. This bounded single-server implementation
prioritizes correctness for approximately 20 users; lock contention and
multi-server accounting throughput have not been benchmarked.

Attempts move from `RESERVED` to `SETTLED` only with a registered authoritative
usage reader. A final usage receipt converts the reservation into the actual
token and amount charge. The settlement transaction uses the attempt's pinned
tariff and account identities. Repeating the same authoritative receipt is
idempotent; replacing it is rejected. Settlement occurs before the post-response
permission recheck, so subsequent revocation or cancellation cannot erase an
incurred charge.

An exception, unparseable usage, a partial stream without final authoritative
usage, or process interruption keeps the complete reservation as `UNKNOWN` or
outstanding `RESERVED`. Cancellation and restart do not refund it. A trusted
backend reconciliation may later settle the original attempt from authoritative
evidence. There is no user-facing settlement or price-write endpoint. A retry
requires a new reservation and can be denied by the previous unknown hold.

If authoritative usage exceeds its reserved bound, the ledger records the
actual bill and marks the resulting limit violation in the facts/events. It
does not discard an incurred overage to make totals appear compliant. Further
admission is denied until the original ceilings allow it.

## Remote allocations

The receiver preserves the original source plan and `usageBudget`. A separate
immutable receiver commitment is pinned to the imported plan hash and exact
receiver binding proof. Its currency/rate must be compatible with the source;
costed provider/model selection cannot change remotely. A zero-to-zero mapping
still needs installed exact deterministic identities and a reviewed binding
proof. Remote children preserve their source subset and inherit the root's
receiver price and narrower token/amount ceilings after persisted ancestry
validation.

Before dispatch, the origin commits an allocation against its original root,
ancestor and user accounts. The allocation binds receipt, target, both owners,
both tasks, source/receiver plan hashes and both commitment hashes. The receiver
imports the exact grant through the authenticated trusted handoff, after the
current origin authority attests its SHA-256. A hash alone is not authentication.
The receiver charges the grant account together with its own task/ancestor/user
accounts before any provider attempt; children use the same root grant.

Receiver statements are hashed, cumulative and monotonic. The origin applies
each settlement delta once and retains the unused allocation while execution
or usage is unresolved. Positive native/effect/tree stop evidence releases only
the unused portion when no usage hold remains. Positive stop with unknown
provider usage retains the allocation. Replaying allocation, import or statement
cannot reopen a closed grant, refund a settled bill, or reset the original cap.

For the narrow prepare/cancel race, an exact authenticated
`CANCELLED_NO_DISPATCH` receipt can reclaim the unused origin allocation. It must
bind the original receiver task, plan and quote, provide positive `allStopped`,
and contain no native/run identity. Any earlier accounted or unknown invocation
conflicts with this proof and retains the hold. Missing ACKs and absent native
rows are not no-dispatch evidence.

## Verification and boundaries

`platform/tests/test_usage_ledger_postgres.py` passed 19 tests on generated
loopback PostgreSQL databases (10.184 seconds). Controlled native Models and
synthetic pinned prices prove actual Agent-to-Model dispatch; four competing
provider primitives admit exactly two at the shared user ceiling; native retry
attempts are independently held/settled; sync/async streams and partial closure
retain unknown reservations; native SQL role revocation after a response cannot
erase settlement; restart retains balances; model/rate/policy changes cannot
reuse approval; legacy plan hashes remain unchanged; persisted root/parent/child
accounts share ceilings; overages remain charged; independent origin/receiver
databases retain unknown remote allocation through positive stop, then reclaim
unused funds from authoritative settlement without resetting the source cap;
positive no-dispatch reclaim is idempotent; currency rotation preserves history
while denying old approval; and a shared amount ceiling independently denies
new work while token capacity remains. Ruff and Pyright pass for the
ledger and Model hooks.

The independent-database ledger test validates real PostgreSQL/provider-hook
accounting, not authenticated HTTP handoff transport or paid provider billing.
Those protocol/application checks are reported separately. No real provider,
real credentials, paid compute, production access or live monetary charge was
used. No real provider-specific SDK usage parser or hidden-retry contract has
been verified. Enabling a paid provider still requires explicit user approval,
an installed reviewed adapter/guard/usage reader, trusted user-scoped credentials,
and current immutable pricing and budget approval. Durable unknown balances
need an operator reconciliation policy; this milestone does not auto-refund,
auto-top-up, or claim production accounting certification.
