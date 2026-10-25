# Tasks

## 1. Contract and review
- [ ] 1.1 coordinator审最小控件/路由与真实API映射；复核add-research-assistant-qa接口，不扩展后端/视觉方案。

## 2. Owner setup and directed QA
- [ ] 2.1 接个人助手读取/显式创建、QA草稿/发布与CAS操作额度配置，真实连接选择和未计量说明；新项目使用researchAssistantId，保留旧endpoint字段。
- [ ] 2.2 接分页目录、单对象私密提问/原message读取、真实delivery/reply/输入依据；复用原命令恢复，不建历史/答案状态机。
- [ ] 2.3 接现composition参数、资源/平台往返、深链/刷新和窄屏焦点；重读及owner切换清除旧正文，来源不可用隐藏完整派生回答。

## 3. Verification and independent review
- [ ] 3.1 确定性测试A02/A03/A05：GET零写、draft不publish、原请求408/remount/peer配置更换不换键、写成功后读失败不重发、revision冲突、source_unavailable及owner切换清空、输入依据不冒称引用、token/费用不伪计量。
- [ ] 3.2 B01/B02实际双用户浏览器：平台→设置→发布→有限额度→Bob离线→Alice私问→原reply/依据→资源往返/深链重登；撤来源后整段隐藏。真实core/API/PG，模型传输可合成但不得宣称C03或真实GPU通过；PG与coordinator串行预约。
- [ ] 3.3 运行适用Web/架构/audit检查，保留首失败；作者之外完整base/head精简review、整改复审和精确CI由coordinator验收。主动关联/真实团队质量另按后续P7，不勾为本单元已完成。
