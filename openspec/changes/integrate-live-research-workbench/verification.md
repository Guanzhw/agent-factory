# 稳定项目路径阶段记录

基线b2a2460；spec先行085ebab。正式工作台不import demo数据、chat或chart。当前只接稳定projects/assistants读取与目标领域变更；后续运行/轮次/团队/助手接口仍待后端冻结并继续接线，本阶段不是完整产品完成。

- `npm run check` exit0：46文件、453测试通过，0跳过，包含5个新工作台测试及11个既有目标/原请求恢复回归；lint/typecheck/default core build通过。
- `node scripts/check_web_architecture.mjs --config scripts/architecture-web.json` exit0：88模块、0violations、0coverageGaps。首次命令遗漏必需config参数，报明确配置错误，修正调用后通过；无架构规则变动。
- 初次typecheck因新JSX条件漏闭合花括号失败，修复语法后上述完整check通过。
- 真实Chromium synthetic transport：1487×1058、390×844各一条项目旅程通过，0pageerror、0consoleerror、0写入。平台→工作台→项目、修改表单/取消、证据页刷新、history、创建对话框Esc/焦点返回、窄屏助手、返回平台通过。脚本和[结果](evidence/project-browser.json)、[桌面](evidence/project-desktop.png)、[窄屏](evidence/project-mobile.png)已保留。
- 首次浏览器夹具缺少auth config必填loginPath/logoutPath，平台入口未出现，见[首失败](evidence/first-fixture-failure.txt)；补齐现有公共配置契约后通过，未修改生产认证/超时/断言。
- 运行只绑定127.0.0.1:4176，无PG、模型、GPU或外部身份。当前仍保留Vite供后续接线验证，最终由本任务清理。

后续须冻结执行/证据API并接完旅程、实际API双用户浏览器、独立精简复审与集成CI。真实模型/GPU验收仍需对应参数与环境，不由本阶段合成结果替代。

## 轮次与执行配置接线

- 后端契约来源bb999e5（独立后端分支，未据此前端合成结果认定其真实恢复通过）。真实start/experiments客户端、nullable轮次/原操作、agent分析/来源、core任务入口已接；目标配置选择实际已发布应用、mode、允许材料pin与现连接，不收JSON或秘密。
- 原11项项目/请求恢复回归已迁移到正式ResearchWorkbench，原无消费者P4视图与research.css已删除；公开入口只re-export正式工作台，共用原命令恢复hook。没有保留第二执行/恢复实现。
- 最新针对性：5文件27项通过、0跳过，包括原11项、start408同键、UNKNOWN/无决策不冒充达标、执行配置空目录与精确pin/预算、demo/live共同导航回归。
- 变更后的首次完整Web：48文件中47通过、1失败；458项中457通过、1失败。失败为未修改的department-publication-ui.test.ts:67中发布材料通知等待超时，原日志[保留](evidence/full-web-first-failure.txt)。随后单独运行该文件25项通过，见[记录](evidence/publication-targeted.txt)。只证明隔离复验通过，尚未查明共享负载或fixture时序根因，不能把该完整run记为通过；未放宽超时/断言，未无改动整套追绿。
- 当前lint/typecheck、独立research build通过；架构93模块0违规/0gap。新依赖为0，未改变冻结lock。
- 最新真实Chromium两视口再次通过，增加项目→资源→模型→连接→模型→原项目/证据页返回；配置空目录实际显示缺项入口；轮次未决数据明确不作科学结论。仍是synthetic API transport，没有付费模型/GPU执行。
- 窄setup接口由并行任务提供；P7团队/QA尚待后端HTTP，仍需继续接线。当前不可合并成最终完整产品。

## 显式 setup 前端

对齐后端4b1efaf：实际模型connectionRef（含已保存模型绑定匹配）、环境descriptor、已发布工具及其依赖连接需求。无可用候选明确阻断；不接受JSON、密钥或fixture默认环境。草稿只展示声明，显式publish成功后才提供真实pin用于约定；成功draft id在researchSetup URL保留，资源往返可回原项目。新项目/平台入口清空旧setup指针。

同应用原命令恢复hook用于project与setup两个实际consumer，原11项恢复/目标行为迁移到正式UI继续通过。setup新增3项测试覆盖无真实连接/环境、草稿不发布/不假pin、显式发布后应用、丢失发布响应与owner切换原键恢复；共30项针对性通过。

