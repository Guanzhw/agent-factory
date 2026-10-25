# Removed development login

The product no longer provides a development/mock/demo login mode. The old launcher and embedded identity provider have been removed; historical behavior remains in Git history and acceptance records only.

Use [configured authentication and upgrade instructions](REMOVE_DEMO_UPGRADE.md). Without a real configured identity service, login stays unavailable. Do not turn existing synthetic users into real accounts or delete their database as part of a code update.
