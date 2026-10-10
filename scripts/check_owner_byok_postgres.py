"""Required owner BYOK/default-off acceptance. Only fake provider IO; reject skips."""
import json
import os
from pathlib import Path
import sys
import unittest


def main():
    if not os.environ.get('FACTORY_TEST_DATABASE_URL'):
        print('OWNER_BYOK_POSTGRES_REQUIRED', file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parents[1]
    sys.path[:0] = [str(root / 'platform/tests'), str(root / 'platform')]
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'test_billing_mode.BillingModeTests', 'test_byok_model.ByokModelTests',
        'test_personal_models_postgres.PersonalModelsPostgresTests',
        'test_application_environments.ApplicationEnvironmentTests',
        'test_application_environments_postgres.ApplicationEnvironmentPostgresTests',
        'test_owner_runtime_broker.OwnerRuntimeBrokerTests',
        'test_platform_openresearch_runtime.PlatformOpenResearchRuntimeTests',
        'test_platform_openresearch_custody.PlatformOpenResearchCustodyTests',
        'test_ssh_openresearch.SSHOpenResearchTests',
        'test_remote_bindings_postgres.RemoteBindingPostgresTests.test_effective_nonlocal_receiver_mapping_obeys_default_off_before_factory'])
    expected = 40
    if suite.countTestCases() != expected:
        print('OWNER_BYOK_POSTGRES_CASE_COUNT', file=sys.stderr)
        return 1
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    accepted = result.wasSuccessful() and not result.skipped and result.testsRun == expected
    print(json.dumps({'suite': 'owner_byok_default_off', 'testsRun': result.testsRun,
        'requiredCases': expected, 'skipped': len(result.skipped), 'accepted': accepted,
        'modelLive': False, 'externalRemoteVerified': False, 'realCredentialsUsed': False}))
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