此实质接线后的必要完整`npm run check` exit0：49文件、464测试通过、0跳过，lint/typecheck/default core build通过。前阶段完整失败仍保留；coordinator发现并停止两份长期占CPU的遗留Pyright进程，争用可能有关但没有本用例因果证明，不把本轮通过抹成从未失败或用作无争用性能基线。

真实Chromium两视口项目/资源旅程通过，追加setup无真实环境时保存按钮禁用及缺项提示，console/pageerror均空；仍合成API transport、无业务写入。真实后端setup/项目/执行整合浏览器由coordinator排PG；本结果不代模型/GPU/外部身份验收。P7助手问答与团队记录访问HTTP仍待后端，不把当前提示当完整旅程交付。

## 独立review P1：启动响应后读取失败

作者外review指出client.start将POST与后续GET连为一次返回；首次POST成功后GET403/404会被通用hook误判为写入未发生并清原意图。新增两个回归在修复前均失败（storage实际null），见[start-refresh-first-failure.txt](evidence/start-refresh-first-failure.txt)。

修复只改变成功POST之后的读取错误语义：明确返回“启动已响应、状态尚未核对”的复合Error并保留原cause/错误说明，原恢复hook保留request/payload。POST本身4xx分类不变，没有新增重试控制器。32项相关测试通过，含403/404、remount、新启动禁用、同键恢复。修复仍待独立精确head复审与集成最终完整检查，不用此前464项通过冒充新head全量结果。

项目/资源轻量浏览器所用4176 Vite已停止；依赖symlink仅本地测试使用，未纳入提交。实际npm完整/生产audit均exit0、0 vulnerabilities，lock未改。

## Integration review: operation without observation

The real custody contract permits an existing operation with `observation: null`. A new regression initially failed with `TypeError: Cannot read properties of null (reading state)` (2 passed, 1 failed; preserved in `evidence/null-observation-first-failure.txt`). The frontend type now matches that contract and renders UNKNOWN / observation not yet confirmed while retaining the original operation identity. The only action is to read the original records; it does not dispatch a replacement. The targeted run passes 3 tests. This deterministic contract regression does not substitute real backend browser acceptance.

## Actual integrated browser fixture plan

Run `scripts/accept_live_research_workbench.py` against the optional research deployment and a newly generated `af_test_` database. Browser requests use real application/core HTTP and real cookie/CSRF auth, with no Playwright interception. The only model substitute is the existing trusted Settings transport hook, returning controlled ChatCompletions from actual input/tool output. A registered local checksum tool creates an actual artifact; it is not a remote GPU or scientific autonomy test. A synthetic tool material and a personal model connection are explicit fixture prerequisites, not product startup seeds. Research setup/private draft/publication, project agreement/confirmation/start and reading are driven through the browser. Production-mode login uses the existing local HTTPS OIDC fixture, not an external identity provider. P7 team reading remains NOTDONE because that application endpoint is absent. Failures are preserved before fixes; only owned temporary databases/servers are cleaned up.

### Integrated browser first product failure

The real API browser reached explicit setup publication, exact-pin goal confirmation and native root admission on `30699a3`, then failed before its first owner-model transport call: `OwnerChatModel._body` rejected the workflow response format with `PERSONAL_MODEL_UNSUPPORTED_FORMAT`. The original root task was `failed`, with no experiment and no scientific decision. This is a product compatibility failure, not passed end-to-end acceptance. See [the safe first-failure report](evidence/real-browser-owner-model-first-failure.md) for completed actions, distinguishing diagnostic, preserved logs and cleanup. The original PG container was retained; a read-only catalog query confirmed zero generated `af_test_` databases after cleanup. Backend repair and remaining actual browser scenarios are still required.

The author completed the exact `09a2eae` Web check before integrated-browser work: **49 files / 466 tests passed, zero skips**, `npm run check` exit 0 (`/tmp/af-live-reviewed-full.log`), and explicit research build exit 0 (`/tmp/af-live-reviewed-research-build.log`). The later nullable-observation fix `14b2bc0` has three targeted passing tests and TypeScript exit 0; that does not claim the earlier full check ran on the new fix. The independent review document is imported unchanged and explicitly distinguishes reviewer inspection from author-run checks.

After the text-output fix, actual browser `81859a5` progressed into a completed native checksum child but the root still failed. A portable actual Agno/OwnerChatModel/wait-tool experiment identified `MODEL_PROTOCOL_TOOL`: Agno's local `external_execution` metadata was being forwarded to the provider codec. The [first-failure report](evidence/real-browser-owner-model-first-failure.md) records the two distinct blockers and the actual child outcomes. No full-browser pass or production-local/mobile pass is claimed.

