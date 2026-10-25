## Why
Agno 3.1 对无可执行函数的未知工具响应仍可能继续模型轮次；tool_call_limit 不能限制此路径。只读问答即使声明 tools=[] 仍可能被模型恶意 train 调用带入无界循环。

## What Changes
OwnerChatModel 在每次响应边界拒绝不属于该次请求声明集合的工具名。无工具请求收到任何工具调用立即安全失败，无下一轮。

## Capabilities
### New Capabilities
- `owner-model-tool-authority`: 模型响应工具调用受原请求声明约束。

## Impact
基线 4956857；仅 byok_model 和专属便携测试，不修改 Agno、应用或既有等待逻辑。
