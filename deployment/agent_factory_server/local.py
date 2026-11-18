"""Resumable loopback setup against a PostgreSQL database supplied by the operator."""
from datetime import UTC, datetime, timedelta
from getpass import getpass
from ipaddress import ip_address
import os
from pathlib import Path
import secrets
import ssl
from tempfile import NamedTemporaryFile

from sqlalchemy import create_engine, inspect, text

from agent_factory.config import Settings


def new_private_file(path, data):
    # Another launcher or an interrupted write must never replace a working key.
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        try:
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary.close()
            try:
                os.link(temporary.name, path)
            except FileExistsError:
                pass
        finally:
            temporary.close()
            Path(temporary.name).unlink(missing_ok=True)


def local_certificate(path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    if not path.exists():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'localhost')])
        now = datetime.now(UTC)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=365))
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip_address('127.0.0.1'))]), False)
                .sign(key, hashes.SHA256()))
        new_private_file(path, cert.public_bytes(serialization.Encoding.PEM) + key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    cert = x509.load_pem_x509_certificate(path.read_bytes())
    public = path.with_suffix('.crt')
    new_private_file(public, cert.public_bytes(serialization.Encoding.PEM))
    if public.read_bytes() != cert.public_bytes(serialization.Encoding.PEM):
        raise ValueError('已有公开证书与服务证书不匹配，请核对证书配置。')
    print(f'首次连接请在浏览器信任公开证书 {public}，SHA-256 {cert.fingerprint(hashes.SHA256()).hex()}。')
    return str(path), str(path)


def main():
    import uvicorn
    from agno.db.postgres import PostgresDb
    from agno.os.authz import UserDirectory
    from agno.os.authz.native_engine import NativePolicyEngine
    from agent_factory.auth import ACCOUNT_ADMIN_ROLE
    from agent_factory.local_login import LocalPasswords
    from .research import create_app
    workspace = Path(os.environ.get('FACTORY_WORKSPACE', '.local')).resolve()
    workspace.mkdir(mode=0o700, parents=True, exist_ok=True)
    url = os.environ.get('FACTORY_DATABASE_URL') or getpass('输入专用 PostgreSQL 连接地址（隐藏）：')
    if not url.startswith('postgresql'):
        raise SystemExit('请提供 PostgreSQL 地址，可通过 FACTORY_DATABASE_URL 或交互输入。')
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
            existing = inspect(conn).has_table('af_browser_auth')
    except Exception:
        engine.dispose()
        raise SystemExit('无法连接 PostgreSQL，请核对数据库、账号和端口后再次运行。') from None
    origin = 'https://127.0.0.1:' + os.environ.get('FACTORY_PORT', '3100')
    try:
        if os.environ.get('FACTORY_LOCAL_LOGIN_ORIGIN', origin) != origin:
            raise SystemExit('本地向导仅绑定 127.0.0.1。团队已有域名请使用部署指南中的 HTTPS 启动方式。')
        key = os.environ.get('FACTORY_JWT_KEY')
        if not key:
            keyfile = workspace / 'local-login.key'
            if not keyfile.exists():
                if existing:
                    raise SystemExit('已有部署，请提供原 FACTORY_JWT_KEY 或指定原工作目录。')
                new_private_file(keyfile, secrets.token_urlsafe(48).encode())
            key = keyfile.read_text().strip()
        settings = Settings(db_url=url, jwt_key=key, workspace=workspace, local_login_origin=origin,
                            port=int(origin.rsplit(':', 1)[1]))
        cert, private = os.getenv('FACTORY_TLS_CERT'), os.getenv('FACTORY_TLS_KEY')
        if not cert and not private:
            cert, private = local_certificate(workspace / 'loopback.pem')
        if not cert or not private:
            raise SystemExit('请同时设置 FACTORY_TLS_CERT 和 FACTORY_TLS_KEY。')
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, private)
        database = PostgresDb(db_engine=engine, id='factory-native-postgres')
        directory = UserDirectory(db=database, fail_closed=True, auto_provision=False)
        if not directory.ids():
            owner = input('新库首位本地成员兼任账号管理员。输入成员 ID：').strip()
            password = getpass('本地密码：')
            if password != getpass('再次输入密码：'):
                raise SystemExit('两次密码不一致，请重新启动向导。')
            LocalPasswords(engine, directory).create(owner, password)
            NativePolicyEngine(db=database).assign(owner, ACCOUNT_ADMIN_ROLE)
    finally:
        engine.dispose()
    print('服务就绪后打开 ' + origin, flush=True)
    uvicorn.run(create_app(settings), host='127.0.0.1', port=settings.port, ssl_certfile=cert,
                ssl_keyfile=private, timeout_graceful_shutdown=35, access_log=False)
