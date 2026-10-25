"""Selected original CLI output, never model-granted publication authority."""
import json
import math
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, JSON, inspect, select, text

from agent_factory.input_schema import bounded_json
from agent_factory.material_governance import PinnedRef

Role = Literal['metrics', 'source', 'run_recipe']
FieldName = Annotated[str, Field(min_length=1, max_length=100, pattern=r'^[A-Za-z_][A-Za-z0-9_]*$')]


class EvidenceSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    toolMaterial: PinnedRef
    fields: dict[Role, FieldName] = Field(min_length=1, max_length=3)


def _metrics(value):
    return isinstance(value, dict) and bool(value) and all(
        isinstance(key, str) and (type(item) in {str, bool, int}
            or type(item) is float and math.isfinite(item)) for key, item in value.items())


def _valid_value(role, value):
    if role == 'source':
        return isinstance(value, str) and bool(value.strip())
    if role == 'metrics':
        return _metrics(value)
    if not isinstance(value, dict):
        return False
    command, dependencies, data = value.get('command'), value.get('dependencies'), value.get('data')
    return (isinstance(command, list) and bool(command)
            and all(isinstance(item, str) and item.strip() for item in command)
            and (isinstance(dependencies, str) and bool(dependencies.strip())
                 or isinstance(dependencies, list) and all(isinstance(item, str) and item.strip() for item in dependencies))
            and (isinstance(data, (list, dict)) or isinstance(data, str) and bool(data.strip()))
            and _metrics(value.get('expected')))


class ResearchEvidence:
    def __init__(self, runs):
        self.runs = runs
        self.attempts = runs.attempts
        with runs.projects.db.write() as conn:
            if 'selection' not in {c['name'] for c in inspect(conn).get_columns(self.attempts.name)}:
                conn.execute(text('ALTER TABLE research_attempts ADD COLUMN selection JSON'))
            if 'selection' not in self.attempts.c:
                self.attempts.append_column(Column('selection', JSON))

    def capture(self, conn, owner, attempt, operation, configured, application_context):
        old = conn.execute(select(self.attempts.c.selection).where(self.attempts.c.id == attempt['id'])).scalar_one()
        if old is not None:
            return old
        selection = {'artifacts': [], 'items': [], 'missingEvidence': [], 'provenance': None}
        if configured is None:
            selection['missingEvidence'] = ['evidence_not_configured']
        elif operation['observation']['state'] != 'COMPLETED':
            selection['missingEvidence'] = ['original_cli_result_unavailable']
        else:
            output = operation['observation']['output']
            try:
                original = self.runs.runs.tool_results(owner, output['taskId'], output['runId'])
            except HTTPException as error:
                if error.status_code != 409 or error.detail != 'APPLICATION_CLI_PROVENANCE_UNAVAILABLE':
                    raise
                selection['missingEvidence'] = ['cli_provenance_unavailable']
            else:
                if original['materialRef'] != configured.toolMaterial.model_dump():
                    raise HTTPException(409, 'RESEARCH_EVIDENCE_MATERIAL_MISMATCH')
                selection['provenance'] = {key: original[key] for key in
                    ('taskId', 'runId', 'planId', 'materialRef', 'operationRef', 'binding')}
                if not original['receipts']:
                    selection['missingEvidence'].append('original_cli_result_unavailable')
                for receipt in original['receipts']:
                    for role, field in configured.fields.items():
                        value = receipt['output']
                        if not isinstance(value, dict) or field not in value:
                            selection['missingEvidence'].append(role)
                            continue
                        selected_value = value[field]
                        if not _valid_value(role, selected_value):
                            selection['missingEvidence'].append(role)
                            continue
                        if len(selection['artifacts']) == 20:
                            raise HTTPException(422, 'RESEARCH_EVIDENCE_ATTACHMENT_LIMIT')
                        selected = bounded_json({'role': role, 'value': selected_value,
                            'effectKey': receipt['effectKey'], 'field': field,
                            'provenance': selection['provenance'], 'verificationStatus': 'producer_declared'}, maximum=16384)
                        artifact = application_context.write_artifact(
                            'research-' + role + '-' + str(len(selection['artifacts'])) + '.json',
                            json.dumps(selected, ensure_ascii=False, allow_nan=False))
                        reference = {'taskId': artifact['jobId'], 'artifactId': artifact['id'], 'sha256': artifact['sha256']}
                        selection['artifacts'].append(reference)
                        selection['items'].append({'role': role, 'reference': reference, 'size': artifact['size'],
                            'effectKey': receipt['effectKey'], 'field': field})
                present = {item['role'] for item in selection['items']}
                selection['missingEvidence'] = sorted(set(selection['missingEvidence']) | ({'metrics', 'source', 'run_recipe'} - present))
        conn.execute(self.attempts.update().where(self.attempts.c.id == attempt['id']).values(selection=selection))
        return selection
