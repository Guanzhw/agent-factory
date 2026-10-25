# Verification — 2026-10-24

独立分支基线b50d196（#97 965350f+原planning）；不含#99 graph。重型全部root串行，公开/合成loopback，无真实模型/provider账户。

- wire/bindings worker24portable通过2.679s，含11新v2场景；SQLite advisory锁函数为fixture，不作PG并发证据。
- root remote-v2-authority-transport：9通过11.574s（driver16.762s）；原v1真实loopback拒绝/size/timeout与v2schema测试。最终authority5测试通过，补真实transport方法mock _post的版本/预算保留；不伪装网络acceptance。
- 独立review发现继承后v1scope字段顺序变化，已恢复capabilities/tools/budget/usageGrantSha256顺序，固定断言。未发现其它新阻断。
- Web mounted targetflow15通过：缺省v1、显式v1、v2拒绝/支持、声明撤回/目标消失不自动切local。首轮跨worktree工具路径无法解析react，0tests；共享完全一致lock的node_modules后使用项目原config15通过，无项目配置或依赖变更。
- remote-v2-first-process：原中立v2真实两服务/独立PG/Agno队列case通过（driver26.233s）。含非空configSchema/config/inputSchema/inputValues，adapter接收原值及operationSeconds7/depth0，plan摘要、receipt/native原身份和UTF8 checksum产物准确字节。
- remote-v2-recovery-process：2项92.016s，lostprepare/dispatchack+receiverexit41/restart/并发重复dispatch通过；cancel失败于25s等待原生终态，controlled工具只await shield而没有观察协作取消，独立work最终30s bound报错。原日志完整保留，不延长期限。
- 修正上述fixture：原生await轮询原run持久cancel，抛既有RunCancelledException；独立work保持原effect UNKNOWN，不取消它，30s上限和release后allStopped保留。remote-v2-cancel-cooperative单项通过24.053s（29.795driver），断言原native终态但effect未停止时仍held/UNKNOWN，GET无写，release后原CANCELLED结果。
- frozen uv sync成功（同lock）；Pyright零错误（34.063s）、当前ownedRuff与diffcheck通过。后续workerfixture和测试最终修改需最终门禁。

证据/workspace/scratch/task-history-20261024/remote-v2-*.{log,json}；每个json记录命令/cwd/UTC/exitCode。完整Web、构建后浏览器、原v1 PG回归、最终CI未完成，不据便携/单例绿灯声明全部完成。#97基线full有4失败，隔离修复中；本分支未声称继承的稳定性问题已关闭。

最终本地补验：原v1 target discovery与lostreply/disabledowner/UNKNOWN-before-delivery三项PG通过30.123s（34.576driver），不新增派发。npm run check exit0，712 tests通过，lint/types/build完成41.340s；production/full audit0。实际built Chromium两场景通过14.170sdriver；首轮Playwright对disabled option的to_be_disabled误报enabled（DOM已含disabled），改为option原生disabled JS属性断言后通过，product未改。API仅合成GET，禁止外网/写/WS，证据remote-v2-browser-option-state/results.json及screenshots，不当真实receiver网络验收。

基线已合并#97修复88aacb7（a7bdd07 merge），没有#99 graph。原#97full失败记录保留，其修复原科学targeted已通过；此合并不是full成功。新增v2便携module进入daily selection；最终精确CI等待提交。

最终架构733模块/0违规/0gaps；selection全3287、dailyPython272、PG59均有效。最终Pyright/Ruff通过。保留本地node_modules到一致lock依赖的symlink，未提交该环境路径。
