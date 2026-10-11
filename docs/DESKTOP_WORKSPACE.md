# Desktop workspace entry points

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
pointers carry no permission or execution authority.

This change only reorganizes frontend entry points. Its desktop browser
acceptance uses a loopback synthetic demo and an isolated disposable PostgreSQL
database, with no actual model calls. Research result and follow-up acceptance
belongs to the original native OpenResearch continuation validation.
