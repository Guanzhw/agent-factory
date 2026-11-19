"""Account administration over Agno's persistent user directory."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator

from .auth import ACCOUNT_ADMIN_ROLE, AuthService


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


class MemberCreate(AccountCreate):
    password: SecretStr = Field(min_length=1)


class PasswordReset(BaseModel):
    password: SecretStr = Field(min_length=1)


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


def account_router(auth: AuthService, passwords) -> APIRouter:
    router = APIRouter(prefix="/api/factory/accounts", tags=["Accounts"])

    def actor(request: Request) -> str:
        user_id = auth.user(request)["id"]
        auth.require_account_admin(user_id)
        return user_id

    def project(row: dict, roles) -> dict:
        return {"id": row["id"], "name": row.get("name") or row["id"], "email": row.get("email"),
                "disabled": row["disabled"],
                "accountAdmin": ACCOUNT_ADMIN_ROLE in roles}

    def set_admin(user_id: str, admin: bool) -> None:
        if admin:
            auth.account_roles.assign(user_id, ACCOUNT_ADMIN_ROLE)
        else:
            auth.account_roles.unassign(user_id, ACCOUNT_ADMIN_ROLE)

    @router.get("")
    def list_accounts(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 50,
                      offset: Annotated[int, Query(ge=0)] = 0):
        actor(request)
        rows = auth.directory.list(limit=limit, offset=offset)
        ids = [row['id'] for row in rows]
        roles = auth.account_roles.roles_of_many(ids)
        return {"accounts": [project(row, roles.get(row['id'], [])) for row in rows],
                "total": auth.directory.count()}

    @router.post("", status_code=201)
    def create_account(body: MemberCreate, request: Request):
        operator = actor(request)
        try:
            row = passwords.create_member(body.id, body.password.get_secret_value(), name=body.name,
                email=body.email, actor=operator, admin=body.accountAdmin)
        except ValueError:
            raise HTTPException(409, "成员标识已存在，请使用其他标识。") from None
        return project(row, auth.account_roles.roles_of(body.id))

    @router.put("/{user_id}/password")
    def reset_password(user_id: str, body: PasswordReset, request: Request):
        actor(request)
        try:
            passwords.reset(user_id, body.password.get_secret_value())
        except ValueError:
            raise HTTPException(404, "未找到成员账号。") from None
        return {"updated": True}

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
        return project(row, auth.account_roles.roles_of(row["id"]))

    return router
