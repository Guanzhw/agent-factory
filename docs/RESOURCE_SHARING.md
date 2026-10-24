# Personal and team resources

Every model, remote service, CLI/MCP tool and SSH server belongs to the member who creates it. New and existing resources are personal until their owner selects **Share with team**. The page shows the owner and current visibility. Account administrators manage accounts and have no override over another member's resources.

Owners configure resources, change their visibility and revoke them. Other active members can discover and bind team resources. For a shared model, choose **Set as default**; the platform creates a connection owned by the requesting member. Their tasks and results keep that member's identity. For remote services, tools and SSH, bind or enable the visible team connection in the resource page.

Credentials stay with the resource owner in encrypted custody. Team catalog responses omit the owner's credential reference and revision, as well as private tool configuration. Execution resolves the original owner's credential and retains the requesting member for task ownership and current account checks. Sharing never copies a credential into another member's vault.

Models, MCP and supported remote services can use **No authentication** when the target protocol permits it. This creates no placeholder credential and sends no Authorization header. Model services accept valid HTTP or HTTPS addresses, including local/private IPs, custom ports and API base paths. Authentication failures from a target are reported as failed operations; provide a credential when that service requires one.

The native OpenResearch remote service contract requires an explicit bearer token or basic proxy authentication. Its page offers those modes and does not offer anonymous access. Generic model and OpenCode remote services support the unauthenticated path above.

Changing a resource to personal immediately prevents another member's next invocation, including calls through previously obtained handles. Disabling the caller, revoking the resource or revoking its credential also prevents new operations. An already dispatched remote operation retains its original recovery and cancellation identity; changing visibility does not imply that the remote process has stopped.

When a save or sharing response is unknown, use **Check original request**. The page reads the original receipt and does not automatically repeat the write. Model default and sharing receipts remain tied to the original requesting member.

The sharing record stores only resource reference, owner and `personal`/`team` visibility. Existing resource tables and task/connection ownership stay intact; an absent sharing record means personal. Back up the database together with the vault master key as described in the credential setup documentation.
