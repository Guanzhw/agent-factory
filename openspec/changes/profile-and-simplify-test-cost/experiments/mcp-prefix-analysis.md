# Fixed MCP prefix: one-run interpretation

13/13 passed, zero skips/retries/dropped events. unittest 163.744s; parent driver174.634s. This analysis reads the frozen trace only. No tests rerun. JSON companion `mcp-prefix-analysis.json` contains bounded scalar timings and original identities; duration fields there explicitly use milliseconds, timestamps seconds relative to probe start. `mcp-prefix-analysis-detail.txt` is raw analyst output whose legacy `*Ns` duration labels contain milliseconds; use the JSON/this document for publication.

## Original operations and generation transitions

| Case/task | Task ID | Native run ID | Claim→exit (seconds) | Tool invocation spans |
|---|---|---|---|---|
| auth-rejection first | caff966a-aa03-48e0-a7ea-2a6435d33011 | 899f629b-8dab-46ae-96b1-e30209318a17 |77.162787→79.651299 (two claims, attempts1/2)|77.789199→79.053908; expected failed/stopped=true|
| auth replacement |1ca6ba36-946d-4e79-95ad-416913e427ed|101a76cf-36e0-4a61-9961-d1095590738a|85.562505→100.483215 (14.920711s)|86.264186→92.718879;93.113533→100.229378; both completed|
| slow-delete first |c206ba4f-d264-4ced-8135-a7b7c49c2b25|c5deaa98-f212-4865-b68b-ab514724f925|140.330420→146.209566 (two claims, attempts1/2)|140.880595→145.681460; expected failed/stopped=true|
| slow-delete replacement |bac78530-9f27-4891-9142-c244b686f917|6c6267ba-8374-4b26-92d9-3d0d729ad59a|148.764797→162.440729 (13.675932s)|149.690241→156.209971;156.847419→162.246109; both completed|

Claim spans are NOT measured native-wait durations; the trace has no explicit wait-begin timestamp. Original20s native and5s terminal assertions passed. Two claims on the first run are original native recovery, not an extra tool invocation: one MCP invocation per first task.

First auth worker `worker-da5d7729`, replacement `worker-1d72a54d`; slow-delete `worker-7e0cc3ef` then `worker-037e0b19`. Each recorded locked_by matches executing worker. Auth original last slot exit79.651221 and callback finish79.047967 precede stop80.515779–80.534799; next start80.534829–84.646230. Slow-delete original slot exit146.209520 and callback finish145.671147 precede stop146.483475–146.492447; next start146.492473–147.775582. All six claims and slots have exits; maximum slot wait0.805498ms. No original claim/callback/slot overlaps replacement start. Different app/store/engine IDs are recorded per generation. Engine disposal inside stop is expected ExitStack behavior; the probe does not independently mark lifespan __aexit__, so do not claim a separately measured exit-before-dispose ordering.

## Callback costs (milliseconds)

| Case | callbacks | max queue | max callback wall | max own thread CPU | max per-callback SQL sum / max cursor | max per-callback pool sum / max acquire |
|---|---:|---:|---:|---:|---:|---:|
|auth-rejection + replacement|82|12.498825|706.368213|268.288330|539.750057 /394.896821|20.535608 /20.284104|
|slow-delete + replacement|100|4.404012|711.428033|266.821903|369.375391 /174.703536|30.479400 /30.199038|
|pure readiness|28|0.823038|150.320752|0.374543|0 /0|0 /0|

Maxima may belong to different callbacks; full IDs are in JSON. Auth callback24 is the706ms wall spike: own CPU80.341ms,55 SQL/539.750ms total,max394.897ms; queue3.956ms. Concurrent callback23 runs666.708ms, ownCPU268.288ms but SQL128.256ms/max10.023ms. No matching long GC interval exists. Without backend wait samples/server timings this is an observed client-side SQL wall spike, not proof of a slow PostgreSQL statement or lock. SQL/thread CPU/wall overlap and must not be summed as disjoint work. Pool metric covers `_do_get`, not pre-ping/full checkout.

