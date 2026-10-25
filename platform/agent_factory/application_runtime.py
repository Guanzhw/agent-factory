"""Static original-operation ownership, not an execution or service container.

Selectors are trusted exact identities from persisted plans/effects. Absent
hooks for a declared owner retain custody. Unclaimed core bindings retain their
existing semantics; unknown historical bindings cannot invent an application.
"""
from dataclasses import dataclass
from copy import deepcopy
from typing import Any

from fastapi import HTTPException

from .native_component import NativeWorkflowPin


@dataclass(frozen=True)
class RuntimeOwner:
    identifier: str
    hooks: Any
    finalizes: bool = False


class ApplicationRuntimeRegistry:
    def __init__(self, store):
        self.store = store
        self._owners: dict[str, RuntimeOwner] = {}
        self._bindings = {}
        self._applications = {}
        self._legacy = {}
        self._effects = {}
        self._native_components = {}

    def __bool__(self):
        return bool(self._owners)

    def register(self, owner_id, hooks, *, bindings=(), applications=(), legacy_applications=(), effects=(),
                 native_components=(), finalizes=False):
        if not isinstance(owner_id, str) or not owner_id or owner_id in self._owners:
            raise ValueError('Duplicate or invalid application runtime owner')
        declarations = ((self._bindings, tuple(bindings)), (self._applications, tuple(applications)),
                        (self._legacy, tuple(legacy_applications)), (self._effects, tuple(effects)),
                        (self._native_components, tuple(native_components)))
        for mapping, keys in declarations:
            if len(set(keys)) != len(keys) or any(key in mapping for key in keys):
                raise ValueError('Duplicate application runtime identity')
        if any(not isinstance(key, tuple) or len(key) != 3 or key[0] not in {'model', 'tool', 'knowledge', 'environment'}
               or not all(isinstance(part, str) and part for part in key) for key in bindings):
            raise ValueError('Invalid exact runtime binding')
        if any(not isinstance(key, tuple) or len(key) != 2 or not isinstance(key[0], str)
               or type(key[1]) is not int or key[1] < 1 for key in applications):
            raise ValueError('Invalid exact application reference')
        if any(not isinstance(key, str) or not key for key in (*legacy_applications, *effects)):
            raise ValueError('Invalid original operation identity')
        for key in native_components:
            if not isinstance(key, tuple) or len(key) != 4:
                raise ValueError('Invalid exact native component reference')
            NativeWorkflowPin.model_validate(dict(zip(('kind', 'id', 'revision', 'sha256'), key)))
        owner = RuntimeOwner(owner_id, hooks, finalizes)
        self._owners[owner_id] = owner
        for mapping, keys in declarations:
            mapping.update((key, owner_id) for key in keys)
        return owner

    @staticmethod
    def _specs(plan):
        binding = plan.get('executionBindings') or {}
        for kind, field in (('model', 'model'), ('environment', 'environment'), ('tool', 'tools'), ('knowledge', 'knowledge')):
            values = binding.get(field) or []
            if isinstance(values, dict):
                values = [values]
            for spec in values:
                if isinstance(spec, dict):
                    yield kind, spec

    def _plan(self, task):
        return self.store.plan(task['plan_id'], task['owner_id'])

    def owners(self, task, *, effects=True) -> tuple[RuntimeOwner, ...]:
        if not self._owners:
            return ()
        plan = self._plan(task)
        selected = {self._bindings[(kind, spec.get('adapterId'), spec.get('revision'))]
                    for kind, spec in self._specs(plan)
                    if (kind, spec.get('adapterId'), spec.get('revision')) in self._bindings}
        if not selected:
            ref = plan.get('applicationRef') or {}
            key = (ref.get('id'), ref.get('version'))
            if key in self._applications:
                selected.add(self._applications[key])
            elif not ref and not plan.get('executionBindings') and plan.get('application') in self._legacy:
                selected.add(self._legacy[plan['application']])
        component = plan.get('nativeComponent') or {}
        key = tuple(component.get(field) for field in ('kind', 'id', 'revision', 'sha256'))
        if key in self._native_components:
            selected.add(self._native_components[key])
        if effects and task.get('run_id'):
            prefix = task['run_id'] + ':'
            for effect in self.store.effects(task['id']):
                key = effect.get('effect_key', '')
                if key.startswith(prefix) and key[len(prefix):] in self._effects:
                    selected.add(self._effects[key[len(prefix):]])
        return tuple(self._owners[key] for key in sorted(selected))

    @staticmethod
    def callback(owner, name):
        return getattr(owner.hooks, name, None) if owner.hooks is not None else None

    def finalization_context(self, task):
        owners = [owner for owner in self.owners(task) if owner.finalizes]
        if len(owners) > 1:
            raise HTTPException(409, 'APPLICATION_FINALIZATION_OWNER: completion responsibility overlaps')
        if not owners:
            return None
        callback = self.callback(owners[0], 'finalization_context')
        if callback is not None:
            return callback

        def unavailable(*_):
            raise HTTPException(409, 'APPLICATION_FINALIZATION_UNAVAILABLE: retain original completion responsibility')
        return unavailable

    def task_held(self, task):
        for owner in self.owners(task):
            callback = self.callback(owner, 'task_held')
            if owner.hooks is None or callback is not None and callback(self.store, task):
                return True
        return False

    def effect_held(self, effect):
        if not self._owners:
            return False
        key = effect.get('effect_key', '')
        run, separator, local = key.partition(':')
        if not separator:
            return False  # An unclaimed core effect format is not an app declaration.
        task = self.store.task(run)
        if task.get('run_id') != run:
            return True
        declared = self._effects.get(local)
        owners = (self._owners[declared],) if declared else self.owners(task, effects=False)
        return any(owner.hooks is None or declared and self.callback(owner, 'effect_held') is None
                   or (callback := self.callback(owner, 'effect_held')) is not None
                   and callback(effect) for owner in owners)

    def ended_reason(self, task):
        for owner in self.owners(task):
            if owner.hooks is None:
                return 'application-runtime-owner-unavailable'
            callback = self.callback(owner, 'ended_reason')
            if callback is not None and (reason := callback(self.store, task)):
                return reason
        return None

    def mark_cancel(self, task):
        # Caller owns the same metadata transaction as the task cancellation.
        for owner in self.owners(task):
            callback = self.callback(owner, 'mark_cancel')
            if callback is not None:
                callback(self.store, task['id'])

    async def cancel(self, task):
        errors = []
        for owner in self.owners(task):
            callback = self.callback(owner, 'cancel')
            if callback is not None:
                try:
                    await callback(self.store, task)
                except Exception as error:
                    errors.append(error)
        if errors:
            raise errors[0]

    def waiting_control(self, api, task, snapshot):
        waits, active = {}, False
        for owner in self.owners(task):
            callback = self.callback(owner, 'waiting_control')
            if callback is not None:
                waits[owner.identifier], current = callback(api, task, snapshot)
                active = active or current
        return waits, active

    async def project_detail(self, api, task, plan, snapshot, events, job, waits):
        evidence, evaluation = {}, None
        original = deepcopy(job)
        for owner in self.owners(task):
            callback = self.callback(owner, 'project_detail')
            if callback is not None:
                projected = deepcopy(original)
                extra, result = await callback(api, task, plan, snapshot, events, projected, (waits or {}).get(owner.identifier))
                self._merge_job(original, projected, job)
                if evidence.keys() & extra.keys() or evaluation is not None and result is not None:
                    raise HTTPException(409, 'APPLICATION_PROJECTION_CONFLICT: original owners overlap')
                evidence.update(extra)
                if result is not None:
                    evaluation = result
        return evidence, evaluation

    @classmethod
    def _merge_job(cls, original, projected, result):
        """Merge independent fields; conflicting scalar ownership is not order."""
        missing = object()
        for key in original.keys() | projected.keys():
            before, after = original.get(key, missing), projected.get(key, missing)
            if before == after:
                continue
            current = result.get(key, missing)
            if isinstance(before, dict) and isinstance(after, dict) and isinstance(current, dict):
                cls._merge_job(before, after, current)
            elif key == 'allowedActions' and all(isinstance(value, list) for value in (before, after, current)):
                result[key] = list(dict.fromkeys([value for value in current if value not in before or value in after]
                                                + [value for value in after if value not in before]))
            elif current != before and current != after:
                raise HTTPException(409, 'APPLICATION_PROJECTION_CONFLICT: original job field owners overlap')
            elif after is missing:
                result.pop(key, None)
            else:
                result[key] = deepcopy(after)

    def summary_status(self, observer, task, status):
        projected = set()
        for owner in self.owners(task):
            if owner.hooks is None:
                return 'unknown'
            callback = self.callback(owner, 'summary_status')
            if callback is not None:
                value = callback(observer, task, status)
                if value != status:
                    projected.add(value)
        return next(iter(projected)) if len(projected) == 1 else 'unknown' if projected else status

    async def observe_waits(self, observer, task):
        for owner in self.owners(task):
            callback = self.callback(owner, 'observe_waits')
            if callback is not None:
                await callback(observer, task)

    def control(self, task, name, *, tool_name=None):
        owners = self.owners(task)
        if tool_name is not None:
            exact = {self._bindings.get((kind, spec.get('adapterId'), spec.get('revision')))
                     for kind, spec in self._specs(self._plan(task))
                     if kind == 'tool' and spec.get('toolName') == tool_name}
            exact.discard(None)
            if exact:
                owners = tuple(owner for owner in owners if owner.identifier in exact)
        callbacks = [self.callback(owner, name) for owner in owners if self.callback(owner, name) is not None]
        if len(callbacks) > 1 or any(owner.hooks is None for owner in owners):
            raise HTTPException(409, 'APPLICATION_CONTROL_OWNER: original owner unavailable or ambiguous')
        return callbacks[0] if callbacks else None
