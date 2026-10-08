"""Trusted native Workflow decision-step bridge to existing material dispatch."""
from copy import copy
from typing import Callable

from agno.exceptions import InputCheckError
from agno.run import RunContext
from agno.run.agent import RunOutput

from .model_dispatch import DelegatingModel


class WorkflowDecisionModel(DelegatingModel):
    def __init__(self, bindings, *, workflow_id: str, step_id: str, agent_id: str,
                 validator: Callable[[RunOutput, dict, dict], RunContext]):
        if not callable(validator) or any(type(value) is not str or not value or len(value) > 200
                                         for value in (workflow_id, step_id, agent_id)):
            raise ValueError('A trusted workflow step binding is required')
        super().__init__(bindings)
        self.workflow_id, self.step_id, self.agent_id = workflow_id, step_id, agent_id
        self.validator = validator

    def _prepare_selection(self, arguments, kwargs, *, streaming=False):
        index = 6 if streaming else 5
        original = kwargs.get('run_response')
        if original is None and len(arguments) > index:
            original = arguments[index]
        if not isinstance(original, RunOutput) or original.agent_id != self.agent_id or not original.run_id:
            raise InputCheckError('Trusted workflow decision identity required')

        def validated_root():
            store = self.bindings.store
            task = store.task(original.session_id, original.user_id)
            plan = store.plan(task['plan_id'], original.user_id)
            root = self.validator(original, task, plan)
            if (not isinstance(root, RunContext) or not root.run_id or not root.session_id or not root.user_id
                    or root.run_id == original.run_id or root.session_id != original.session_id
                    or root.user_id != original.user_id):
                raise InputCheckError('Trusted workflow root binding required')
            # Agno assigns lineage after the step returns. If supplied, it must agree;
            # absent lineage is never used as authority. The operator validator owns
            # current registered step, queue, plan, owner and envelope checks.
            if (original.parent_run_id not in (None, root.run_id)
                    or original.workflow_id not in (None, self.workflow_id)
                    or original.workflow_step_id != (root.metadata or {}).get('factory_native_step_id')):
                raise InputCheckError('Workflow decision lineage differs')
            return root

        root = validated_root()
        proxy = copy(original)
        proxy.run_id = root.run_id
        proxy.session_state = root.session_state
        forwarded = dict(kwargs)
        positional = list(arguments)
        if len(positional) > index:
            positional[index] = proxy
            forwarded.pop('run_response', None)
        else:
            forwarded['run_response'] = proxy
        prepared = super()._prepare_selection(tuple(positional), forwarded, streaming=streaming)
        response, plan, context, current, local_current, binding = prepared

        def checked_current():
            latest = validated_root()
            if (latest.run_id, latest.session_id, latest.user_id, latest.session_state, latest.metadata) != (
                    root.run_id, root.session_id, root.user_id, root.session_state, root.metadata):
                raise InputCheckError('Workflow root binding changed')
            current()

        return (response, plan, context, checked_current, local_current, binding), original

    def _complete_selection(self, prepared):
        root_prepared, original = prepared
        root_prepared[3]()
        model = super()._complete_selection(root_prepared)
        original.model = root_prepared[0].model
        original.model_provider = root_prepared[0].model_provider
        return model
