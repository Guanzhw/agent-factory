# Desktop workspace entry points

**Historical navigation milestone:** the former OpenResearch entry/preparation
routes and product demo startup are retired. The original acceptance record
below is retained, not current navigation or startup guidance; see the
[README](../README.md).

The primary navigation groups the existing platform views into Applications,
Resources and Tasks. Applications opens the catalog and OpenResearch's existing
project/session workflow. Resources explains where to configure a personal
model, enroll an SSH server or manage an existing connection. Tasks retains the
original plan, approval, execution, event and evidence views. An empty task list
links back to OpenResearch instead of leaving the user without a next step.

Comparison, schedules, storage and developer composition remain in the folded
advanced entry. Administrator views remain role scoped. No resource card
prepares a runtime or sends a research goal; the application still requires the
existing explicit actions and server authorization.

Existing `tab=models`, `tab=connections`, project, mode and task deep links stay
valid. The new `tab=resources` pointer survives refresh and Back/Forward. URL
pointers carry no permission or execution authority. Models preserve their
allowlisted `modelReturn` view in the URL through refresh and Back/Forward;
returning from resources preserves the chosen research mode and project.
Connections also has a general return that preserves that context. The SSH
card's explicit "Go to OpenResearch preparation" action instead enters personal
mode and selects the owner's enabled server. It only navigates to setup; it does
not prepare an environment or submit a research command.

This change only reorganizes frontend entry points. Its desktop browser
acceptance uses a loopback synthetic demo and an isolated disposable PostgreSQL
database, with no actual model calls. Research result and follow-up acceptance
belongs to the original native OpenResearch continuation validation.

This is the public navigation sub-batch of desktop simplification. The research
body's goal, process, evidence and result layout remains separate unfinished
work; this navigation change does not close that broader item.
