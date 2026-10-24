"""Owner endpoint normalization and provider-specific headers/options."""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import urlsplit

from .personal_remote_provider import origin

# Retained verbatim for stored configurations and scoped legacy proxy grants.
GO_BASE = 'https://opencode.ai/zen/go/v1'
GO_CURRENT_BASE = 'https://opencode.ai/inference/go/v1'
ADDITIONAL_BASE_URLS = (GO_CURRENT_BASE, GO_BASE)
CLIENT_USER_AGENT = 'agent-factory/0.2 (+https://github.com/Guanzhw/agent-factory)'


def base_url(value):
    """Normalize the owner's HTTP(S) model base, including custom API paths."""
    try:
        if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
            raise ValueError()
        parsed = urlsplit(value)
        if parsed.query or parsed.fragment or any(c in value for c in '? #\\'):
            raise ValueError()
        destination = origin(f'{parsed.scheme}://{parsed.netloc}')
        path = parsed.path.rstrip('/')
        if any(part in {'.', '..'} for part in path.split('/')):
            raise ValueError()
        return destination + path
    except (ValueError, TypeError, AttributeError):
        raise ValueError('PERSONAL_MODEL_DESTINATION_DENIED') from None


def model_origin(value):
    parsed = urlsplit(base_url(value))
    return origin(f'{parsed.scheme}://{parsed.netloc}')


def continuation_scope(configuration, owner=None):
    """Bind non-secret protocol history to the exact authorized model snapshot."""
    fields = ('ownerId', 'reference', 'revision', 'credentialRef', 'credentialRevision',
        'provider', 'model', 'baseURL', 'thinkingMode')
    binding = {field: configuration.get(field) for field in fields}
    binding['ownerId'] = owner if owner is not None else binding['ownerId']
    binding['protocol'] = configuration.get('protocol', 'chat-completions')
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def model_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}', value):
        raise ValueError('PERSONAL_MODEL_ID_INVALID')
    return value


def requires_session(base):
    return base_url(base) in ADDITIONAL_BASE_URLS


def chat_headers(base, lease, session_id):
    """Compatibility name: headers are independent of CC versus Responses."""
    headers = {'Accept-Encoding': 'identity'}
    if lease is not None:
        headers['Authorization'] = 'Bearer ' + lease.password
    if requires_session(base):
        if (type(session_id) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}', session_id)
                or lease is not None and session_id == lease.password):
            raise ValueError('PERSONAL_MODEL_SESSION_REQUIRED')
        headers.update({'User-Agent': CLIENT_USER_AGENT, 'x-opencode-session': session_id})
    return headers


def generation_options(configuration):
    """Read the existing scoped option without rewriting historical records.

    No new default or model selection is introduced. Future provider extensions
    belong here and cannot override protocol, model, messages, auth or routing.
    """
    mode = configuration.get('thinkingMode')
    if mode is None or mode == 'default':
        return {}
    if (mode != 'disabled' or configuration.get('baseURL') != GO_BASE
            or configuration.get('model') != 'longcat-2.5-preview-free'
            or configuration.get('protocol', 'chat-completions') != 'chat-completions'):
        raise ValueError('PERSONAL_MODEL_THINKING_MODE_UNSUPPORTED')
    return {'thinking': {'type': 'disabled'}}
