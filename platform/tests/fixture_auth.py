"""Synthetic test subjects and short-lived bearer tokens, never an HTTP login mode."""
from agent_factory.auth import ACCOUNT_ADMIN_ROLE, ACCOUNT_MIGRATION_KEY
from fixture_identity import access_token
from httpx import URL
import time
import jwt


def initialize_members(auth):
    for owner in ('manager', 'alice', 'bob'):
        if auth.directory.get(owner) is None:
            auth.directory.upsert(owner, name=owner.title(), metadata={ACCOUNT_MIGRATION_KEY: True})
            if owner == 'manager':
                auth.account_roles.assign(owner, ACCOUNT_ADMIN_ROLE)


def member_headers(auth, owner):
    return {'Authorization': 'Bearer ' + access_token(owner)}


def authorize_client(client, owner, auth=None):
    if auth is None:
        app = client.app
        while not hasattr(getattr(app, 'state', None), 'factory'):
            app = app.app
        auth = app.state.factory['auth']
    initialize_members(auth)
    client.base_url = URL(str(client.base_url).replace('http://', 'https://', 1))
    client.headers.update(member_headers(auth, owner))
    return client.get('/api/factory/session')


def internal_headers(key, owner):
    """Only for tests that explicitly serve the native internal execution boundary."""
    now = int(time.time())
    token = jwt.encode({'sub': owner, 'aud': 'agent-factory', 'iat': now, 'exp': now + 3600},
        key, algorithm='HS256')
    return {'Authorization': 'Bearer ' + token}
