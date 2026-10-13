export type ModelProtocol = 'chat-completions' | 'responses';
export const MODEL_PROTOCOLS: readonly ModelProtocol[] = ['chat-completions', 'responses'];
export interface ModelProviderPreset {
  id: string;
  label: string;
  provider: 'openai-compatible';
  baseURL: string;
  model: string;
  protocol: ModelProtocol;
}

export const LEGACY_GO_BASE = 'https://opencode.ai/zen/go/v1';
export const GO_BASE = 'https://opencode.ai/inference/go/v1';
export const GO_BASES: readonly string[] = [LEGACY_GO_BASE, GO_BASE];
export const MODEL_PROVIDER_PRESETS: readonly ModelProviderPreset[] = [
  { id: 'gpt-6-luna-responses', label: 'GPT-6 Luna · Responses', provider: 'openai-compatible', baseURL: GO_BASE, model: 'gpt-6-luna', protocol: 'responses' },
  { id: 'deepseek-flash-chat-completions', label: 'DeepSeek Flash · Chat Completions', provider: 'openai-compatible', baseURL: GO_BASE, model: 'deepseek-flash', protocol: 'chat-completions' },
];

export function validModelProtocol(value: unknown): value is ModelProtocol {
  return value === 'chat-completions' || value === 'responses';
}

/** Historical opt-in is valid only for the original Go/Longcat configuration. */
export function validThinkingMetadata(value: { baseURL: string; model: string; protocol?: unknown; thinkingMode?: unknown }): boolean {
  return !Object.prototype.hasOwnProperty.call(value, 'thinkingMode')
    || value.thinkingMode === 'disabled' && value.baseURL === LEGACY_GO_BASE
      && value.model === 'longcat-2.5-preview-free' && (value.protocol ?? 'chat-completions') === 'chat-completions';
}
