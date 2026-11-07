> Current status: the standalone Go development campaigns and private runtime broker are retired and removed. Personal models, including Go endpoints, use the normal owner model connection and Agno loop. Historical limits, runners and broker behavior below are not current configuration. HTTPX now supplies model transport directly.

# OpenCode model presets

The current UI presets are defined in [`web/modelProviderConfig.ts`](../web/modelProviderConfig.ts). They configure the owner-model path, not a separate execution engine.

| Preset | Provider | Base URL | Model | Protocol |
| --- | --- | --- | --- | --- |
| DeepSeek V4.1 Flash | `openai-compatible` | `https://opencode.ai/inference/go/openai/v1` | `deepseek-v4.1-flash` | `chat-completions` |
| GPT-6 Luna | `openai-compatible` | `https://opencode.ai/inference/go/openai/v1` | `gpt-6-luna` | `responses` |

The UI saves a selected preset through the existing personal-model API. The credential belongs to the member and is stored through the credential service. Selecting a preset does not create a provider account, obtain a subscription, or verify every model capability.

## Execution and billing

Agno owns the conversation and tool loop. The owner model adapter sends requests through the selected protocol. [Model protocols](MODEL_PROTOCOLS.md) documents request lifetimes, cancellation, and compatibility. [Owner BYOK](owner-byok-api.md) describes the API and billing boundary.

Factory billing is disabled by default. External usage remains subject to the member's provider account. A subscription label or a model response does not prove that provider-side charges are zero.

A local Windows acceptance has executed a synthetic CPU research task through the DeepSeek V4.1 Flash preset and produced reproducible files. That result does not certify GPT-6 Luna, all provider features, or complete deployment readiness. The relevant PR records the exact runtime and outstanding checks.

## Earlier endpoints and adapter records

`https://opencode.ai/zen/go/v1` remains a legacy configuration value. It is not the base URL selected by the current presets. The older isolated adapter, model aliases, small response limits, and one-off authorization records are preserved in [the historical isolated-stage record](history/opencode-go-isolated-stage.md). Those settings do not constrain ordinary current owner-model sessions.
