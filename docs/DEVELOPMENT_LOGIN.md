# Removed development login

The product no longer provides a development/mock/demo login mode. The old launcher and embedded identity provider have been removed; historical behavior remains in Git history and acceptance records only.

Use [explicit local password or OIDC login](../README.md#start-with-configured-authentication) and the [upgrade instructions](REMOVE_DEMO_UPGRADE.md). With neither method configured, login stays unavailable. Local password login creates new ordinary members through a controlled command; it does not turn existing synthetic users into real accounts or authorize deleting their database.
