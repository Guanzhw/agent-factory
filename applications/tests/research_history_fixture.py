"""Explicit persisted pre-upgrade intent; never a product admission path."""
from uuid import uuid4

from agent_factory.application_interface import ApplicationStart
from agent_factory.application_runs import factory_request_id
from agent_factory.store import digest, now


def seed_legacy_intent(runs, owner, project_id, command, agreement):
    execution = agreement.execution
    assert execution is not None
    scope_id, experiment_id, attempt_id = (str(uuid4()) for _ in range(3))
    request = ApplicationStart(requestId='research:' + attempt_id,
        application=execution.applicationRef.id, applicationRef=execution.applicationRef.model_dump(),
        mode=execution.mode, goal=agreement.execution_goal(),
        inputValues=runs._input_values(execution, agreement.execution_goal()),
        materialChoices={key: value.model_dump() for key, value in execution.materialChoices.items()},
        connectionRefs=execution.connectionRefs)
    commitment = {'budget': agreement.budget.model_dump(), 'deadline': execution.deadline}
    with runs.projects.db.store.transaction() as conn:
        runs.scopes.admission_lock(conn)
        with runs.projects.db.write(), runs.records.content.db.write(), runs.records.event_write():
            runs.scopes.create_scope(owner, scope_id, digest(commitment), commitment['budget'], execution.deadline)
            conn.execute(runs.commitments.insert().values(project_id=project_id, scope_id=scope_id, commitment=commitment))
            runs.scopes.allocate(conn, owner, scope_id, attempt_id, digest(request.model_dump()), execution.perRoundCaps.model_dump())
            runs.scopes.bind_request(conn, owner, attempt_id, factory_request_id(request.requestId))
            conn.execute(runs.experiments.insert().values(id=experiment_id, project_id=project_id,
                goal_version=command.expectedVersion, hypothesis=agreement.objective,
                conditions={'evaluation': agreement.evaluation, 'stopConditions': agreement.stopConditions,
                            'resourceRefs': agreement.resourceRefs}, created_at=now()))
            conn.execute(runs.attempts.insert().values(id=attempt_id, experiment_id=experiment_id,
                allocation_id=attempt_id, request=request.model_dump()))
            content_id = runs.records.start(owner, project_id, command.expectedVersion, experiment_id, attempt_id, agreement)
            result = {'startRecordId': content_id, 'projectId': project_id, 'goalVersion': command.expectedVersion,
                'experimentId': experiment_id, 'attemptId': attempt_id, 'scopeId': scope_id,
                'allocationId': attempt_id, 'request': request.model_dump()}
            fingerprint = digest({'action': 'start', 'project': project_id, **command.model_dump(exclude={'requestId'})})
            return runs.projects.db.record(conn, runs.projects.commands, owner, command.requestId,
                fingerprint, 'research.start', result)
