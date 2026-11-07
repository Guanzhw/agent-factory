"""Select an available owner model for the native chat Agent."""
from copy import deepcopy

from fastapi import HTTPException

from .session_tools import COLLABORATION_TOOLS
from .session_memory import MEMORY_TOOLS


MODE = 'autonomous'
INSTRUCTIONS = (
    "Complete the user's goal using the supplied conversation and corrections. "
    "Reply in the user's language. Choose useful tools and next actions yourself; "
    "there is no mandatory research sequence or preliminary checklist. "
    "Use files and commands directly when useful. Delegate independent work with research_delegate, "
    "continue other useful work, and use research_wait_child before incorporating its result. "
    "Children share the workspace; give them distinct files when they edit concurrently. "
    "When given a subtask, complete that subtask. Project, record, preference and colleague tools are optional. "
    "Report actual results, files and failures clearly, distinguishing observations from conclusions."
)


def rejected(code, message, status=409):
    return HTTPException(status, {'code': code, 'message': message})


class ResearchSessionSetup:
    def __init__(self, store, connections, models, tools):
        self.store, self.connections, self.models, self.tools = store, connections, models, tools

    def options(self, owner):
        models = [{key: item[key] for key in ('connectionRef', 'provider', 'model', 'available', 'contextWindow', 'autoCompactTokenLimit') if key in item}
                  for item in self.models.list(owner)]
        available = set(self.tools.available_tools)
        workspace = bool(getattr(self.tools, 'workspace_root', None))
        commands = bool(getattr(self.tools, 'host_commands', False))
        code = 'RESEARCH_MODEL_REQUIRED' if not any(item.get('available') for item in models) else None
        return {'available': code is None, 'unavailableCode': code, 'models': models,
            'collaboration': {'available': COLLABORATION_TOOLS <= available},
            'memory': {'available': MEMORY_TOOLS <= available},
            'workspace': {'configured': workspace, 'hostCommands': commands,
                          'isolation': 'host-user-not-os-sandbox'},
            'accounting': {'tokenMetered': False, 'costMetered': False}}

    def prepare(self, owner, model_ref):
        options = self.options(owner)
        if not options['available']:
            raise rejected(options['unavailableCode'], '请先配置可用模型。')
        model = next((item for item in options['models'] if item.get('connectionRef') == model_ref and item.get('available')), None)
        if model is None:
            raise rejected('RESEARCH_MODEL_UNAVAILABLE', '所选模型连接当前不可用。')
        return {'connectionRefs': {'model': model_ref}, 'model': deepcopy(model),
                'autonomousCollaboration': options['collaboration']['available'],
                'personalMemory': options['memory']['available']}
