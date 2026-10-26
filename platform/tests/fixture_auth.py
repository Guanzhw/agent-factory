"""Synthetic test subjects and short-lived bearer tokens, never an HTTP login mode."""
from agent_factory.auth import ACCOUNT_ADMIN_ROLE, ACCOUNT_MIGRATION_KEY
from fixture_identity import access_token
import time
import jwt


def initialize_members(auth):
    for owner in ('manager', 'alice', 'bob'):
        if auth.directory.get(owner) is None:
            auth.directory.upsert(owner, name=owner.title(), metadata={ACCOUNT_MIGRATION_KEY: True})
            if owner == 'manager':
                auth.account_roles.assign(owner, ACCOUNT_ADMIN_ROLE)


def member_headers(owner):
    return {'Authorization': 'Bearer ' + access_token(owner)}


def authorize_client(client, owner, auth=None):
    if auth is None:
        app = client.app
        while not hasattr(getattr(app, 'state', None), 'factory'):
            app = app.app
        auth = app.state.factory['auth']
    initialize_members(auth)
    client.base_url = str(client.base_url).replace('http://', 'https://', 1)
    client.headers.update(member_headers(owner))
    return client.get('/api/factory/session')


def internal_headers(key, owner):
    """Only for tests that explicitly serve the native internal execution boundary."""
    now = int(time.time())
    token = jwt.encode({'sub': owner, 'aud': 'agent-factory', 'iat': now, 'exp': now + 3600},
        key, algorithm='HS256')
    return {'Authorization': 'Bearer ' + token}


def disabled_member_request(test, state, client, method, path, *, owner='alice', **kwargs):
    """Assert external rejection, then exercise the native current-member guard."""
    from fastapi.testclient import TestClient
    headers = kwargs.pop('headers', {}) | member_headers(owner)
    external = client.request(method, path, headers=headers, **kwargs)
    test.assertEqual(external.status_code, 401, external.text)
    test.assertEqual(external.json(), {'detail': 'OIDC_ACCESS_TOKEN_INVALID'})
    native = TestClient(state['http_app'], base_url='http://internal-test')
    try:
        response = native.request(method, path,
            headers=internal_headers(state['auth'].settings.jwt_key, owner), **kwargs)
        test.assertEqual(response.status_code, 403, response.text)
        return response
    finally:
        native.close()
