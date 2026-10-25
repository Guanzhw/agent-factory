# Bounded assistant events

`AssistantEvents` is a transactional notification service for published content. It does not execute tools or replace the native queue. Receiver-owned subscriptions select exact namespace/event type and an existing budget scope; there is no broadcast fallback or filter language.

## Receiver commitment

`configure(owner, EventSubscription(...), request_id)` requires the receiver's own endpoint and scope. Configure `endpointId`, `namespace`, `eventType`, `scopeId`, one-round `caps`, an absolute epoch `deadline` within the scope deadline, `maxDepth`, and `maxCandidates`. Only one configuration for an endpoint/namespace/type may be enabled. The current application integration can call this trusted service directly; scope creation is not a new public HTTP operation. `subscriptions_for(owner)` lists only that owner’s configurations; `delivery(owner, id)` is readable only by its publisher or receiver. Disable the old configuration before replacing it. Existing deliveries retain their original configuration.

The service never silently creates or replenishes a budget. Existing `LocalBudgetScopes` controls allocation, tool/account limits and settlement. Its unmetered mode does not promise a monetary cap, and a nonzero tool allowance does not grant training permission. The receiver application's fixed component/tool boundaries must prohibit GPU dispatch where required.

## Application transaction

```python
with store.transaction() as conn:
    # Persist the application revision and its curated publication here.
    events.emit(conn, owner, ContentEvent(
        namespace="research", eventType="record", contentId=publication_id,
        candidates=related_endpoint_ids, deadline=deadline,
    ), request_id)
```

`emit` must borrow that transaction. Candidate IDs are chosen by application relevance logic and intersected with exact receiver subscriptions. Empty candidates mean no recipients. Core stores no research schema or unfiltered private conversation. Notification text contains the publication ID; recipients read it through current content authorization.

Automatic follow-up emission supplies trusted `parent_delivery_id` and the original bound `task_id`. The service inherits the persisted root, increments depth and cannot extend the original deadline. These arguments are not exposed as sender-chosen message fields. Applications must pass the actual original execution context, not allow an agent to declare an unrelated new root.

## Admission and maintenance

`prepare(event_id, endpoint_id)` commits the unique delivery, allocation, message intent and owner/request budget-delivery mapping together. All reservation entry points resolve that durable mapping, including a public instances request that omits trusted allocation/delivery keywords. `deliver_batch(limit, stopping=event)` is an explicit asynchronous maintenance call, with no self-started thread. The core starts maintenance after native readiness and stops new delivery during shutdown. Each event, candidate and delivery checks the stop event before starting; already-running metadata work finishes, and the next native admission is not started. Shutdown awaits maintenance rather than cancelling a running `to_thread` operation.

Preparation locks proceed admission → event namespace → usage/messages, then the transaction ends. Request binding reuses the already-held admission lock; it never first acquires admission after holding usage. Native admission begins afterwards. Its original admission lock calls `validate_admission` to check the original delivery/request/plan/allocation and current subscription, endpoint and content authority. Subscription changes lock admission → event namespace; content and endpoint revocations use the same admission fence in their services. No native call may run inside the uncommitted event transaction.

Repeated delivery refers to the same message and allocation. No-task recovery re-enters the original request through native reservation's atomic fresh gate. A reserved task without a native receipt remains uncertain; timeout, expiry or missing receipt cannot authorize replacement execution. Allocation without confirmed termination remains held. Existing settlement decides when actual usage can be released.

Delivery states describe metadata work, not scientific success or native completion. Errors remain recorded by class rather than arbitrary exception parameters. Event and pending-message scans rotate by last attempt time, so a failing item does not block later items; the existing once-per-second bounded maintenance loop limits metadata retry frequency. A terminal rejection without an original task is committed under the admission lock, and fresh admission rejects that delivery afterwards. Its allocation remains held. Existing tasks are still observed and offered to existing settlement, including after authorization changes. Shutdown refusal keeps the delivery pending for a later process. Late-committing events are found by their own unscanned state, not a global increasing-ID watermark. Relatedness quality, real model behavior and GPU capacity require the separate real-environment acceptance cases.

## Verification boundaries

Portable tests cover transaction borrowing/rollback, exact candidate subscription matching, current revocation, propagation metadata and duplicate identities; their scope double tests routing only. PostgreSQL tests use actual scope allocation and isolated native metadata for concurrent deduplication, exhaustion, restart, and cross-connection visibility. Native admission/withdrawal race barriers are integration checks owned by the coordinator, not inferred from the portable tests.
