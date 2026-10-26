# Scoped application content

`ApplicationContent` publishes immutable, curated JSON snapshots and optional exact artifact references. Applications own their domain records and revision relationships. The core owns the publication identity and uses existing `ResourceSharing` for personal/team visibility. A source label is provenance supplied by the author, not a verified application execution identity.

## Contract

`POST /api/factory/application-content` accepts:

```json
{
  "requestId": "publish-experiment-1",
  "source": {"application": "research", "record": "experiment-1", "revision": "1"},
  "content": {"state": "negative-result", "analysis": "Author interpretation"},
  "artifacts": [],
  "visibility": "team"
}
```

Visibility defaults to `personal`. The service derives the owner from the current authenticated member. Content is limited to 16 KiB of bounded JSON; at most 20 artifact references are accepted. Each reference is exactly `{taskId, artifactId, sha256}`. The author must own the original task, and the persisted bytes must match the SHA. Ordinary artifact output limits apply; this API does not proxy remote paths or large checkpoints.

For a larger complete body, supply `contentArtifact: {taskId, artifactId, sha256}` instead of `content`. Its bytes must be a UTF-8 JSON object with the same structure and safe-data checks. Both the raw bytes and UTF-8 JSON serialization must fit the existing per-artifact output budget (`experiment_output_bytes`, normally 65536). The body reference is independent of the 20 selected evidence artifacts. Inline requests retain their original escaped-JSON 16 KiB limit and idempotency fingerprint.

Reads and lists check current publication and source permissions before loading the original body artifact, then return the complete object in `content`. The body is not copied into the publication row. Missing or damaged bytes fail explicitly; there is no cached-body fallback. A page retains at most its existing item limit times the per-body budget. The body reference also permits its exact artifact download under these same permissions, without adding it to the selected `artifacts` list.

- `GET /api/factory/application-content?after=<cursor>&limit=50` lists currently visible snapshots (maximum page size 100).
- `GET /api/factory/application-content/{id}` reads one snapshot.
- `POST /api/factory/application-content/{id}/sharing` accepts `{requestId, visibility}` and requires its author.
- `GET /api/factory/application-content/{id}/artifacts/{artifactId}` downloads only a selected artifact or the exact body artifact, as an attachment with `private, no-store` caching.

Publication returns `id`, `ownerId`, `source`, `content`, exact artifact references, `createdAt`, `visibility`, `isOwner`, and `verificationStatus: unverified`. This wrapper does not certify author claims. Sharing does not alter original artifact provenance. Artifact metadata projections omit execution bindings and connection references. A hash match proves byte identity, not scientific correctness.

The reader and author must remain current members. Every new read checks current visibility; retained IDs and download URLs confer no continuing authority. Revocation does not erase the original publication/task or withdraw bytes already delivered. Replaying the original publish or share request returns current visibility and never restores a subsequently revoked grant. Reusing a request ID for different content conflicts.

## Domain transaction integration

Trusted application services can publish a domain revision atomically:

```python
with store.transaction() as conn:
    conn.execute(revisions.insert().values(...))
    published = application_content.publish(owner, publication, request_id)
```

`GovernedStorage` borrows the existing transaction. Domain changes, publication, sharing registration, and idempotency receipt commit or roll back together. No second domain state machine or event delivery is implied. Publish a new snapshot for a new revision; the application maintains the relation to earlier revisions.

Granting an artifact never grants its whole job, sibling artifacts, model connections, or credentials. Missing bytes and changed hashes fail explicitly. This service does not rerun tasks or substitute evidence. Authors must curate public content itself; the field/secret checks cannot determine whether arbitrary prose or artifact bytes are appropriate to share.

## Validation

`test_application_content` exercises portable owner/member checks, replay after revocation, immutable snapshots, bounds, and shared transaction rollback. `test_application_content_postgres` requires an isolated PostgreSQL fixture and checks real native checksum artifacts, exact downloads without job access, restart, tampering/missing evidence, and cross-connection transaction visibility. Synthetic checksum output is not real model research or GPU validation.
