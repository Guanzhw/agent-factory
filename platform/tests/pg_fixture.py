"""Class-scoped disposable databases; never clean a supplied database's tables."""
from uuid import uuid4
import re
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


class IsolatedPostgres:
    def __init__(self, base_url):
        self.base = make_url(base_url)
        if self.base.host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("PostgreSQL acceptance fixtures require an authorized loopback server")
        self.name = "af_test_" + uuid4().hex
        self.url = self.base.set(database=self.name).render_as_string(hide_password=False)
        self.admin = None

    def __enter__(self):
        self.admin = create_engine(self.base, isolation_level="AUTOCOMMIT")
        with self.admin.connect() as conn:
            conn.execute(text('CREATE DATABASE "' + self.name + '"'))
        return self

    def __exit__(self, *args):
        if not re.fullmatch(r"af_test_[a-f0-9]{32}", self.name) or self.name == self.base.database:
            raise ValueError("Refusing cleanup outside this generated fixture database")
        try:
            with self.admin.connect() as conn:
                conn.execute(text('DROP DATABASE IF EXISTS "' + self.name + '" WITH (FORCE)'))
        finally:
            self.admin.dispose()
