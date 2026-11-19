"""Account administration over Agno's persistent user directory."""
from __future__ import annotations

import json
import time
from typing import Annotated

from agno.db.schemas.authz import AUTHZ_GROUPING, AUTHZ_USERS
from agno.os.authz._request_scope import invalidate
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator

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


class MemberCreate(AccountCreate):
    password: SecretStr | None = Field(default=None, min_length=1)


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


def create_directory_member(engine, directory, owner, *, name=None, email=None, actor=None, admin=False,
                            first_member=False, persist_password=None):
    # Agno's directory and role methods commit independently. Keep all records for a new member together.
    database = directory._db
    users = database._get_table(AUTHZ_USERS, create_table_if_not_found=True)
    roles = database._get_table(AUTHZ_GROUPING, create_table_if_not_found=True) if admin else None
    stamp = int(time.time())
    row = dict(id=owner, name=name or owner, email=email, disabled=False, created_at=stamp, updated_at=stamp)
    metadata = {ACCOUNT_MIGRATION_KEY: True}
    with engine.begin() as conn:
        if conn.dialect.name == 'sqlite':
            conn.exec_driver_sql('BEGIN IMMEDIATE')
        else:
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_local_passwords_create'))"))
        if first_member and conn.execute(select(users.c.id).limit(1)).first():
            raise ValueError('首位成员已创建，请使用已有账号登录。')
        created = conn.execute(insert(users).values(**row, user_metadata=json.dumps(metadata))
                               .on_conflict_do_nothing(index_elements=[users.c.id]).returning(users.c.id)).scalar()
        if created is None:
            raise ValueError('Account already exists; local identity was not attached')
        if persist_password is not None:
            persist_password(conn)
        if roles is not None:
            conn.execute(insert(roles).values(subject=owner, role=ACCOUNT_ADMIN_ROLE).on_conflict_do_nothing())
    if admin:
        invalidate()
    row['metadata'] = metadata
    directory._emit('user.created', owner, None, [directory._summary(row)], actor)
    return row


def account_router(auth: AuthService, passwords=None) -> APIRouter:
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
        local = passwords.local_owners(ids) if passwords else set()
        return {"accounts": [{**project(row, roles.get(row['id'], [])), "localLogin": row['id'] in local} for row in rows],
                "localLoginEnabled": passwords is not None,
                "total": auth.directory.count()}

    @router.post("", status_code=201)
    def create_account(body: MemberCreate, request: Request):
        operator = actor(request)
        if passwords is None and body.password is not None:
            raise HTTPException(409, "此部署未启用本地密码登录。")
        try:
            if passwords is None:
                row = create_directory_member(auth.native_db.db_engine, auth.directory, body.id, name=body.name,
                    email=body.email, actor=operator, admin=body.accountAdmin)
            else:
                row = passwords.create_member(body.id, body.password.get_secret_value() if body.password else None,
                    name=body.name, email=body.email, actor=operator, admin=body.accountAdmin)
        except ValueError:
            raise HTTPException(409, "成员标识已存在，请使用其他标识。" if passwords else "Account already exists") from None
        return project(row, auth.account_roles.roles_of(body.id))

    @router.put("/{user_id}/password")
    def reset_password(user_id: str, body: PasswordReset, request: Request):
        actor(request)
        if passwords is None:
            raise HTTPException(409, "此部署未启用本地密码登录。")
        try:
            passwords.reset(user_id, body.password.get_secret_value())
        except ValueError:
            raise HTTPException(409, "仅已有本地密码的成员可以重置密码。") from None
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
