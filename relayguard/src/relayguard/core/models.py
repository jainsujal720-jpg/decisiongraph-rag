from enum import StrEnum

from pydantic import BaseModel, Field


class TaskClass(StrEnum):
    SIMPLE = "simple"
    MODERATE = "moderate"
    INVOLVED = "involved"
    COMPLEX = "complex"
    HEAVY = "heavy"
    LONG_CONTEXT = "long_context"


class ChatRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1)
    system_prompt: str | None = Field(default=None, max_length=20_000)
    response_schema: dict | None = None
    task_class: TaskClass | None = None
    simulate_primary_failure: bool = False
    requires_privileged_access: bool = False


class RouteDecision(BaseModel):
    task_class: TaskClass
    primary_model: str
    fallback_model: str
    reason: str


class UsageSummary(BaseModel):
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    token_cost_usd: float | None = None
    note: str = "Estimate from provider tokens and configured rates; not an invoice."


class RoutingTrace(BaseModel):
    source: str = "rules"
    jev_mode: str = "off"
    jev_class: str | None = None
    jev_confidence: float | None = None
    jev_probability: float | None = None
    jev_input_tokens: int | None = None
    jev_cost_usd: float | None = None
    reason: str = ""


class GovernanceSummary(BaseModel):
    tenant_spend_usd: float
    tenant_budget_usd: float
    remaining_budget_usd: float
    retry_count: int
    circuit_open: bool


class ChatResponse(BaseModel):
    answer: str
    route: RouteDecision
    served_by: str
    served_model: str
    fallback_used: bool
    cost_usd: float
    request_id: str
    governance: GovernanceSummary
    usage: UsageSummary | None = None
    routing: RoutingTrace | None = None
