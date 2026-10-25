"""Curated research snapshots; core content sharing remains the authorization owner."""
from agent_factory.application_content import ContentPublication, ContentSource
from contextlib import nullcontext


class ResearchRecords:
    def __init__(self, content, associations=None):
        self.content = content
        self.associations = associations

    def event_write(self):
        return self.associations.events.db.write() if self.associations else nullcontext()

    def start(self, owner, project_id, goal_version, experiment_id, attempt_id, agreement):
        publication = ContentPublication(source=ContentSource(application='research', record=experiment_id, revision='start'),
            content={'kind': 'research.experiment.start', 'state': 'pending_admission',
                'projectId': project_id, 'goalVersion': goal_version,
                'experimentId': experiment_id, 'attemptId': attempt_id,
                'objective': agreement.objective, 'conditions': {
                    'evaluation': agreement.evaluation, 'stopConditions': agreement.stopConditions}},
            visibility='team')
        identifier = self.content.publish(owner, publication, 'research-start-record:' + attempt_id)['id']
        if self.associations:
            with self.content.db.read() as conn:
                self.associations.prepare(conn, owner, identifier)
        return identifier
