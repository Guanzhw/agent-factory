"""Serve the existing Factory UI with trusted AutoResearch operator settings.

An operator module is Python configuration, not an uploaded user document. Its
build_settings() returns Settings with reviewed presets and exact application
references. This command never publishes materials or acquires credentials.
"""
import argparse
import importlib
import re

from agent_factory.config import Settings
from agent_factory.main import create_app


def configured(module_name):
    if not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*(?:\.[A-Za-z_][A-Za-z_0-9]*)*', module_name):
        raise ValueError('AUTORESEARCH_OPERATOR_MODULE_INVALID')
    settings = importlib.import_module(module_name).build_settings()
    if (type(settings) is not Settings or settings.host != '127.0.0.1'
            or settings.runtime_tool_contract != 'autoresearch-session-v1'
            or settings.max_workers != 1 or not settings.autoresearch_presets):
        raise ValueError('AUTORESEARCH_OPERATOR_SETTINGS_INVALID')
    return settings


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--operator-module', required=True)
    parser.add_argument('--check', action='store_true', help='Validate configuration without starting a database or model')
    args = parser.parse_args(argv)
    try:
        settings = configured(args.operator_module)
        if args.check:
            import json
            print(json.dumps({'configured': True, 'presets': [
                {'id': p.id, 'ready': not p.unavailable(), 'blockers': p.unavailable()}
                for p in settings.autoresearch_presets.values()]}, ensure_ascii=False))
            return 0
        import uvicorn
        uvicorn.run(create_app(settings), host='127.0.0.1', port=settings.port, access_log=False)
        return 0
    except Exception:
        # Operator modules may touch private connection routes; never echo errors.
        print('AUTORESEARCH_OPERATOR_START_FAILED')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
