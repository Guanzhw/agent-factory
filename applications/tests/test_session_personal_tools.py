"""Configured CLI/MCP resources reach the default research plan."""
import sys

from agent_factory.personal_tools import PersonalTools, ConfigureResourceRequest
import test_research_session_setup as fixture


class SessionPersonalToolsTests(fixture.OptionalSessionToolsTests):
    def test_configured_cli_and_mcp_are_bound_without_an_extra_application_setup(self):
        service = PersonalTools(self.connections, None, ())
        self.store.personal_tools = self.connections.personal_tools = service
        service.register(self.store.execution_bindings)
        cli = service.configure_resource('alice', ConfigureResourceRequest(
            transport='cli', toolName='local_lookup', executable=sys.executable,
            arguments=['-c', 'print("ok")'], outputFormat='text', requestId='configure-local'))
        mcp = service.configure_resource('alice', ConfigureResourceRequest(
            transport='mcp', toolName='remote_lookup', remoteToolName='lookup',
            url='http://localhost:8001/mcp', requestId='configure-mcp'))
        service.configure_resource('bob', ConfigureResourceRequest(
            transport='cli', toolName='bob_private', executable=sys.executable,
            arguments=['-c', 'print("private")'], outputFormat='text', requestId='configure-bob'))
        result = self.setup.prepare('alice', self.model['connectionRef'], self.limits)
        app = self.store.applications.require_current(result['applicationRef'])
        mode = app['modes']['autonomous']
        self.assertIn('local_lookup', mode['toolOrder'])
        self.assertIn('remote_lookup', mode['toolOrder'])
        self.assertNotIn('bob_private', mode['toolOrder'])
        self.assertIn(cli['registrationRef'], result['connectionRefs'].values())
        self.assertIn(mcp['registrationRef'], result['connectionRefs'].values())
        service.revoke('alice', cli['registrationRef'], 'revoke-cli')
        updated = self.setup.prepare('alice', self.model['connectionRef'], self.limits)
        self.assertNotEqual(updated['applicationRef'], result['applicationRef'])
        self.assertNotIn(cli['registrationRef'], updated['connectionRefs'].values())
