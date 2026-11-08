# Chat detail comparison

The user reports that the broad layout is close to DSH Web but the chat details remain far apart. This follow-up compares the actual local DSH Web 0.2.2-rc.1 and Factory sessions before changing the interface. It focuses on ordinary messages, composition, visible model output, tool details, Markdown, scrolling, errors, Stop and narrow screens.

Current-run screenshots are stored outside the repository under `D:/WorkSpace/agent-factory-local/design-evidence/chat-details-20261108/`. The desktop viewport is 1280 by 900 at device scale 1. The narrow viewport is 390 by 844. The products show different real conversations; this is a comparison of presentation and behavior, not identical model output.

## Observed steps

| Step | Evidence | Finding before the follow-up |
| --- | --- | --- |
| 1. Read a completed reply | `01-dsh-reply.png`, `02-factory-before.png` | DSH places a plain right-aligned user bubble and time/copy row above a compact execution disclosure. Factory adds a turn header, instruction-state labels and an assistant label to every exchange. |
| 2. Expand the tool process | `03-dsh-tools.png`, `04-factory-tools-before.png` | DSH uses compact labeled operations. Factory hides an ordinary read-file result behind a raw full-event JSON disclosure and gives no command/file preview in the collapsed operation. |
| 3. Read older messages | Desktop interaction and captured reply state | DSH exposes a return-to-bottom control. Factory has following logic but no way to resume following from the conversation itself. |
| 4. Compose another message | Desktop and narrow captures | Factory's conversation composer lacks the current model label, stays taller, permits sending an empty draft, and requires manual textarea resizing. DSH keeps a compact, growing input with the model beside Send. |
| 5. Read Markdown/code | DSH visible code-block toolbar and Factory reply capture | Factory renders tables, but code blocks lack Copy and wrap controls. Ordinary message-copy controls are also absent. |
| 6. Use a narrow screen | `05-dsh-mobile.png`, `06-factory-mobile-before.png` | The same extra metadata consumes more space on Factory. Its input remains usable and there is no horizontal page overflow, but the message/input hierarchy differs visibly. |

The meaningful gaps are message hierarchy, actual content access, copying, composition and scroll recovery. Font family and base 14-pixel text already match the reference. Screenshot evidence alone does not establish complete accessibility or real provider recovery.

## Verification boundaries

Existing Factory waiting, unknown-output, disconnect and Stop behavior uses real saved events. This follow-up keeps those facts visible while reducing routine metadata. It does not synthesize hidden model reasoning, provider usage, ratings or controls with no corresponding operation.

Source output that contains private runtime information is immediately collapsed and excluded from saved screenshots. Current accepted source captures show ordinary text and collapsed operation labels. Screenshots and real conversation contents are not committed.

## Delivered corrections

Ordinary exchanges now use a user bubble with a time/copy row and a plain assistant reply. Correction and pending-inclusion labels remain when they change the meaning. The compact completed-process header reports elapsed time from saved timestamps. Tool rows preview the actual path or argv and expose readable file content, stdout and errors before the full event JSON.

User messages, replies and code blocks have working clipboard controls with explicit failure feedback. Code blocks offer wrapping, including empty fenced blocks; tables scroll within the reply. The composer grows with its content and viewport width, shows the selected model, disables empty submission and keeps Stop beside the active input. A return-to-bottom control restores following. Opening execution details or scrolling up preserves the reader's position; a ResizeObserver tracks actual content growth, including asynchronous file-list changes.

The first full 21-case run exposed a real empty-code-block crash: React Markdown supplies no code children for an empty fence. The owning renderer now accepts that native contract. Later targeted attempts corrected native clipboard CRLF expectations and browser readiness/locator assumptions. All failed runs remain in external evidence. The corrected full suite passes 21 cases in 112.939 seconds with the default Windows encoding. Frontend lint, types and production build, Ruff and Pyright pass. Independent source review also found and verified fixes for inherited checkbox height and code-child whitespace rules.

