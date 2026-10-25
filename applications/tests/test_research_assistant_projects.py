"""Old endpoint semantics and rows survive the independent assistant relationship."""
from unittest.mock import Mock

from fastapi import HTTPException
from sqlalchemy import text

from research.projects import CreateProject, ResearchProjects
import test_applications_composition as fixtures


class ResearchAssistantProjectsTests(fixtures.ApplicationCompositionFixture):
    def test_old_row_migration_and_new_owned_relationship(self):
        with self.store.engine.begin() as conn:
            conn.execute(text('CREATE TABLE research_projects (id VARCHAR PRIMARY KEY, owner_id VARCHAR NOT NULL, '
                'title VARCHAR NOT NULL, assistant_id VARCHAR, state VARCHAR NOT NULL, goal_version INTEGER NOT NULL, '
                'ending JSON, created_at VARCHAR NOT NULL)'))
            conn.execute(text("INSERT INTO research_projects VALUES ('old','alice','Old project','original-endpoint','draft',0,NULL,'original-time')"))
        endpoints, assistants = Mock(), Mock()
        service = ResearchProjects(self.store, self.auth, endpoints, assistants=assistants)
        old = service.read('alice', 'old')
        self.assertEqual(old['assistantId'], 'original-endpoint')
        self.assertIsNone(old['researchAssistantId'])
        new = service.create('alice', CreateProject(requestId='new-relationship', title='New', researchAssistantId='stable-alice'))
        assistants.owned.assert_called_once_with('alice', 'stable-alice')
        self.assertEqual(new['researchAssistantId'], 'stable-alice')
        assistants.owned.side_effect = HTTPException(404, 'not owned')
        with self.assertRaises(HTTPException):
            service.create('bob', CreateProject(requestId='cross-owner-assistant', title='Foreign', researchAssistantId='stable-alice'))
        reopened = ResearchProjects(self.store, self.auth, endpoints, assistants=assistants)
        self.assertEqual(reopened.read('alice', 'old'), old)
        self.assertEqual(reopened.read('alice', new['id']), new)