仓库中的五份文本日志摘录仅规范化行尾空白，以通过whitespace检查；错误、断言、计数和结果未改，原始本地日志仍按前文路径保留。该文档编辑不代表新的测试运行。

### Native-tool repair: intermediate browser result and stricter terminal evidence

On `9ce15e4` (later `1e001c4` changes documentation only), the normal script exited 0 for development desktop and local-HTTPS-OIDC mobile: actual setup publication, owner-model/native child decision, evidence view, refresh/history, logout/relogin and Bob read/write denials ran; page/console errors were empty. However, post-run inspection found both captured round `terminal` fields were still null: the script stopped polling as soon as `decision` existed. This is insufficient to claim complete terminal-record acceptance. The original output remains `/tmp/af-live-real-browser-native-tools/evidence.json`; it is not presented as the final full journey result.

The fixture is strengthened to keep the same 45-second bound while waiting for both the actual decision and terminal record, then asserting the deterministic fixture's expected checksum, archived artifact and completed root/child identities. It now preserves complete experiment records as well as round records. This does not alter product timeouts or make any previous assertion weaker. A fresh actual API verification is required after the currently scheduled QA PostgreSQL run.

### Final actual API browser result after both repairs

**PASS: 2 complete scenarios, zero skips**, original 45-second terminal bound unchanged. Command `PYTHONPATH=applications:applications/tests:platform:platform/tests:platform/tests/browser:deployment:scripts python scripts/accept_live_research_workbench.py --database-url <authorized disposable loopback PG> --dist dist --output /tmp/af-live-real-browser-terminal --mode both` exited **0**; original log `/tmp/af-live-real-browser-terminal.log`. Product code is `9ce15e4c3a63ab44705d14ae6abcb5ba37616d62`; checkout `1e001c4` differs only in documentation. The research build was produced from `30699a3`; Git comparison confirms the frontend/lock/build configuration bytes are unchanged through the product code head. The test script's SHA and safe endpoint/status evidence are bound in [live-browser-terminal.json](evidence/live-browser-terminal.json).

- Development-selector Alice/Bob, 1487×1058: PASS.
- Production-mode **local synthetic HTTPS OIDC** Alice/Bob, 390×844: PASS; not an external identity-provider acceptance.
- Each new empty database: explicitly installed fixture checksum tool and personal model connection; browser creates project, saves agreement, prepares private configuration, explicitly publishes current native pin, selects its exact references, saves/explicitly confirms version 2, then explicitly starts.
- Each actual native root and its actual child is `completed`. The child output contains the expected computed checksum and an actual archived artifact. Each round has an actual terminal-record ID, an `agent_analysis` decision and source IDs; the controlled model's `met` is a fixture decision, not scientific validation.
- Actual evidence page, refresh, platform return, browser back/forward, logout/relogin preserving project, and separate Bob identity all ran. Bob's read and attempted write to Alice's project each returned 404; Bob's project list stayed empty.
- Both scenarios: **0 page errors, 0 unexpected console errors**. Known login-session 401s are classified separately. Saved network evidence contains only paths/statuses, never authorization query strings, headers or cookies.
- All generated databases were dropped; a post-run read-only catalog query found **0 `af_test_` databases**. Owned HTTPS servers and workers stopped. The pre-existing PG container and volume were retained; the PG slot was explicitly released to the QA author.

Screenshots were opened and visually inspected: [platform desktop](evidence/live-platform-desktop.png), [actual terminal evidence desktop](evidence/live-evidence-desktop.png), [platform mobile](evidence/live-platform-mobile.png), [actual terminal evidence mobile](evidence/live-evidence-mobile.png). The mobile screenshot captures a scrolling content viewport; complete identities/results remain available in the structured evidence.

Boundaries: no browser API interception; actual Store/native queue/custody, application HTTP, cookie/CSRF, owner model adapter and PostgreSQL. Only the provider HTTP transport and local deterministic compute tool are synthetic. The model connection was created through actual core HTTP fixture setup, **not** the model-settings browser form. P7 team reading/peer QA, final reproducible scientific package, real external production identity, paid/real model autonomy and actual remote GPU/capacity remain outside this run. The earlier two product failures, fixture failures and intermediate decision-only result remain recorded above; none is retroactively marked passed.