## Actual browser and provider evidence

`09-factory-tools-final.png` and `10-factory-reply-final.png` show the current desktop implementation; `11-factory-mobile-final.png` shows the same actual reply at 390 by 844. Source and implementation tool captures were inspected together at equal scale. Actual Edge clipboard reading verifies the Python code. Narrow composition grows to two lines, the Send control measures 44 by 44 pixels, and document dimensions remain 390 by 844 without horizontal overflow. Desktop document dimensions remain 1280 by 900.

The existing subscription model completes the combined acceptance task in 20 seconds. The expanded native SSH receipt shows exit 0 and all three requested command outputs. Native file results show the created and replaced Chinese file; its read result contains the expected two lines and the file list reports 34 bytes. This run also exposes and leads to a correction for missing native skill-resource read records. A separate real follow-up completes in 12 seconds with visible instruction/reference calls and their full native results; `12-factory-skills-final.png` shows the result. Refresh preserves both turns and their five/two recorded calls. The correction and red/green evidence are detailed in the joint notes.

The ordinary Edge file link is clicked while waiting for a browser download event. The click succeeds, but no download event arrives within 15 seconds. Later read-only diagnosis finds the complete 34 bytes in its temporary file. After the user clicks Save, the completed `.txt` matches the exact session source byte-for-byte and by SHA-256, and `.crdownload` disappears. The user's screenshot shows Open file. Real Edge delivery is therefore verified with manual Save; the earlier observation timeout is retained without treating it as an application failure. Scripted Chromium's independent byte check remains separate evidence. See the joint notes for the full hash and browser-tool limitation.

Final verification after the Skills event correction passes all 21 cases in 113.536 seconds, alongside frontend checks, Ruff and Pyright. The local preview retains the verified code and both real acceptance turns.


## Second chat-detail correction

The second Product Design pass starts from merged source `37af529` on local branch `codex/dsh-chat-detail-round2-20261108`. It uses a fresh preflight, same-size desktop/tablet/phone captures, the actual installed DSH component/CSS modules, implementation and a new design-QA pass. [Current design QA](../../design-qa.md) supersedes the earlier chat-detail acceptance for the affected surfaces.

The source contracts come from installed `@deepseek-ai` packages under the DSH dependency tree:

- `dsh-client-ui-conversation/lib/client.js:20057,20634,21701,22015-22120`: independent header, 76px tabbed height, composer hierarchy, 28px panel radius, 36px editor and 34px primary action.
- `dsh-client-ui-chat/lib/client.js:4793,4880-5005,5053,5931,5965-6009`: real activity labels, compact disclosure, right-aligned user stack and copy/time actions.
- `dsh-client-ui-sidebar-files/lib/client.js:2197,2229-2242`: real right-side file access.
- `dsh-client-ui-layout/lib/client.js:13,250,479`: 1024px auto-collapse and 768px drawer boundaries.

The delivered frontend removes idle status clutter from the body, moves management details into working native popovers, and preserves unknown results, failed-tool counts, file-read errors and idle cancellation of future collaboration. A short conversation no longer offers Jump when it cannot scroll. Long streamed replies retain the reader's position until following resumes. The independent 76px header remains fixed while the conversation scrolls. A reproduced long-title overflow is fixed in the owning grid rather than hidden.

All 23 minimal Windows regressions pass in 125.435 seconds on the final code. The pending-request regression proves that an unconfirmed request blocks new composition while an allowed idle Stop still reaches the real stop API, persists stopped state and causes no model call. The old disabled condition fails this regression before the final implementation passes. The first full attempt's selector failures and actual 396px-at-390px overflow remain in external evidence. Frontend lint/types/build, Ruff, Pyright and whitespace checks pass; independent final source review reports no remaining confirmed blocker. The preview's backend and existing running user session are left active. The changes are prepared for draft PR review. Merge and deployment remain separate.
