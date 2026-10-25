# Why

Explicit research setup publishes required materials and their application through existing governance services. A real rollback test left materials committed because MaterialGovernance opened its own transaction instead of borrowing the current Store transaction.

# What Changes

Borrow an existing Store connection in MaterialGovernance writes, retaining its existing governance lock. Standalone writes still own their transaction. No new publication mechanism or schema.

# Impact

Material governance transaction ownership and rollback tests; application setup remains a separate consumer.
