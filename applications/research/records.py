"""Curated research snapshots; core content sharing remains the authorization owner."""
from agent_factory.application_content import ContentPublication, ContentSource


class ResearchRecords:
    def __init__(self, content):
        self.content = content

    def start(self, owner, project_id, goal_version, experiment_id, attempt_id, agreement):
        publication = ContentPublication(source=ContentSource(application='research', record=experiment_id, revision='start'),
            content={'kind': 'research.experiment.start', 'state': 'pending_admission',
                'projectId': project_id, 'goalVersion': goal_version,
                'experimentId': experiment_id, 'attemptId': attempt_id,
                'objective': agreement.objective, 'conditions': {
                    'evaluation': agreement.evaluation, 'stopConditions': agreement.stopConditions}},
            visibility='team')
        return self.content.publish(owner, publication, 'research-start-record:' + attempt_id)['id']
