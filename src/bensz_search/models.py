"""Validated contracts; auto controls deliberately exclude provider credentials."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Intent = Literal["auto", "general", "news", "academic", "deep", "people", "coding"]
Level = Literal["auto", "low", "medium", "high"]
Freshness = Literal["auto", "any", "day", "week", "month", "year"]
Fusion = Literal["none", "rrf", "weighted_rrf"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class CallerProfile(StrictModel):
    type: str = "auto"
    domain: str = "auto"
    intent: Intent = "auto"


class Constraints(StrictModel):
    freshness: Freshness = "auto"
    authority: Level = "auto"
    recall: Level = "auto"
    precision: Level = "auto"
    semantic: Level = "auto"
    source_diversity: Level = "auto"
    latency: Level = "auto"
    cost: Level = "auto"
    latency_budget_ms: int | None = Field(default=None, ge=100, le=60000)
    cost_budget_usd: float | None = Field(default=None, ge=0, le=10)


class SearchRequest(StrictModel):
    query: str | list[str]
    search_tool_name: str = "auto"
    profile: CallerProfile = Field(default_factory=CallerProfile)
    profile_prompt: str | None = Field(default=None, max_length=4000)
    constraints: Constraints = Field(default_factory=Constraints)
    debug: bool = False
    fusion: Fusion = "weighted_rrf"
    max_results: int = Field(default=10, ge=1, le=20)
    search_domain_filter: list[str] = Field(default_factory=list, max_length=20)
    max_tokens_per_page: int | None = Field(default=None, ge=1, le=100000)
    country: str | None = Field(default=None, min_length=2, max_length=2)

    @field_validator("query")
    @classmethod
    def valid_query(cls, value):
        queries = value if isinstance(value, list) else [value]
        if not queries or len(queries) > 10 or any(not q.strip() or len(q) > 10000 for q in queries):
            raise ValueError("query must contain 1–10 nonempty strings of at most 10000 characters")
        return value

    @field_validator("search_domain_filter")
    @classmethod
    def valid_domains(cls, value):
        if any(not d.lstrip("-") or any(c in d for c in "/:@? ") for d in value):
            raise ValueError("domain filters must be hostnames, optionally prefixed with -")
        return value


class SearchTask(StrictModel):
    query: str | list[str]
    intent: Intent = "auto"
    domain: str = "auto"
    freshness: Freshness = "any"
    authority_requirement: Level = "auto"
    recall_requirement: Level = "auto"
    precision_requirement: Level = "auto"
    semantic_requirement: Level = "auto"
    source_diversity: Level = "auto"
    latency_budget_ms: int = Field(default=8000, ge=100, le=60000)
    cost_budget_usd: float = Field(default=0.02, ge=0, le=10)
    result_count: int = Field(default=10, ge=1, le=20)
    caller_profile: CallerProfile = Field(default_factory=CallerProfile)
    routing_reason: list[str] = Field(default_factory=list)
    prefer_single: bool = False


class ProviderCapabilities(StrictModel):
    provider: str
    source_family: str
    capabilities: dict[str, float]
    features: list[str] = Field(default_factory=list)
    intent_engines: dict[str, list[str]] = Field(default_factory=dict)
    quality: float = Field(default=1, gt=0, le=1)
    cost_class: Literal["low", "medium", "high"] = "medium"
    latency_class: Literal["low", "medium", "high"] = "medium"
    estimated_cost_usd: float = Field(ge=0, le=10)
    timeout_ms: int = Field(default=4000, ge=100, le=60000)

    @field_validator("capabilities")
    @classmethod
    def valid_capabilities(cls, value):
        if not value or any(not 0 <= score <= 1 for score in value.values()):
            raise ValueError("capabilities must be finite scores between 0 and 1")
        return value


class PlanEntry(StrictModel):
    name: str
    weight: float = Field(gt=0)
    count: int = Field(ge=1, le=20)


class SearchPlan(StrictModel):
    strategy: Literal["single", "parallel"]
    providers: list[PlanEntry]
    fallbacks: list[PlanEntry] = Field(default_factory=list)
    fusion: Fusion = "weighted_rrf"
    timeout_ms: int
    max_cost: float
    routing_reason: list[str]


class SearchResultFeedback(StrictModel):
    request_id: str = Field(min_length=1, max_length=100)
    event: Literal["clicked", "cited", "used", "repeated", "deeper_search", "accepted"]
    result_url: str | None = Field(default=None, max_length=2000)
