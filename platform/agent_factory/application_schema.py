"""Versioned application declarations. V1 is frozen for immutable compatibility.

V2 carries neutral factory ceilings and declarative application-owned config.
Neither config nor its schema can register code, authority, or credentials.
"""
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator
from .native_component import NativeWorkflowPin
from .material_governance import PinnedRef
from .input_schema import validate_input_schema, validate_input_values

class LegacyBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")
    toolCalls: int = Field(default=8, strict=True, ge=1, le=128)
    maxDepth: int = Field(default=2, strict=True, ge=1, le=8)
    maxChildren: int = Field(default=4, strict=True, ge=1, le=64)
    experimentSeconds: int = Field(default=8, strict=True, ge=1, le=600)
    outputBytes: int = Field(default=65536, strict=True, ge=1024, le=1048576)


class LegacyTaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    askScopeBelowLength: int = Field(default=0, strict=True, ge=0, le=2000)
    experimentDurationSeconds: int = Field(default=5, strict=True, ge=1, le=600)


class MaterialChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["skill", "tool", "prompt", "knowledge", "model", "environment"]
    defaultRef: PinnedRef
    allowedRefs: list[PinnedRef] = Field(min_length=1, max_length=8)


class ConnectionRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    kind: Literal["model", "tool", "knowledge", "environment", "orx"]
    requiredCapabilities: list[str] = Field(default_factory=list, max_length=30)
    required: StrictBool = True


class ModeDefinition(BaseModel):
    nativeComponent: NativeWorkflowPin | None = None
    inputSchema: dict[str, Any] | None = None

    @field_validator("inputSchema")
    @classmethod
    def checked_input_schema(cls, value):
        return validate_input_schema(value) if value is not None else None

    model_config = ConfigDict(extra="forbid")
    materialRefs: list[PinnedRef] = Field(min_length=1, max_length=30)
    materialChoices: dict[str, MaterialChoice] = Field(default_factory=dict, max_length=12)
    capabilities: list[str] = Field(min_length=1, max_length=30)
    budget: LegacyBudget = Field(default_factory=LegacyBudget)
    config: LegacyTaskConfig = Field(default_factory=LegacyTaskConfig)
    toolOrder: list[str] = Field(default_factory=list, max_length=30)
    connectionRequirements: list[ConnectionRequirement] = Field(default_factory=list, max_length=12)


class ApplicationDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    discoveryKeywords: list[str] = Field(default_factory=list, max_length=30)
    defaultForDiscovery: StrictBool = False
    defaultMode: str = Field(default="literature", min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    modes: dict[str, ModeDefinition] = Field(min_length=1, max_length=8)


class Budget(BaseModel):
    """Neutral per-operation resource ceiling, independent of workload domain."""
    model_config = ConfigDict(extra="forbid")
    toolCalls: int = Field(default=8, strict=True, ge=1, le=128)
    maxDepth: int = Field(default=2, strict=True, ge=1, le=8)
    maxChildren: int = Field(default=4, strict=True, ge=1, le=64)
    operationSeconds: int = Field(default=8, strict=True, ge=1, le=600)
    outputBytes: int = Field(default=65536, strict=True, ge=1024, le=1048576)


class ModeDefinitionV2(ModeDefinition):
    budget: Budget = Field(default_factory=Budget)
    configSchema: dict[str, Any] = Field(default_factory=lambda: {
        "type": "object", "properties": {}, "additionalProperties": False})
    config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def checked_config(self):
        self.configSchema = validate_input_schema(self.configSchema)
        self.config = validate_input_values(self.configSchema, self.config)
        # This is an inert application payload, never an execution envelope.
        reserved = {"capabilities", "permissions", "budget", "credentials", "connectionRefs",
                    "executionBindings", "materialRefs", "toolOrder", "sample"}
        if reserved & set(self.configSchema["properties"]):
            raise ValueError("Application configuration cannot declare factory authority fields")
        return self


class ApplicationDefinitionV2(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contractVersion: Literal[2]
    id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    discoveryKeywords: list[str] = Field(default_factory=list, max_length=30)
    defaultForDiscovery: StrictBool = False
    defaultMode: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    modes: dict[str, ModeDefinitionV2] = Field(min_length=1, max_length=8)


def definition_model(value):
    # Absence is deliberately v1: injecting a marker would change stored hashes.
    if "contractVersion" not in value:
        return ApplicationDefinition
    if type(value["contractVersion"]) is not int or value["contractVersion"] != 2:
        raise ValueError("Unsupported application contract version")
    return ApplicationDefinitionV2


def budget_limits(settings, contract_version=1):
    return {"toolCalls": settings.max_tool_calls, "maxDepth": 2, "maxChildren": 4,
            "operationSeconds" if contract_version == 2 else "experimentSeconds": settings.experiment_timeout_seconds,
            "outputBytes": settings.experiment_output_bytes}


def task_config(application, mode, goal, tools, budget):
    if application.get("contractVersion", 1) == 2:
        return {"sample": goal, "toolOrder": tools,
                "applicationConfig": validate_input_values(mode["configSchema"], mode["config"])}
    return {"askScope": "ask_scope" in tools and len(goal) < mode["config"]["askScopeBelowLength"],
            "sample": goal, "experimentDurationSeconds": min(mode["config"]["experimentDurationSeconds"], budget["experimentSeconds"]),
            "toolOrder": tools}


def time_budget_key(plan):
    """Never silently fall back to a wider v1 ceiling for a v2 plan."""
    if "contractVersion" in plan:
        if type(plan["contractVersion"]) is not int or plan["contractVersion"] != 2:
            raise ValueError("Unsupported plan contract version")
        key, forbidden = "operationSeconds", "experimentSeconds"
    else:
        key, forbidden = "experimentSeconds", "operationSeconds"
    if forbidden in plan.get("budget", {}):
        raise ValueError("Mixed budget contract fields are forbidden")
    return key


def time_budget(plan, default):
    key = time_budget_key(plan)
    value = plan.get("budget", {}).get(key)
    if plan.get("contractVersion", 1) == 2 and (type(value) is not int or value <= 0):
        raise ValueError("V2 plan requires a positive operationSeconds ceiling")
    return value if value is not None else default
