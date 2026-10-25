# Verification

基线f25c899；spec-first提交d2986e9。仅未来CI证据门槛，不改变旧run40191804720完整计数未核实的结论。

- 小型runner测试20项通过，0跳过；包含真实子进程执行CI内嵌校验脚本、exit0但缺回执、invalid JSON、提前stop、required skip、failure/error及optional class skip。无数据库/模型调用。
- ruff两个Python变更文件通过；workflow经PyYAML解析；git diff --check通过。
- 额外定向pyright检查触及仓库配置未包含的scripts/tests，报告4项既有类型问题（loader.errors类型两项、TextTestResult.successful_ids两项）；在未改check_postgres的独立worktree复现相同4项，未借此次修复扩大范围。不是新增错误，也不将该定向检查记为通过。
- 证据日志：`/tmp/af-research-next-evidence/ci-completion-portable-first.log`、`ci-completion-portable-final.log`、`ci-completion-pyright.log`、`ci-completion-pyright-baseline.log`。
- 未运行full/PG，未下载或绕过旧artifact，未推送。等待coordinator独立审查。
