"""Model-visible output previews; full receipts remain available for recovery.

Codex truncation uses an approximate four UTF-8 bytes per token and retains
both ends. This is presentation, never proof that an operation failed.
"""
DEFAULT_OUTPUT_TOKENS = 10000


def output_preview(text: str, budget: int = DEFAULT_OUTPUT_TOKENS * 4) -> str:
    raw = text.encode()
    if len(raw) <= budget:
        return text
    left, right = budget // 2, budget - budget // 2
    prefix = raw[:left].decode('utf-8', errors='ignore')
    suffix = raw[-right:].decode('utf-8', errors='ignore') if right else ''
    return prefix + f'\n…{(len(raw) - budget + 3) // 4} tokens truncated…\n' + suffix
