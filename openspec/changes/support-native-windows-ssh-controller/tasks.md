## 1. Design and prerequisites
- [x] 1.1 Independently review lease accounting/fresh authorization, fixed helper, explicit scope and packaging seams.
- [x] 1.2 Close Stage B's actual authentication failure with preserved first evidence; do not adopt an unvalidated carrier path.

## 2. Narrow production implementation
- [x] 2.1 Add the Windows lease/carrier and minimal owned-process contract, keeping Linux behavior unchanged.
- [x] 2.2 Integrate explicit pinned SSH scope at both consumers and the installed core helper/dependencies.
- [x] 2.3 Independently review exact full diff and fix unnecessary abstraction or unsafe shortcuts.

## 3. Verification
- [x] 3.1 Run portable scope/guard/limit/failure tests and actual Windows installed-core SSH checks.
- [x] 3.2 Verify Linux checks and standalone wheel behavior.
- [ ] 3.3 Run controlled Windows-to-Linux original submit/recovery/cancel. BLOCKED: no authorized Linux target/access supplied; the Windows-loopback peer does not satisfy this gate.


- [x] 3.4 Preserve first installed-core failure and independently review fixed safe phase/code instrumentation; run one authorized instrumented acceptance to distinguish acquisition, helper identity/handshake and command failure without changing the oracle.

当前回执：精确 `445a2ce` 的 Windows40247109502 三组（portable 60/60、独立安装两消费者及全部原断言）与 fast40247109535 成功，见 [安装证据](verification-installed.md)。此前四次 installed 失败保留；最终 full 仍待运行。3.3 保持 BLOCKED，不以 Windows loopback 代替。

- [x] 3.5 Independently review invocation-local fixed helper filename design against the observed NOT_FOUND/error-2 failure; implement only after review.
- [x] 3.6 Verify byte-preserving copy and identity/cleanup wiring, then run the unchanged actual installed Windows acceptance with Unicode-and-space parents; retain all failed reports and keep the Windows-to-Linux gate separate.

- [x] 3.7 Independently review and correct fixed known_hosts lookup under a space-containing child cwd; retain run40246732528 and require the unchanged actual Windows consumer/wrong-pin gates.

- [ ] 3.8 完成最终精确 head 的 fast/full、作者外文档增量复审及合并后 main 检查；现有 full 仅由 workflow_dispatch 触发。

## 4. 2026-10-26 independent audit corrections
- [x] 4.1 非作者审查精确 spec commit，保留历史结果及 POSIX 旧缺陷归属。
- [x] 4.2 先记录失败回归，再修正共同 deadline、仅密文残留的失败范围与有界 slot；保留真正不确定清理的全局关闭。
- [x] 4.3 共用固定 SSH argv，修复 POSIX 空格/引号路径，验证原 agent/identity/host pin 与父 cwd。
- [x] 4.4 候选 Stage B 改按需；核对默认产品 oracle、历史 Stage A 独有范围与手动入口均保留。
- [ ] 4.5 完成适用检查、非作者完整基线→head与增量简洁性复审；主代理确认后记录实际 Windows CI，未运行项保持未验证。

## 5. Full acceptance import correction
- [ ] 5.1 非作者审查此精简平台导入修正；保留 full40272188443 两项原失败并先复现相同断言，再限定 Windows API 导入、运行两项原回归与相关 portable/static 检查，完成完整 `62614177`→head 及增量复审；新 Windows 专项和组合 full 由主代理核验，旧失败不改写为 PASS。
