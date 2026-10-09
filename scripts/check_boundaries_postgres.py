"""Required platform/application-boundary PostgreSQL checks; skips cannot pass."""
import json
import os
from pathlib import Path
import sys
import unittest


def main():
    if not os.environ.get('FACTORY_TEST_DATABASE_URL'):
        print('BOUNDARIES_POSTGRES_REQUIRED', file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'platform/tests'), str(root / 'platform')]
    names = [
        'test_application_contract_v2.NeutralChecksumNativeTests.test_neutral_checksum_native_artifact',
        'test_personal_remote_postgres.PersonalRemotePostgresTests.test_actual_http_auth_scope_bind_restart_and_native_grant_revocation',
        'test_openresearch_workspace_postgres.WorkspacePostgresTests',
        'test_credential_vault_postgres.CredentialVaultPostgresTests',
        'test_credential_vault_wiring_postgres.CredentialVaultWiringPostgresTests',
        'test_managed_workspace_postgres.ManagedWorkspacePostgresTests',
        'test_managed_orx_attachment_postgres.ManagedORXPostgresTests',
        'test_personal_command_postgres.PersonalCommandPostgresTests',
        'test_personal_orx_postgres.PersonalOrxPostgresTests',
        'test_personal_orx_projects_postgres.OrxProjectPostgresTests',
        'test_lifecycle_observer_postgres.LifecycleObserverPostgresTests.test_13_terminal_orx_without_stop_proof_holds_every_capacity_projection',
        'test_remote_authority.OriginAuthorityPostgresTests.test_actual_current_owner_connection_revocation_denies_without_resolving_or_constructing_provider',
    ]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    expected = 16
    if suite.countTestCases() != expected:
        print('BOUNDARIES_POSTGRES_CASE_COUNT', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    accepted = result.wasSuccessful() and not result.skipped and result.testsRun == expected
    print(json.dumps({'suite': 'platform_application_boundaries', 'testsRun': result.testsRun,
        'skipped': len(result.skipped), 'requiredCases': expected, 'accepted': accepted,
        'modelLive': False, 'externalRemoteVerified': False, 'openResearchEndToEndVerified': False}))
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