All210 scheduled callbacks entered and finished. Two monitor awaits were canceled: callback84 at100.228868, worker finishes100.251562; callback113 at145.594232, finishes145.671147. Callback84 trails successful invocation exit by22.184ms but ends before native slot exit100.483142 and final stop. Current code joins callback threads only for failed pre-dispatch stop proof; this small successful-monitor tail is consistent with that contract and is not evidence of stale cross-generation execution. It does not justify dropping credential validation or UNKNOWN holds.

## GC, loops, and CPU

Two gen2 collections:81.042498–82.976354,1933.855ms wall/1933.363ms collector thread CPU,5492 objects;136.871075–138.314546,1443.471ms wall/1442.759ms collector CPU,8638 objects. Both occur during fixture startup (auth second-generation startup; slow-delete first-generation startup), outside native claim and callback intervals. Thus neither explains callback24 or the replacement tool times in this run.

The independent sampler is itself delayed:80.883734–82.983306 gap2.099571s with processCPU+2.071809s;136.457146–138.333805 gap1.876660s with processCPU+1.767990s. This directly supports CPU-active GC pauses in setup, not a scheduler-only idle period. Sampled cgroup counters show no throttled-period increments; no conclusion about other historical runs follows.

Maximum scheduled→arrival heartbeat delays: auth old/new loops0.975/4.181ms; slow-delete old/new loops12.044/98.773ms; pure0.451ms. These are successive generation loops, NOT simultaneous client/server-loop coverage. Server fixture loop is not registered by the probe. There is no measured dual-loop/GC overlap here; moreover the sampler cannot schedule heartbeats while it is itself paused, so small heartbeat latency does not exclude such a pause. GC durations and sample gaps are the stronger evidence.

## Pure readiness and teardown

No native task/run context, no SQL. Relative to invocation entry: transport construction begins4.043ms, ends15.220ms (duration11.170ms); first HTTP POST29.051ms; further POST60.599ms,GET62.291ms,POST82.570ms,POST105.008ms. `_call` exits119.208ms after the test has reached and canceled its blocked tool. Later POST274.344ms and DELETE278.443ms; invocation exits629.330ms with expected UNKNOWN/stopped=false. The test deliberately uses0.5s teardown and150ms credential delay, explaining callback212's150.321ms wall/0.091ms own CPU. This is not an unexpected callback stall. Method-only logging does not identify JSON-RPC method bodies; readiness is proven by the unchanged test assertion, not by relabeling a particular POST as tools/call.

Transport constructor durations are small (pure11.170ms); the historical2s initial-readiness failure is not reproduced. No DELETE2s authorization timeout is reproduced. The slow-delete first task's delayed server cleanup is intentional fixture behavior and releases correctly.

## Predeclared hypotheses and decision

- Callback queue starvation: no evidence in this run (maximum12.499ms; all callbacks entered/finished). SQL work remains substantial, with one395ms cursor wall spike, but not a demonstrated deadline failure or server-side cause.
- Loop/GC: substantial CPU-active collections reproduced, but in setup, outside failing-phase candidates. No failed callback/deadline coincides with GC; no historical causal attribution follows.
- Stale lifecycle/owner: measured original slots/claims/callbacks finish before generation replacement; no retained-owner bottleneck observed. This excludes that specific overlap for these traced operations, not all object retention or historical failures.

No new production defect or near-expiry failure is established. The successful-monitor22ms tail and394.897ms cursor spike are precise observations, not a basis for weakening cleanup, disabling GC, increasing deadlines, or declaring the historical problem fixed. With no reproduced failure, the experiment is **inconclusive for the historical root cause**. Do not repeat this prefix to obtain more green results. Preserve these timings; use already-installed phase diagnostics if a necessary future validation actually fails.
