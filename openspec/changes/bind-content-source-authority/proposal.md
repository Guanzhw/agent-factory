# Why

Research associations and selected deliverables can contain information derived from another member's publication. Application-only checks cannot safely grant a second member access to a selected core artifact: publishing that artifact without dependencies creates a generic content-download bypass, while reading it as the owner would proxy owner authority.

# What Changes

Bind immutable source content IDs to curated publications. Core checks all original sources on every body/list/artifact read and original publication replay. Owner sharing controls remain available without exposing an unavailable derived body. No second artifact store, application ACL or execution controller is added.

# Capabilities
## New Capabilities
- `content-source-authority`: source-dependent curated content and exact artifact access.
## Modified Capabilities
None.

# Impact
ApplicationContent and its current tests; the concrete consumers are research peer-derived evidence and selected deliverable attachments. Manifests remain application records. No model/GPU/credential calls.
