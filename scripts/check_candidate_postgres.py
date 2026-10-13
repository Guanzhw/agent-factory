"""Focused compatibility entrypoint; requirements live in postgres_requirements."""
from check_postgres import main as run_postgres_checks


def main():
    return run_postgres_checks(['--group', 'research_candidate_postgres'])


if __name__ == '__main__':
    raise SystemExit(main())
