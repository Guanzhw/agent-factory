"""Explicit local passwords for native members; no public account creation."""
from __future__ import annotations

import argparse
import getpass
import secrets
import sys
import warnings

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from .accounts import AccountCreate
from .auth import ACCOUNT_MIGRATION_KEY


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
        if not isinstance(value, str) or not 12 <= len(value) <= 128:
            raise ValueError('Password must contain 12–128 characters')

    def create(self, owner, password):
        AccountCreate(id=owner)
        self._password(password)
        encoded = self.hasher.hash(password)
        with self.engine.connect() as conn:
            if conn.dialect.name == 'sqlite':
                conn.exec_driver_sql('BEGIN IMMEDIATE')
            else:
                conn.begin()
                conn.execute(text("SELECT pg_advisory_xact_lock(hashtext('af_local_passwords_create'))"))
            try:
                exists = conn.execute(text('SELECT 1 FROM af_local_passwords WHERE owner=:owner'), {'owner': owner}).first()
                if exists or self.directory.get(owner) is not None:
                    raise ValueError('Account already exists; local identity was not attached')
                self.directory.upsert(owner, name=owner, metadata={ACCOUNT_MIGRATION_KEY: True})
                conn.execute(text('INSERT INTO af_local_passwords(owner,password_hash) VALUES(:owner,:hash)'),
                             {'owner': owner, 'hash': encoded})
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def verify(self, owner, password):
        try:
            AccountCreate(id=owner)
            self._password(password)
        except ValueError:
            raise HTTPException(401, 'LOCAL_LOGIN_REJECTED') from None
        with self.engine.connect() as conn:
            encoded = conn.execute(text('SELECT password_hash FROM af_local_passwords WHERE owner=:owner'),
                                   {'owner': owner}).scalar_one_or_none()
        try:
            self.hasher.verify(encoded or self._dummy, password)
        except (VerificationError, InvalidHashError):
            raise HTTPException(401, 'LOCAL_LOGIN_REJECTED') from None
        if encoded is None:
            raise HTTPException(401, 'LOCAL_LOGIN_REJECTED')
        return owner


def main(argv=None):
    parser = argparse.ArgumentParser(description='Create a new ordinary local account while the service is stopped.')
    parser.add_argument('username')
    args = parser.parse_args(argv)
    engine = None
    try:
        if not sys.stdin.isatty():
            raise ValueError('A private interactive terminal is required')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('Password: ')
            confirmation = getpass.getpass('Confirm password: ')
        if password != confirmation:
            raise ValueError('Passwords differ')
        from agno.db.postgres import PostgresDb
        from agno.os.authz import UserDirectory
        from .config import Settings
        from .store import require_production_database
        settings = Settings.from_env()
        engine = create_engine(settings.db_url)
        require_production_database(engine)
        database = PostgresDb(db_engine=engine, id='factory-native-postgres')
        directory = UserDirectory(db=database, fail_closed=True, auto_provision=False)
        LocalPasswords(database.db_engine, directory).create(args.username, password)
    except (Exception, KeyboardInterrupt):
        print('Local account creation did not complete normally. Check the account before retrying; existing accounts are never changed.', file=sys.stderr)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
    print('Local account created.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
