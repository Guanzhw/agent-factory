# Final authorized DeepSeek path validation

This stage follows accepted managed-egress commit
`e90de8a9a7ec69e00b5be896a6888216efcc3997`. The operator authorized one final
independent `deepseek-flash` synthetic coding request. It cannot replay or refund
the two UNKNOWN attempts. The cumulative DeepSeek budget is three, Luna zero.
Billing-off state is user-attested; invoice and account state are not inferred.

`GoFinalSmokeCampaign.authorize_final` uses the same original `.budget.sqlite`
file. An IMMEDIATE transaction creates one immutable final authorization,
retains previous campaign stop facts and both prior ticket records, and grants
only its returning process permission to reserve ordinal three. The old tickets
are immutable. Reopening, changing confirmation IDs, another process, or another
campaign name cannot grant another final authorization. The original stable
session is retained, but the new request receives a distinct UUID.

The dedicated runner requires all explicit flags, invokes the existing adapter
once, and does not run tools or a product workflow. It uses the existing verified
TLS/environment proxy/CA client, fixed official Chat Completions endpoint,
zero retries, 60-second timeout, streaming usage and a 64-token output cap.
Only root's guarded callback reads OPENCODE_GO from runtime environment. No
credential, generated text, raw exception, HTTP body or arbitrary header value
is persisted. Evidence retains allowlisted stages/status/model/finish reason,
usage and cumulative budget counts. Any failure stops; no Luna or PAYG fallback.

A successful new request would validate this path only. It would neither prove
the historical connection-failure root cause nor constitute production identity,
scientific workflow, target-host or billing acceptance. The prior unauthenticated
public GET is not evidence of authenticated inference success.
