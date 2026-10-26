# Tasks

## 1. 方案与报告

- [ ] 1.1 作者之外审查方案与精确 base/head，记录简洁性结论后才实施。
- [ ] 1.2 删除两份 MCP 轨迹、更新固定历史链接和必要失败事实；核对 Git 对象内容和链接，保留未闭环结论。
- [ ] 1.3 浏览器总报告及生成器只写子报告索引；验证两个路径均能读取、子报告和截图与基线一致。

## 2. 测试夹具

- [ ] 2.1 storage 诊断改为显式 `FACTORY_STORAGE_DIAGNOSTIC=1` 并写明命令；原测试在默认和开启模式各运行一次，检查证据输出及资源清理，保留失败结果。
- [ ] 2.2 删除重复材料初始化和 `member_headers` unused 参数；更新全部调用方，运行既有 fixture lifecycle、department publication 与相关静态检查。

## 3. 集成与审查

- [ ] 3.1 核验完整 diff 仅含批准范围，运行 `ruff`、`pyright`、OpenSpec strict 与适用 CI；记录结果、精确 head 和未验证项，交作者之外完整 diff 简洁性复审并整改。

## Workflow follow-up

- 独立 Draft PR 发布；最终核验和合并由协调者按既有授权执行，不混入 PR138。
