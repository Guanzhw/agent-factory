"""Explicit research deployment; the default core composition stays app-free."""
from agent_factory.config import Settings
from research.public import install
from .application_composition import ApplicationAssembly
from .main import create_app as create_deployment


def create_app(settings=None):
    return create_deployment(settings, applications=(ApplicationAssembly(name='research', install=install),))


def main():
    import uvicorn
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, access_log=False)


if __name__ == '__main__':
    main()
