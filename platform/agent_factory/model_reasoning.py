"""Verified effort choices for the endpoint/protocol combinations we expose."""


def reasoning_efforts(configuration):
    base = configuration['baseURL'].rstrip('/')
    model = configuration['model']
    protocol = configuration.get('protocol', 'chat-completions')
    # https://models.dev/api.json, opencode-go, retrieved 2026-11-08.
    if base == 'https://opencode.ai/inference/go/openai/v1':
        if model == 'gpt-6-luna' and protocol == 'responses':
            return ['none', 'low', 'medium', 'high', 'xhigh', 'max']
        if model == 'deepseek-v4.1-flash' and protocol == 'chat-completions':
            return ['low', 'high', 'max']
    # https://developers.openai.com/api/docs/models/gpt-6-luna
    if base == 'https://api.openai.com/v1' and model == 'gpt-6-luna':
        return ['none', 'low', 'medium', 'high', 'xhigh', 'max'] if protocol == 'responses' else ['none']
    # https://api-docs.deepseek.com/api/create-chat-completion/
    if (base in {'https://api.deepseek.com', 'https://api.deepseek.com/v1'}
            and model in {'deepseek-flash', 'deepseek-v4-pro'} and protocol == 'chat-completions'):
        return ['none', 'low', 'high', 'max']
    return []
