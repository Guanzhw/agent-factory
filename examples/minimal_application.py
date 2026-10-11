"""Synthetic application logic over interface v1; no Store or BindingContext.

An operator registers this reviewed function as an Agno Step with zero retries,
an exact implementation hash, governed tools/materials and normal admission.
This example does not configure credentials or run a model.
"""
import json

from agno.workflow.types import StepOutput

from agent_factory.application_interface import ApplicationExecutionContext


def summarize(step_input, *, application_context: ApplicationExecutionContext):
    goal = application_context.inputs['goal']
    result = {'goal': goal, 'synthetic': True, 'scientificConclusionVerified': False}
    artifact = application_context.write_artifact('summary.json', json.dumps(result))
    application_context.emit_event('summary_ready', 'Synthetic summary saved', {'artifactId': artifact['id']})
    return StepOutput(content={'artifactId': artifact['id'], **result})
