"""Native Agno identity for a trusted team; administrators manage accounts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from contextvars import Context
import json
from typing import Any

from agno.os.authz import Authorization, AuthorizationContext, UserDirectory
from agno.os.authz.native_engine import NativePolicyEngine
from agno.os.authz.provider import AuthorizationProvider
from agno.os.service_accounts import TOKEN_PREFIX as SERVICE_ACCOUNT_TOKEN_PREFIX
from fastapi import HTTPException, Request
import jwt
from starlette.responses import JSONResponse

EXECUTOR_ID = "factory-executor"
AUDIENCE = "agent-factory"
ACCOUNT_ADMIN_ROLE = "factory-manager"
ACCOUNT_MIGRATION_KEY = "factory_account_admin_v1"
_NATIVE_ACCOUNT_RESOURCES = {"agent_os", "authz", "users", "service_accounts"}
_PUBLIC_PATHS = ["/", "/assets/*", "/favicon.ico", "/api/status", "/api/health",
                 "/api/factory/status", "/api/factory/auth/config"]


class TrustedTeamProvider(AuthorizationProvider):
    """All active accounts share ordinary capabilities, with native isolation intact."""

    def __init__(self, directory: UserDirectory):
        self.directory = directory

    def _member(self, principal_id: str | None) -> bool:
        if not principal_id:
            return False
        current = self.directory.get(principal_id)
        return current is not None and not current.get("disabled")

    def check(self, ctx: AuthorizationContext) -> bool:
        # Agno asks this special question when deciding whether to drop user
        # isolation. Account administrators never acquire that global bypass.
        if ctx.resource_type == "config" and ctx.action == "write":
            return False
        return ctx.resource_type not in _NATIVE_ACCOUNT_RESOURCES | {"*"} and self._member(ctx.principal_id)

    def accessible_resource_ids(self, ctx: AuthorizationContext) -> set[str]:
        return {"*"} if self.check(ctx) else set()

    def authorize_route(self, ctx: AuthorizationContext, required_scopes: list[str]) -> bool:
        # Native account/policy APIs have broader authority than the account UI.
        # They remain closed; the small account router owns account management.
        # Agno maps database schema up/down migrations to config:write.
        if any(scope == "config:write" or scope.split(":", 1)[0] in _NATIVE_ACCOUNT_RESOURCES
               for scope in required_scopes):
            return False
        return self.check(ctx)


class MemberTokenBoundary:
    """Keep native service-account tokens outside this directory-member product.

    Agno PATs use a separate scope-based identity plane and bypass the configured
    provider and the owner's disabled flag. The factory accepts member JWTs from
    its identity bridges, so persisted PATs cannot acquire a second authority path.
    """

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in {"http", "websocket"}:
            for name, value in scope.get("headers", []):
                if name.lower() != b"authorization":
                    continue
                credential = value.decode("latin-1")
                # Mirror Agno's header extraction, which accepts raw tokens too.
                token = credential[7:].strip() if credential.lower().startswith("bearer ") else credential.strip()
                if token.startswith(SERVICE_ACCOUNT_TOKEN_PREFIX):
                    if scope["type"] == "websocket":
                        await send({"type": "websocket.close", "code": 1008})
                    else:
                        await JSONResponse({"detail": "A member identity token is required"}, status_code=401)(scope, receive, send)
                    return
        if scope["type"] == "websocket":
            async def member_receive():
                message = await receive()
                if message["type"] == "websocket.receive" and message.get("text"):
                    try:
                        frame = json.loads(message["text"])
                    except json.JSONDecodeError:
                        return message
                    # Native workflows authenticate through JSON frames rather
                    # than HTTP headers, including identity changes mid-socket.
                    if isinstance(frame, dict) and frame.get("action") == "authenticate":
                        token = frame.get("token")
                        if isinstance(token, str) and token.startswith(SERVICE_ACCOUNT_TOKEN_PREFIX):
                            await send({"type": "websocket.close", "code": 1008})
                            return {"type": "websocket.disconnect", "code": 1008}
                return message
            await self.app(scope, member_receive, send)
        else:
            await self.app(scope, receive, send)


class UnconfiguredIdentityBoundary:
    """Keep internal member tokens off the public app when no IdP is configured."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] == "http" and any(name.lower() == b"authorization" for name, _ in scope.get("headers", [])):
            await JSONResponse({"detail": "AUTHENTICATION_NOT_CONFIGURED"}, status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)


