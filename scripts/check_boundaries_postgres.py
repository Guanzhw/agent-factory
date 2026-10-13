"""Focused compatibility entrypoint; requirements live in postgres_requirements."""
from check_postgres import main as run_postgres_checks


def main():
    return run_postgres_checks(['--group', 'platform_application_boundaries'])


if __name__ == '__main__':
    raise SystemExit(main())
