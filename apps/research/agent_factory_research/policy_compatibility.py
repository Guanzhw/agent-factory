"""Research ancestry proofs and historical display over public plan policy.

Ordinary member submission and historical approval immutability remain owned by
PlanPolicyService. This class neither creates approvals nor adds execution roles.
"""
from typing import Any, Mapping
from fastapi import HTTPException
from agent_factory.plan_policy import PlanPolicyService
from .services import services_for


class ResearchPlanPolicyService(PlanPolicyService):
    def extend_application_tool_catalog(self, catalog):
        if self.store.settings.source_synthesis_enabled:
            return {**catalog, 'save_literature_synthesis': 'research:read'}
        return catalog

    def _plan_summary(self, plan):
        summary = super()._plan_summary(plan)
        if plan.get('application') == 'personal-orx-project-create-v1':
            from .personal_orx_projects import project_review_summary
            project_creation = project_review_summary(plan)
            if project_creation is not None:
                summary['projectCreation'] = project_creation
        return summary

    def require_execution(self, owner: str, plan: str | Mapping, *, run_context: Any = None,
                          scientific_child_id: str | None = None) -> dict:
        if scientific_child_id is None:
            return super().require_execution(owner, plan, run_context=run_context)
        return self._require_scientific_authorization(owner, plan, run_context=run_context,
                                                     scientific_child_id=scientific_child_id)

    def _require_scientific_authorization(self, owner, plan, *, scientific_child_id,
                                         run_context=None, scientific_custody=False):
        def ancestors(current_plan):
            return self._scientific_ancestors(owner, current_plan, scientific_child_id,
                                              run_context, scientific_custody)
        return super()._require_authorization(owner, plan, run_context=run_context,
                                             ancestor_resolver=ancestors)

    def _scientific_ancestors(self, owner, current_plan, scientific_child_id,
                             run_context, scientific_custody):
        if not current_plan.get('delegation'):
            raise HTTPException(409, 'Scientific placement requires a delegated source plan')
        service = services_for(self.store).remote_scientific
        child = self.store.task(scientific_child_id, owner)
        if (service is None or run_context is not None or child.get('run_id') or child['plan_id'] != current_plan['id']
                or child['cancel_requested'] or bool(child['terminal']) != scientific_custody
                or self.store.has_failures(child['id'])):
            raise HTTPException(409, 'Scientific placement requires its original metadata child')
        if scientific_custody and current_plan.get('mode') != 'remote-scientific-training':
            raise HTTPException(409, 'Scientific custody is limited to completed original training')
        row = service._row(owner, scientific_child_id)
        service.validate_source(current_plan, row['body']['envelope'])
        parent = self.store.task(row['parent_id'], owner)
        link = self.store.delegation._link(scientific_child_id)
        if (not link or link['parent_id'] != parent['id'] or link['root_id'] != parent['id']
                or type(link['depth']) is not int or link['depth'] != 1 or link['owner_id'] != owner
                or link['child_id'] != child['id'] or link['plan_id'] != current_plan['id']):
            raise HTTPException(409, 'Scientific placement ancestry changed')
        _, ancestors = self.store.delegation._mandate(owner, parent)
        return ancestors

    def require_scientific_custody(self, owner: str, plan: str | Mapping, *, scientific_child_id: str) -> dict:
        """Read one completed training child's custody under its current parent.

        This deliberately returns no execution approval. Native admission and
        tool entrypoints continue through require_execution, which rejects the
        completed child.
        """
        checked = self._require_scientific_authorization(owner, plan, scientific_child_id=scientific_child_id,
                                                         scientific_custody=True)
        current = self._plan(owner, plan)
        bindings = getattr(self.store, 'execution_bindings', None)
        if bindings is not None:
            bindings.recheck(current)
        governance = getattr(self.store, 'material_governance', None)
        if governance is not None:
            governance.require_materials_current(current)
        for guard in tuple(self.store.execution_guards.values()):
            guard(owner, current, None, None)
        return {'custodyReadable': True, 'ownerId': owner, 'planId': current['id'],
                'planDigest': checked['planDigest']}

