# DSH-style local chat visual QA

final result: passed for the documented UI states; real Edge file delivery verified after manual Save

This result covers the chat UI and event presentation. The full Windows regression suite passes at its recorded revision. Initial live Edge observation limits are preserved below; subsequent manual Save and exact file verification complete real delivery, as recorded in [joint integration notes](docs/reviews/dsh-skills-integration-20261108.md).

## Comparison target and evidence

The selected target is the actual local DeepSeek Harness Web 0.2.2-rc.1 at `http://127.0.0.1:3080/`. Its frontend packages and MIT notices match the pinned upstream release recorded in `THIRD_PARTY_NOTICES.md`.

The implementation is the existing Agent Factory application at `https://127.0.0.1:3100/`.

Evidence directory: `D:/WorkSpace/agent-factory-local/design-evidence/`. These private screenshots and receipts are outside the source repository.

| Evidence | State |
| --- | --- |
| `dsh-empty-1280.png`, `factory-empty-final-1280.png` | Empty composer, dark theme, sidebar open, desktop. |
| `empty-comparison.png` | Both full frames in the same comparison image, DSH left and Factory right. |
| `composer-comparison.png` | Both composer crops in one image, preserving equal pixel scale. |
| `dsh-tools-expanded-1280.png`, `factory-tools-final-1280.png`, `tools-comparison.png` | Completed turn with process/tool details, source and implementation. Conversation content differs. |
| `factory-mobile-empty.png`, `factory-mobile-chat.png`, `dsh-mobile-chat.png` | Narrow layout and existing conversation. |
| `live-ssh-waiting.png`, `live-ssh-tools.png`, `live-ssh-final.png`, `live-ssh-mobile.png` | Actual subscription-provider run and SSH receipts. |
| `ui-fixture-waiting.png`, `ui-fixture-unknown.png`, `ui-fixture-reconciled.png`, `ui-fixture-mobile.png` | Explicit synthetic UI state cases. |
| `factory-settings-final.png`, `factory-model-settings-final.png` | Dark Settings and model resource cards, checked after the contrast correction. |

Desktop CSS viewport: 1280 × 900. Source and implementation bitmaps: 1280 × 900. Device density is normalized to one bitmap pixel per CSS pixel; final measured implementation DPR is approximately 1. Source uses CDP deviceScaleFactor 1. Narrow viewport: 390 × 844. No full browser chrome is included.

The requested Library image could not be materialized because this session exposes no Library materialization tool. The existing local DSH application is also an explicitly selected reference and supplies the actual visual target. The requested `iab` surface returns unavailable; the existing local Edge surface supplies browser evidence.

## Comparison history

1. The original Factory frame has a white shell, a taller form near the top, five separate navigation rows, and expanded raw events. These are major layout and content-density differences from DSH.
2. The first dark build still has a white search input, a floating account row, and an oversized composer. These P2 issues are fixed with scoped input styles, a full-height sidebar, and reduced composer spacing. Secondary navigation moves under More.
3. The final full-frame and composer comparison align the 280-pixel sidebar, dark surfaces, centered title, workspace context row, rounded composer, right-aligned model selector, and send action. The composer begins at the same vertical region. Final narrow captures retain controls and show no horizontal document overflow.
4. Completed process headers collapse by default. Expanding a tool reveals parameters, actual output, exit code, errors, and the complete receipt. A real historical command failure is visibly labeled. The actual SSH run adds three tool rows, returns a final answer, and survives refresh without a new turn or additional tool calls.
5. Settings resource cards initially retain light surfaces. Scoped dark card colors restore readable foregrounds; actual Settings and model-card screenshots confirm the correction.

The initial broad-layout result did not cover the remaining chat-detail gaps. A later actual-source comparison identified message metadata, copying, readable tool output, code controls, composition and scroll recovery. Those corrections and current evidence are recorded in [the chat-detail comparison](docs/reviews/chat-detail-fidelity-20261108.md). This assessment applies to those inspected states.

## Required fidelity surfaces

- Fonts and typography: matches the DSH system stack, including Segoe UI and Microsoft YaHei. The welcome heading is 24 pixels on desktop; ordinary controls and chat copy use 13 to 14 pixels. Factory keeps its existing name and icon. The DSH brand font and whale are intentionally not substituted for Factory branding.
- Spacing and layout rhythm: 280-pixel sidebar, bounded centered content, 20-pixel composer radius, compact process rows, and sticky composer. The final narrow send control measures 44 × 44 CSS pixels. Navigation collapses, and mobile selection returns to the conversation.
- Colors and tokens: application `#141414`, sidebar `#1c1c1c`, composer `#292929`, muted labels `#a2a4a6`, restrained borders, and distinct failure/wait colors. The reference gradients and decorative effects are not invented.
- Image quality and assets: the chat target has no illustration or photo requirement. Existing Tabler library icons and the existing Factory brand icon remain sharp at both sizes. No custom raster or SVG stand-ins are introduced.
- Copy and content: the real current question reaches the native model. Internal events remain behind raw history. Missing arguments and missing outcomes are explicit. Silence never claims hidden thinking, continued activity, or success. Old SSH training and 15-minute wording is removed from the resource card.

## Interaction and accessibility checks

Checked sidebar collapse and reopen, session selection, Settings return, new-message disabled state, native details controls, parameter/result folding, actual error detail, Markdown table rendering, final answer, and narrow layout. Visible focus rings and semantic buttons, labels, and disclosure elements remain. The silence clock is separate from the static live status announcement.

The last actual browser reload reports no captured console errors. Actual Edge screenshots, not the production build alone, support the visual result.

All seven cases pass on disposable PostgreSQL and the scripted model. They cover the current user message and follow-up, SSH events and retained history, synthetic missing/late/reconciled events and connection EOF, local process Stop, compression, native file creation/replacement, exact download bytes, path boundaries, and successful application shutdown. Those synthetic cases remain distinct from provider acceptance.

Actual provider acceptance uses the user's existing OpenCode Go subscription and DeepSeek V4.1 Flash. The question `ssh 可用了吗?` completes in 93.11 seconds, with discovery and two read-only SSH commands. Both return exit 0. Refresh retains one turn and three calls. This real run provides waiting, tool receipt, final reply, and recovery evidence; it does not establish real provider disconnect recovery or remote descendant cancellation.

## Follow-up polish and limits

P3: Factory retains product-specific navigation, labels, branding, and table borders. DSH plugin controls, permission modes, token meters, hidden reasoning, and team chrome are not added without corresponding Factory data or capabilities.

The current follow-up adds message and code copying, code wrapping, compact process timing, readable native file/command output, a growing model-labeled composer, active Stop and return-to-bottom. It keeps a single bounded conversation scroller at narrow widths. The normal-encoding 21-case Windows suite passes in 113.536 seconds at that revision. Actual Edge checks confirm clipboard content, two-line narrow composition, a 44-pixel Send target and no document overflow. A fresh subscription-provider task confirms SSH exit 0 and a 34-byte Chinese file create/edit/read cycle; its follow-up verifies two visible native Skills reads. The download event initially times out. Subsequent diagnosis finds the complete temporary bytes; manual Save produces the final file with identical bytes and hash, completing real Edge delivery.

An earlier real model session also creates, edits and reads a 40-byte Chinese file. Its initial download wait and native-window URL rejection remain historical limitations; they do not override the later verified 34-byte delivery. The scripted Chromium download passes independently. Windows TLS/RST warnings and the existing global CSS and bundle-size warnings remain.
