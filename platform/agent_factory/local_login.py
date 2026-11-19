"""Explicit local passwords for native members; no public account creation."""
from __future__ import annotations

import argparse
import getpass
import json
import secrets
import sys
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects.postgresql import insert

from .accounts import AccountCreate
from .auth import ACCOUNT_ADMIN_ROLE, ACCOUNT_MIGRATION_KEY


class LocalPasswords:
    def __init__(self, engine, directory):
        self.engine, self.directory = engine, directory
        self.hasher = PasswordHasher()
        self._dummy = self.hasher.hash(secrets.token_urlsafe(32))
        with engine.begin() as conn:
            conn.execute(text('CREATE TABLE IF NOT EXISTS af_local_passwords '
                              '(owner TEXT PRIMARY KEY,password_hash TEXT NOT NULL)'))

    @staticmethod
    def _password(value):
        if not isinstance(value, str) or not value:
            raise ValueError('Password must not be empty')

    def reset(self, owner, password):
        AccountCreate(id=owner)
        self._password(password)
        encoded = self.hasher.hash(password)
        with self.engine.begin() as conn:
            if conn.dialect.name == 'postgresql':
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_browser_auth'))"))
            changed = conn.execute(text('UPDATE af_local_passwords SET password_hash=:hash WHERE owner=:owner'),
                                   {'owner': owner, 'hash': encoded})
            if not changed.rowcount:
                raise ValueError('Only existing local passwords can be reset')
            if inspect(conn).has_table('af_browser_auth'):
                conn.execute(text("DELETE FROM af_browser_auth WHERE kind='session' AND body->>'owner'=:owner "
                                  "AND body->>'expires' IS NULL"), {'owner': owner})

    def local_owners(self, owners):
        from sqlalchemy import bindparam
        with self.engine.connect() as conn:
            return set(conn.execute(text('SELECT owner FROM af_local_passwords WHERE owner IN :owners')
                .bindparams(bindparam('owners', expanding=True)), {'owners': owners}).scalars())

    def create(self, owner, password, *, name=None, email=None, actor=None):
        self._password(password)
        return self.create_member(owner, password, name=name, email=email, actor=actor)

    def create_member(self, owner, password, *, name=None, email=None, actor=None, first_member=False, admin=False):
        from agno.db.schemas.authz import AUTHZ_GROUPING, AUTHZ_USERS

        AccountCreate(id=owner)
        if password is not None:
            self._password(password)
        encoded = self.hasher.hash(password) if password is not None else None
        # Agno's user and role methods commit separately. Use its tables in the credential transaction.
        database = self.directory._db
        users = database._get_table(AUTHZ_USERS, create_table_if_not_found=True)
        roles = database._get_table(AUTHZ_GROUPING, create_table_if_not_found=True) if admin else None
        stamp = int(time.time())
        row = dict(id=owner, name=name or owner, email=email, disabled=False, created_at=stamp, updated_at=stamp)
        metadata = {ACCOUNT_MIGRATION_KEY: True}
        with self.engine.begin() as conn:
            if conn.dialect.name == 'sqlite':
                conn.exec_driver_sql('BEGIN IMMEDIATE')
            else:
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_local_passwords_create'))"))
            if first_member and conn.execute(select(users.c.id).limit(1)).first():
                raise ValueError('首位成员已创建，请使用已有账号登录。')
            if conn.execute(text('SELECT 1 FROM af_local_passwords WHERE owner=:owner'), {'owner': owner}).first():
                raise ValueError('Account already exists; local identity was not attached')
            created = conn.execute(insert(users).values(**row, user_metadata=json.dumps(metadata))
                                   .on_conflict_do_nothing(index_elements=[users.c.id]).returning(users.c.id)).scalar()
            if created is None:
                raise ValueError('Account already exists; local identity was not attached')
            if encoded is not None:
                conn.execute(text('INSERT INTO af_local_passwords(owner,password_hash) VALUES(:owner,:hash)'),
                             {'owner': owner, 'hash': encoded})
            if roles is not None:
                conn.execute(insert(roles).values(subject=owner, role=ACCOUNT_ADMIN_ROLE).on_conflict_do_nothing())
        row['metadata'] = metadata
        self.directory._emit('user.created', owner, None, [self.directory._summary(row)], actor)
        return row

    @staticmethod
    def current_hash(conn, owner):
        return conn.execute(text('SELECT password_hash FROM af_local_passwords WHERE owner=:owner'),
                            {'owner': owner}).scalar_one_or_none()

    def verified_hash(self, owner, password):
        try:
            AccountCreate(id=owner)
            self._password(password)
        except ValueError:
            raise HTTPException(401, 'LOCAL_LOGIN_REJECTED') from None
        with self.engine.connect() as conn:
            encoded = self.current_hash(conn, owner)
        try:
            self.hasher.verify(encoded or self._dummy, password)
        except (VerificationError, InvalidHashError):
            raise HTTPException(401, 'LOCAL_LOGIN_REJECTED') from None
        if encoded is None:
            raise HTTPException(401, 'LOCAL_LOGIN_REJECTED')
        return encoded

    def verify(self, owner, password):
        self.verified_hash(owner, password)
        return owner


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create a new ordinary local account while the service is stopped.')
    parser.add_argument('username')
    parser.add_argument('--reset', action='store_true', help='Reset an existing local password')
    args = parser.parse_args(argv)
    engine = None
    try:
        password = getpass.getpass('Password: ')
        if password != getpass.getpass('Confirm password: '):
            raise ValueError('Passwords differ')
        from agno.db.postgres import PostgresDb
        from agno.os.authz import UserDirectory
        from .config import Settings
        settings = Settings.from_env()
        engine = create_engine(settings.db_url)
        database = PostgresDb(db_engine=engine, id='factory-native-postgres')
        directory = UserDirectory(db=database, fail_closed=True, auto_provision=False)
        passwords = LocalPasswords(database.db_engine, directory)
        if args.reset:
            passwords.reset(args.username, password)
        else:
            passwords.create(args.username, password)
    except (Exception, KeyboardInterrupt):
        print('Local account operation failed. Check the account and password confirmation before retrying.', file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print('Local password reset.' if args.reset else 'Local account created.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
