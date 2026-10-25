"""Process-local synthetic external access-token issuer; no network or product hook."""
import json
import time
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from agent_factory.oidc_identity import OIDCIdentityConfig

ISSUER = 'https://factory-test-issuer.invalid'
AUDIENCE = 'factory-test-public-api'
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def identity_config(owners=()):
    key = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(_KEY.public_key()))
    key.update(kid='disposable-test-key', alg='RS256', use='sig')
    return OIDCIdentityConfig(issuer=ISSUER, audience=AUDIENCE, jwks={'keys': [key]},
        subject_owners={(ISSUER, owner): owner for owner in ('alice', 'bob', 'manager', 'manager2', 'fixture-editor', 'owned-user', 'fixture-owner', *owners)})


def access_token(owner):
    now = int(time.time())
    return jwt.encode({'iss': ISSUER, 'sub': owner, 'aud': AUDIENCE, 'iat': now,
        'exp': now + 300, 'jti': str(uuid4()), 'client_id': 'fixture-client'},
        _KEY, algorithm='RS256', headers={'kid': 'disposable-test-key', 'typ': 'at+jwt'})
