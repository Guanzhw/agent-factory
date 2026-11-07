"""Read native effects and the current conversation without a second runtime."""
def effect_unresolved(effect, store=None):
    return effect.get('status') not in {'DONE', 'CANCELLED'}


def runtime_custody_held(store, task_id):
    sessions = getattr(store, 'research_sessions', None)
    return bool(sessions is not None and sessions.task_held(store, store.task(task_id)))


def execution_classification(plan):
    return {'executionKind': 'native-agent', 'syntheticFixture': False}
