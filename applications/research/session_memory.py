"""Personal preferences in Agno's native store, selected by the research owner."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from agno.db.schemas import UserMemory
from agent_factory.personal_tool_contract import ToolInvocationError
from agent_factory.store import digest


MEMORY_TOOLS = {'research_find_memories', 'research_remember', 'research_update_memory', 'research_forget_memory'}
MEMORY_WRITES = MEMORY_TOOLS - {'research_find_memories'}
PAGE_SIZE = 10


def _rejected(code):
    return ToolInvocationError(code, outcome='failed', stopped=True)


def _item(memory):
    return {'id': memory.memory_id, 'text': memory.memory, 'updatedAt': memory.updated_at or memory.created_at}


class ResearchSessionMemory:
    def __init__(self, sessions):
        self.sessions = sessions
        self.db = sessions.store.native_db

    def find(self, owner, values):
        page = values.get('page', 1)
        try:
            memories, total = self.db.get_user_memories(user_id=owner,
                search_content=values.get('query'), limit=PAGE_SIZE, page=page,
                sort_by='memory_id', sort_order='asc', deserialize=False)
        except Exception:
            raise _rejected('RESEARCH_MEMORY_UNAVAILABLE') from None
        return {'operation': 'find', 'memories': [_item(UserMemory.from_dict(item)) for item in memories],
                'page': page, 'total': total, 'nextPage': page + 1 if page * PAGE_SIZE < total else None}

    def prepare(self, context, call_id, name, values):
        sessions = self.sessions
        with sessions._write() as conn:
            _, turn, _ = sessions._execution(conn, context)
            body = deepcopy(turn['body'])
            operations = body.setdefault('memoryOperations', {})
            key = context.run_id + ':' + call_id
            original = operations.get(key)
            if original is None and operations.get(call_id, {}).get('runId') == context.run_id:
                original = operations[call_id]
            if original is not None:
                if original['runId'] != context.run_id or original['toolName'] != name or original['arguments'] != values:
                    raise _rejected('RESEARCH_MEMORY_REQUEST_CONFLICT')
                return original
            identifier = str(uuid5(NAMESPACE_URL, 'research-memory:' + context.user_id + ':'
                + context.run_id + ':' + call_id)) if name == 'research_remember' else values['memory_id']
            previous = None
            if name != 'research_remember':
                try:
                    previous = self.db.get_user_memory(identifier, user_id=context.user_id)
                except Exception:
                    raise _rejected('RESEARCH_MEMORY_UNAVAILABLE') from None
                if previous is None:
                    raise _rejected('RESEARCH_MEMORY_NOT_FOUND')
            operation = {'runId': context.run_id, 'callId': call_id, 'toolName': name, 'arguments': deepcopy(values),
                         'memoryId': identifier, 'previous': _item(previous) if previous else None}
            operations[key] = operation
            sessions._save_turn(conn, turn, body)
            return operation

    @staticmethod
    def _marker(operation, call_id):
        return 'research-memory:' + operation['runId'] + ':' + call_id

    def execute(self, owner, call_id, operation, guard):
        guard()
        identifier, name = operation['memoryId'], operation['toolName']
        try:
            if name == 'research_forget_memory':
                self.db.delete_user_memory(identifier, user_id=owner)
            else:
                self.db.upsert_user_memory(UserMemory(memory_id=identifier, user_id=owner,
                    memory=operation['arguments']['memory'], input=self._marker(operation, call_id)))
            output = self.reconcile(owner, call_id, operation)
        except Exception:
            # The native transaction can have committed before its reply failed.
            raise ValueError('RESEARCH_MEMORY_OUTCOME_UNKNOWN') from None
        if output is None:
            raise ValueError('RESEARCH_MEMORY_OUTCOME_UNKNOWN')
        return output

    def reconcile(self, owner, call_id, operation):
        memory = self.db.get_user_memory(operation['memoryId'], user_id=owner)
        name = operation['toolName']
        if name == 'research_forget_memory':
            return ({'operation': 'forget', 'memory': operation['previous'],
                     'notice': '仅移除个人记忆；旧会话和摘要保留。'} if memory is None else None)
        if (memory is None or memory.memory != operation['arguments']['memory']
                or memory.input != self._marker(operation, call_id)):
            return None
        output = {'operation': 'remember' if name == 'research_remember' else 'update', 'memory': _item(memory)}
        if operation['previous'] is not None:
            output['previousText'] = operation['previous']['text']
        return output

    def observe(self, owner, turn, task, prefix):
        """Only inspect original memory IDs; never repeat a memory mutation."""
        store = self.sessions.store
        effects = {item['effect_key']: item for item in store.effects(task['id'])}
        for operation_key, operation in turn['body'].get('memoryOperations', {}).items():
            call_id = operation.get('callId', operation_key)
            key = prefix + call_id
            effect = effects.get(operation['runId'] + ':' + key)
            if operation['runId'] != task['run_id'] or effect is None:
                continue
            confirming_saved = (effect['status'] == 'DONE'
                and (effect.get('result') or {}).get('outcome') == 'completed'
                and (effect.get('result') or {}).get('reconciled') is not True
                and turn['body'].get('blockReason') == 'RESEARCH_RESTART_REQUIRES_RECONCILIATION')
            if effect['status'] != 'UNKNOWN' and not confirming_saved:
                continue
            request = {'ownerId': owner, 'taskId': task['id'], 'sessionId': turn['session_id'],
                'turnId': turn['id'], 'toolName': operation['toolName'], 'callId': call_id,
                'arguments': operation['arguments']}
            original = store.sql('SELECT fingerprint FROM af_effects WHERE effect_key=:key '
                'AND task_id=:task AND run_id=:run', key=effect['effect_key'], task=task['id'], run=task['run_id'])
            if len(original) != 1 or original[0]['fingerprint'] != digest(request):
                continue
            try:
                output = self.reconcile(owner, call_id, operation)
                if output is None or confirming_saved and output != effect['result']['output']:
                    continue
                receipt = {'outcome': 'completed', 'output': output, 'reconciled': True}
                store.effect_complete(task['run_id'], key, receipt)
            except Exception:
                continue
            store.event(task['id'], 'research_tool_finished', '已核对原记忆操作，未重新执行',
                {'toolName': operation['toolName'], 'callId': call_id,
                 'operation': operation['toolName'].removeprefix('research_'), **receipt})
