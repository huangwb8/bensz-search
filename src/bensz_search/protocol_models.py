"""Public v1 data contract; no transport or model vendor fields."""

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .models import CallerProfile, Constraints, Fusion, SearchRequest, StrictModel

PROTOCOL_VERSION = "1.0"
INTERACTION_VERSION = "1.0"


class QueryOptions(StrictModel):
    dialect: Literal["keywords", "natural_language"] = "keywords"
    search_domain_filter: list[str] = Field(default_factory=list, max_length=20)
    country: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    query_language: str | None = Field(
        default=None, pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$", max_length=35
    )
    result_language: str | None = Field(
        default=None, pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$", max_length=35
    )
    safe_search: Literal["off", "moderate", "strict"] | None = None

    @field_validator("search_domain_filter")
    @classmethod
    def valid_domains(cls, value):
        return SearchRequest.valid_domains(value)


class CallSpec(StrictModel):
    call_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    tool_id: str = Field(min_length=1, max_length=64)
    engine_id: str | None = Field(default=None, min_length=1, max_length=80)
    query: str = Field(min_length=1, max_length=10000)
    max_results: int = Field(default=10, ge=1, le=20)
    options: QueryOptions = Field(default_factory=QueryOptions)

    @field_validator("query")
    @classmethod
    def valid_query(cls, value):
        if not value.strip():
            raise ValueError("query cannot be blank")
        return value


class PlannedCall(CallSpec):
    fallbacks: list[CallSpec] = Field(default_factory=list, max_length=9)


class ProtocolSearch(StrictModel):
    mode: Literal["auto", "planned"] = "auto"
    query: str | None = Field(default=None, min_length=1, max_length=10000)
    calls: list[PlannedCall] = Field(default_factory=list, max_length=10)
    registry_revision: str | None = Field(default=None, max_length=128)
    constraints: Constraints = Field(default_factory=Constraints)
    profile: CallerProfile = Field(default_factory=CallerProfile)
    options: QueryOptions = Field(default_factory=QueryOptions)
    fusion: Fusion = "weighted_rrf"
    max_results: int = Field(default=10, ge=1, le=20)
    dry_run: bool = False
    fallback_on_empty: bool = False
    response_language: str = Field(
        default="en", pattern=r"^[a-zA-Z]{2,3}(-[a-zA-Z0-9]{2,8})*$", max_length=35
    )

    @model_validator(mode="after")
    def consistent_mode(self):
        if self.mode == "auto" and (not self.query or not self.query.strip() or self.calls):
            raise ValueError("auto requires a nonblank query and no calls")
        if self.mode == "planned" and (not self.calls or self.query is not None):
            raise ValueError("planned requires calls and no top-level query")
        if self.mode == "planned" and self.options != QueryOptions():
            raise ValueError("planned options belong to each call")
        ids = [c.call_id for c in self.calls for c in [c, *c.fallbacks]]
        if len(ids) != len(set(ids)):
            raise ValueError("call_id must be unique including fallbacks")
        if len(ids) > 10:
            raise ValueError("at most 10 physical calls including fallbacks")
        return self


class ProtocolError(StrictModel):
    code: str
    field: str | None = None
    message: str
    retryable: bool = False
    suggestion: str | None = None


class Availability(StrictModel):
    enabled: bool
    credentials_ready: bool
    cooling_down: bool
    recent_probe_at: str | None = None
    recent_probe_result: str = "unknown"


class QueryContract(StrictModel):
    input_forms: list[str]
    max_query_length: int
    max_queries_per_call: int
    max_results: int
    operators: dict[str, Literal["supported", "unsupported", "unknown"]]
    options: dict[str, Literal["native", "post_filter", "advisory", "unsupported", "unknown"]]
    examples: list[str]
    common_errors: list[str]
    evidence: str
    last_verified: str
    verification_scope: str


class CapabilityLimits(StrictModel):
    max_calls: int
    concurrency: int
    max_snippet_chars: int
    max_response_bytes: int
    tenant_concurrency: int
    requests_per_minute: int
    max_results: int
    max_latency_ms: int
    state_scope: str
    strict_billing_budget: bool


class EngineCapability(StrictModel):
    engine_id: str
    selectable: bool
    query_contract: QueryContract
    evidence: str | None = None


class ToolCapability(StrictModel):
    tool_id: str
    provider_type: str
    engines: list[EngineCapability]
    tasks: dict[str, float]
    score_basis: str
    query_contract: QueryContract
    source_family: str
    independence_confidence: str
    independence_basis: str
    estimated_cost_usd: float
    cost_basis: str
    timeout_ms: int
    availability: Availability


class CapabilitySnapshot(StrictModel):
    protocol_version: str = PROTOCOL_VERSION
    interaction_version: str = INTERACTION_VERSION
    registry_revision: str
    generated_at: str
    cache_ttl_seconds: int
    limits: CapabilityLimits
    tools: list[ToolCapability]


class Source(StrictModel):
    call_id: str
    tool_id: str
    engine_id: str | None = None
    rank: int
    source_family: str
    independence_basis: str = "configured source family; independence not measured"
    snippet_kind: str
    date: str | None = None


class ProtocolResult(StrictModel):
    result_id: str
    title: str
    url: str
    canonical_identity: str
    aliases: list[str]
    snippet: str
    snippet_kind: str
    date: str | None = None
    sources: list[Source]
    fusion_score: float
    score_basis: str = "rank contribution; not factual confidence"
    content_trust: Literal["untrusted_external_content"] = "untrusted_external_content"
    dedup_basis: str = "canonical URL or conservative document identity"
    truncated: bool = False


class SearchEnvelope(StrictModel):
    protocol_version: str = PROTOCOL_VERSION
    request_id: str
    registry_revision: str | None = None
    status: Literal["success", "partial_success", "no_results", "failed", "validated"]
    results: list[ProtocolResult] = Field(default_factory=list)
    execution: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    estimated_cost_usd: float = 0
    cost_basis: str = "configured estimate including failed calls; not provider billing"
    error: ProtocolError | None = None
    truncated: bool = False
    constraints: dict = Field(default_factory=dict)
    cost_estimate: dict = Field(default_factory=dict)
