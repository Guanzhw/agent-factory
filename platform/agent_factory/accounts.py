"""Account administration over Agno's persistent user directory."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator

from .auth import ACCOUNT_ADMIN_ROLE, ACCOUNT_MIGRATION_KEY, AuthService


class AccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}$")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=1, max_length=254)
    accountAdmin: StrictBool = False

    @field_validator("id")
    @classmethod
    def user_namespace(cls, value: str) -> str:
        if value in {ACCOUNT_ADMIN_ROLE, "factory-user"}:
            raise ValueError("Account id is reserved")
        return value


class AccountUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=1, max_length=254)
    disabled: StrictBool | None = None
    accountAdmin: StrictBool | None = None

    @field_validator("name", "email", "disabled", "accountAdmin")
    @classmethod
    def explicit_values(cls, value):
        if value is None:
            raise ValueError("Updated fields require an explicit value")
        return value


def account_router(auth: AuthService) -> APIRouter:
    router = APIRouter(prefix="/api/factory/accounts", tags=["Accounts"])

    def actor(request: Request) -> str:
        user_id = auth.user(request)["id"]
        auth.require_account_admin(user_id)
        return user_id

    def project(row: dict) -> dict:
        return {"id": row["id"], "name": row.get("name") or row["id"], "email": row.get("email"),
                "disabled": row["disabled"],
                "accountAdmin": ACCOUNT_ADMIN_ROLE in auth.account_roles.roles_of(row["id"])}

    def set_admin(user_id: str, admin: bool) -> None:
        if admin:
            auth.account_roles.assign(user_id, ACCOUNT_ADMIN_ROLE)
        else:
            auth.account_roles.unassign(user_id, ACCOUNT_ADMIN_ROLE)

    @router.get("")
    def list_accounts(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                      offset: Annotated[int, Query(ge=0)] = 0):
        actor(request)
        return {"accounts": [project(row) for row in auth.directory.list(limit=limit, offset=offset)],
                "total": auth.directory.count()}

    @router.post("", status_code=201)
    def create_account(body: AccountCreate, request: Request):
        operator = actor(request)
        if auth.directory.get(body.id) is not None:
            raise HTTPException(409, "Account already exists")
        row = auth.directory.upsert(body.id, name=body.name, email=body.email,
                                    metadata={ACCOUNT_MIGRATION_KEY: True}, actor=operator)
        if body.accountAdmin:
            set_admin(body.id, True)
        return project(row)

    @router.patch("/{user_id}")
    def update_account(user_id: str, body: AccountUpdate, request: Request):
        operator = actor(request)
        row = auth.directory.get(user_id)
        if row is None:
            raise HTTPException(404, "Account not found")
        fields = body.model_fields_set
        if fields & {"name", "email"}:
            row = auth.directory.upsert(user_id, name=body.name, email=body.email, actor=operator)
        if "accountAdmin" in fields:
            set_admin(user_id, bool(body.accountAdmin))
        if "disabled" in fields:
            row = auth.directory.set_disabled(user_id, bool(body.disabled), actor=operator)
        return project(row)

    return router
