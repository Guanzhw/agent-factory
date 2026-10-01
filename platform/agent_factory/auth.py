"""Native Agno managed authorization and the explicitly enabled demo identity seam."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextvars import Context
from http.cookies import CookieError, SimpleCookie
import secrets
from typing import Any
from urllib.parse import urlsplit

from agno.os.authz import Authorization, AuthorizationContext, UserDirectory
from agno.os.authz.native_engine import NativePolicyEngine
from fastapi import HTTPException, Request
import jwt
from starlette.responses import JSONResponse

DEMO_COOKIE = "factory_demo_session"
EXECUTOR_ID = "factory-executor"
AUDIENCE = "agent-factory"
_PERSONAS = {"manager": ("Manager", "factory-manager"), "alice": ("Alice", "factory-user"), "bob": ("Bob", "factory-user")}
_PUBLIC_PATHS = ["/", "/assets/*", "/favicon.ico", "/api/status", "/api/health",
                 "/api/factory/status", "/api/factory/demo/login"]


class AuthService:
    """Rights come from the current native SQL policy, never a model or JWT role claim."""

    def __init__(self, settings: Any, native_db: Any):
        self.settings = settings
        self.native_db = native_db
        configured: Any = getattr(settings, "jwt_key", None)
        if hasattr(configured, "get_secret_value"):
            configured = configured.get_secret_value()
        if not configured:
            if not settings.demo:
                raise ValueError("Production requires an operator-configured JWT signing key")
            configured = secrets.token_urlsafe(48)
        if not isinstance(configured, str) or len(configured.encode()) < 32:
            raise ValueError("JWT signing key must contain at least 32 bytes")
        self._key = configured
        self.audience = getattr(settings, "jwt_audience", AUDIENCE)
        self.directory = UserDirectory(db=native_db, fail_closed=True, auto_provision=False)
        # Supplying the native engine keeps production on managed roles even before
        # an operator has provisioned any users; no scope-only fallback is possible.
        self.authorization = Authorization(
            db=native_db, engine=NativePolicyEngine(db=native_db),
            verification_keys=[self._key], algorithm="HS256", verify_audience=True,
            audience=self.audience, trust_token_scopes=False, audit=True,
            excluded_route_paths=_PUBLIC_PATHS,
        )

    def initialize_demo(self) -> None:
        if not self.settings.demo:
            return
        # Native subjects and roles share a namespace; a persona named manager
        # must not collide with a role slug named manager.
        self.authorization.define_role("factory-manager", ["agent_os:admin"])
        self.authorization.define_role("factory-user", [
            f"agents:{EXECUTOR_ID}:read", f"agents:{EXECUTOR_ID}:run",
            "components:read", "registry:read", "sessions:read", "filesystem:read",
        ])
        for user_id, (name, role) in _PERSONAS.items():
            # Do not restore assignments or disabled flags removed by an operator.
            if self.directory.get(user_id) is None:
                self.directory.upsert(user_id, name=name)
                self.authorization.assign(user_id, role)

    def agentos_kwargs(self) -> dict[str, Any]:
        return {"authorization": self.authorization, "user_directory": self.directory,
                "user_isolation": True}

    def _current_user(self, user_id: str) -> dict[str, Any]:
        if not isinstance(user_id, str) or not user_id or user_id.startswith("__"):
            raise HTTPException(401, "A verified user identity is required")
        try:
            user = self.directory.get(user_id)
        except Exception as error:
            raise HTTPException(503, "User directory is unavailable") from error
        if user is None or user.get("disabled"):
            raise HTTPException(403, "User is unavailable or disabled")
        return user

    def user(self, request: Request) -> dict[str, Any]:
        if not getattr(request.state, "authenticated", False) or not getattr(request.state, "_agno_auth_complete", False):
            raise HTTPException(401, "Authentication required")
        user_id = getattr(request.state, "user_id", None)
        if not isinstance(user_id, str):
            raise HTTPException(401, "A verified user identity is required")
        return self.identity(user_id)

    def identity(self, user_id: str) -> dict[str, Any]:
        """Trusted verified/whitelisted identity projection; grants remain current."""
        # No user/name/role information is taken from form values or JWT claims.
        current = self._current_user(user_id)
        try:
            roles = Context().run(self.authorization.roles_of, user_id)
        except Exception as error:
            raise HTTPException(503, "Authorization store is unavailable") from error
        # Product labels follow CURRENT managed capabilities, including an
        # operator's custom author role; they never grant permission themselves.
        role = None
        if roles:
            try:
                self.require(user_id, "components:write")
            except HTTPException as error:
                if error.status_code != 403:
                    raise
                role = "user"
            else:
                role = "manager"
        return {"id": user_id, "name": current.get("name") or user_id, "role": role}

    def require(self, user_id: str, action: str = "run", resource: str = "agents",
                resource_id: str | None = EXECUTOR_ID) -> None:
        """Recheck at admission AND immediately before actual tool/effect execution."""
        self._current_user(user_id)
        if ":" in action:
            parts = action.split(":")
            if len(parts) == 2:
                resource, action = parts
                resource_id = None
            elif len(parts) == 3:
                resource, resource_id, action = parts
            else:
                raise ValueError("Permission must be resource:action or resource:id:action")
        if resource != "agents" and resource_id == EXECUTOR_ID:
            resource_id = None
        context = AuthorizationContext(principal_id=user_id, resource_type=resource,
                                       resource_id=resource_id, action=action, scopes=[], claims={})
        try:
            provider = self.authorization.provider
            # A tool can execute after an earlier check in the same async context.
            # Discard request-local native policy memoization at this boundary;
            # the native provider then reads CURRENT SQL grants again.
            if isinstance(provider, list):
                raise RuntimeError("Unexpected collection of authorization providers")
            allowed = provider is not None and Context().run(provider.check, context)
        except Exception as error:
            raise HTTPException(503, "Authorization store is unavailable") from error
        if not allowed:
            raise HTTPException(403, "Current permissions deny this action")

    def _issue_native_token(self, user_id: str, *, lifetime_seconds: int = 300) -> str:
        """Trusted in-process bridge only; never a public arbitrary-subject endpoint."""
        self._current_user(user_id)
        now = datetime.now(timezone.utc)
        return jwt.encode({"sub": user_id, "aud": self.audience, "iat": now,
                           "exp": now + timedelta(seconds=lifetime_seconds)}, self._key, algorithm="HS256")

    def issue_demo_token(self, persona: str) -> str:
        if not self.settings.demo:
            raise HTTPException(404, "Demo login is disabled")
        if persona not in _PERSONAS:
            raise HTTPException(400, "Unknown demo persona")
        # A user whose grant was revoked can still sign in, but has no restored rights.
        return self._issue_native_token(persona, lifetime_seconds=3600)


class CookieBridge:
    """Pure ASGI outer wrapper: native middleware verifies the demo cookie's JWT."""

    def __init__(self, app: Any, settings: Any):
        self.app, self.settings = app, settings

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and self.settings.demo:
            headers = list(scope.get("headers", []))
            if not any(name.lower() == b"authorization" for name, _ in headers):
                cookies = SimpleCookie()
                try:
                    for name, value in headers:
                        if name.lower() == b"cookie":
                            cookies.load(value.decode("latin-1"))
                except CookieError:
                    cookies.clear()
                if DEMO_COOKIE in cookies:
                    token = cookies[DEMO_COOKIE].value
                    # SameSite=Strict belongs on the issuing response too. This guard
                    # also rejects explicit cross-origin mutating cookie requests.
                    origins = [value.decode("latin-1") for name, value in headers if name.lower() == b"origin"]
                    hosts = [value.decode("latin-1") for name, value in headers if name.lower() == b"host"]
                    if scope.get("method") not in {"GET", "HEAD", "OPTIONS"} and origins:
                        if len(origins) != 1 or len(hosts) != 1 or urlsplit(origins[0]).netloc != hosts[0]:
                            await JSONResponse({"detail": "Cross-origin demo session request denied"}, status_code=403)(scope, receive, send)
                            return
                    if token.isascii() and "\r" not in token and "\n" not in token:
                        headers.append((b"authorization", f"Bearer {token}".encode("ascii")))
                        scope = {**scope, "headers": headers}
        await self.app(scope, receive, send)
