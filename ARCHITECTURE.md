# Architecture

Agent Factory is a chat application for a trusted small team, built on Agno AgentOS 3.1.0 and PostgreSQL. The browser opens a conversation; models, tools, credentials and SSH connections live in Settings. An Agent chooses useful tools and subassistants from the user's goal.

## Implementation

- `platform/agent_factory` provides identity, personal/shared resource configuration and the thin connection to Agno execution.
- `applications/research` stores conversations, optional project goals, personal preferences, curated research records and team questions.
- `deployment/agent_factory_server` installs the research application in the service.
- `web` provides the single chat and settings interface.

Agno owns model/tool execution, streaming, PostgreSQL queue tickets, cancellation and continuation. A small dispatcher selects the current user's model for a native run; the shared Agent's model is never mutated to another user's credentials. Research and personal tools become native Functions directly.

The conversation is submitted with its goal, context and model connection. It does not first create or publish materials, applications, capability manifests or budget scopes. Subassistants inherit their parent's model and tools and run through the same native queue.

An application starts work through `ApplicationRuns` with its goal, request ID and execution inputs. The task stores the inputs needed to run or recover it. Repeating a request retrieves the original task; reusing its ID with different inputs reports a conflict. Teams can keep a business plan, approval rules or policy revisions in their application and check them there. Older tasks still load their execution inputs from their original plan records.

### Installing application behavior

An application's installation function registers callbacks under the same name it passes to `ApplicationRuns`. For example, a notes app can give the Agent its own lookup tool:

```python
from agent_factory.application_runtime import ApplicationRuntime, ApplicationTools

def install(state):
    state['application_runtimes']['notes'] = ApplicationRuntime(
        tools=lambda context, execution, agent: ApplicationTools([lookup_note], include_personal=False),
    )
```

Here `lookup_note` is an Agno Function supplied by the app. Each callback is optional and synchronous.

- `tools(context, execution, agent)` returns the functions for this run. Set `include_personal=True` (the default) to also load the owner's SSH, MCP and CLI tools.
- `instructions(context, execution)` returns the full list of instruction strings. Call `execution_instructions(execution, inputs)` to include the saved instructions, goal and input values.
- `prepare_history(context, execution, session, agent)` prepares history at run start and during recovery of a queue attempt with saved observations. Ordinary native continuation uses its saved messages.
- `before_model(context, execution, messages, auxiliary, *, auxiliary_request=False)` can modify messages or raise an error before a provider call. This includes auxiliary calls for summaries or compression. `auxiliary()` creates an owner-bound model with chat emission disabled. An asynchronous provider call runs this callback in a worker thread.

`execution` contains saved task inputs. Agno supplies the `RunContext`, `AgentSession` and `Agent`. An application that already records external tool effects can supply its `effect_prefixes` so queue recovery recognizes `run_id + ':' + prefix + tool_call_id`. If a retry cannot match recorded effects to saved tool calls, it reports an error before starting a new attempt. The research application shows the full implementation in [its runtime module](applications/research/runtime.py).

Tasks remember whether they use application callbacks. After a deployment they use the currently installed implementation. If a required implementation is missing, the task reports the application name and the error. Plain tasks keep their default behavior. Historical research tasks retain their research binding, and child tasks inherit the parent's choice. Applications that need version-specific behavior can record the version in their own inputs.

Files use Agno CodingTools. The configured session workspace is a default directory, not a file-access boundary; absolute research paths are supported. Shell execution alone uses the existing cancellable process helper. MCP uses the official SDK with Agno tool discovery. SSH uses system OpenSSH; configured remote Agno agents use AgentOSClient. Optional research records and shared answers do not impose a fixed research sequence.

## Data and maintenance

User/resource associations, actual errors and user-requested stopping remain functional requirements. Removed services do not delete historical database rows, credentials or user files. Older design and verification documents describe their recorded revisions; they are not a description of the current implementation.

The former manual Factory assembly, review, workflow custody, resource lease, budget, deployment-manifest and storage-administration layers are retired. Their duplicate interfaces and dedicated checks are removed. See [Development checks](docs/DEVELOPMENT_CHECKS.md) for the current static commands and actual-use verification scope.