class AuthService:
    """The native user directory owns membership and the account disabled flag."""

    def __init__(self, settings: Any, native_db: Any):
        self.settings = settings
        self.native_db = native_db
        configured: Any = getattr(settings, "jwt_key", None)
        if hasattr(configured, "get_secret_value"):
            configured = configured.get_secret_value()
        if not isinstance(configured, str) or len(configured.encode()) < 32:
            raise ValueError("JWT signing key must contain at least 32 bytes")
        self._key = configured
        self.audience = getattr(settings, "jwt_audience", AUDIENCE)
        self.directory = UserDirectory(db=native_db, fail_closed=True, auto_provision=False)
        # Preserve existing administrator assignments, using native persistence
        # only as the account-admin flag. Resource grants no longer gate members.
        self.account_roles = NativePolicyEngine(db=native_db)
        self._migrate_account_admins()
        self.authorization = Authorization(
            db=native_db, authorization_provider=TrustedTeamProvider(self.directory),
            verification_keys=[self._key], algorithm="HS256", verify_audience=True,
            audience=self.audience, trust_token_scopes=False, audit=True,
            excluded_route_paths=_PUBLIC_PATHS,
        )

    def _migrate_account_admins(self) -> None:
        """Interpret former global administrators once, retaining native accounts.

        Each native directory row carries a completion marker. Subsequent role
        demotion remains effective even while historical resource policies exist.
        No account's disabled flag or unrelated metadata is changed.
        """
        with self.native_db.db_engine.begin() as conn:
            if conn.dialect.name == "postgresql":
                from sqlalchemy import text
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('factory-account-admin-v1'))"))
            for user_id in self.directory.ids():
                current = self.directory.get(user_id)
                assert current is not None
                metadata = dict(current.get("metadata") or {})
                if metadata.get(ACCOUNT_MIGRATION_KEY) is True:
                    continue
                roles = self.account_roles.roles_of(user_id)
                if ACCOUNT_ADMIN_ROLE not in roles and self.account_roles.check_scope("agent_os:admin", subject=user_id):
                    self.account_roles.assign(user_id, ACCOUNT_ADMIN_ROLE)
                metadata[ACCOUNT_MIGRATION_KEY] = True
                self.directory.upsert(user_id, metadata=metadata)

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
        # A stale tab may share a newly changed browser cookie. This hint only
        # narrows the verified principal; it cannot select or authorize a user.
        expected = request.headers.get("x-factory-expected-owner")
        if expected is not None and expected != user_id:
            raise HTTPException(403, {"code": "EXPECTED_OWNER_MISMATCH", "message": "Account changed"})
        return self.identity(user_id)

    def identity(self, user_id: str) -> dict[str, Any]:
        """Project current membership and the account-admin flag."""
        # No user/name/role information is taken from form values or JWT claims.
        current = self._current_user(user_id)
        try:
            roles = Context().run(self.account_roles.roles_of, user_id)
        except Exception as error:
            raise HTTPException(503, "Authorization store is unavailable") from error
        role = "manager" if ACCOUNT_ADMIN_ROLE in roles else "user"
        return {"id": user_id, "name": current.get("name") or user_id, "role": role}

    def require_member(self, user_id: str) -> None:
        """Recheck the account at admission and immediately before execution."""
        self._current_user(user_id)

    def require_account_admin(self, user_id: str) -> None:
        self.require_member(user_id)
        try:
            roles = Context().run(self.account_roles.roles_of, user_id)
        except Exception as error:
            raise HTTPException(503, "Account authority is unavailable") from error
        if ACCOUNT_ADMIN_ROLE not in roles:
            raise HTTPException(403, "Account administrator required")

    def _issue_native_token(self, user_id: str, *, lifetime_seconds: int = 300) -> str:
        """Trusted in-process bridge only; never a public arbitrary-subject endpoint."""
        self._current_user(user_id)
        now = datetime.now(timezone.utc)
        return jwt.encode({"sub": user_id, "aud": self.audience, "iat": now,
                           "exp": now + timedelta(seconds=lifetime_seconds)}, self._key, algorithm="HS256")
