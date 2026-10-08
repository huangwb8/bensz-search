"""Shared protocol service used by HTTP and MCP; snapshots never contain secrets."""

import hashlib
import json
import os
import time
from datetime import UTC, datetime
from uuid import uuid4

from .executor import ExecutionCall, execute
from .federation import bounded_task
from .intent import analyze
from .models import SearchRequest
from .planner import NoProviders
from .protocol_models import (
    INTERACTION_VERSION,
    PROTOCOL_VERSION,
    CallSpec,
    ProtocolError,
    SearchEnvelope,
)
from .protocol_results import normalize_results
from .query_contracts import contract, map_options


class ProtocolFailure(Exception):
    def __init__(self, code, message, field=None, status_code=422, retryable=False, suggestion=None):
        self.error = ProtocolError(
            code=code, message=message, field=field, retryable=retryable, suggestion=suggestion
        )
        self.status_code = status_code
        super().__init__(message)

    def envelope(self, request_id=None):
        return SearchEnvelope(request_id=request_id or str(uuid4()), status="failed", error=self.error)


class ProtocolLimits:
    def __init__(self):
        self.max_calls = min(10, max(1, int(os.getenv("BENSZ_SEARCH_MAX_CALLS", "10"))))
        self.concurrency = min(10, max(1, int(os.getenv("BENSZ_SEARCH_CONCURRENCY", "3"))))
        self.max_snippet_chars = min(10000, max(100, int(os.getenv("BENSZ_SEARCH_SNIPPET_CHARS", "2000"))))
        self.max_response_bytes = max(32768, int(os.getenv("BENSZ_SEARCH_RESPONSE_BYTES", "128000")))
        self.tenant_concurrency = max(1, int(os.getenv("BENSZ_SEARCH_TENANT_CONCURRENCY", "4")))
        self.requests_per_minute = max(1, int(os.getenv("BENSZ_SEARCH_REQUESTS_PER_MINUTE", "60")))

    def public(self):
        return {
            **vars(self),
            "max_results": 20,
            "max_latency_ms": 60000,
            "state_scope": "single process",
            "strict_billing_budget": False,
        }


def snapshot_revision(router, allowed, limits):
    public = {
        n: p.model_dump(exclude={"engine_evidence"})
        for n, p in router.registry.providers.items()
        if n in allowed
    }
    # Include the router generation: credential/address rotation invalidates old plans
    # without hashing secrets or leaking other tenants' configurations.
    body = {"registry": public, "limits": limits.public(), "generation": router.generation}
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def capabilities(router, allowed, limits=None):
    limits = limits or ProtocolLimits()
    tools = []
    for name, p in sorted(router.registry.providers.items()):
        if name not in allowed:
            continue
        state = router.health.state(name)
        tools.append(
            {
                "tool_id": name,
                "provider_type": p.provider,
                "engines": [
                    {
                        "engine_id": e,
                        "selectable": True,
                        "query_contract": contract(p),
                        "evidence": "operator allowlist and verified instance metadata; adapter selection supported",
                    }
                    for e in p.verified_engines
                    if p.provider == "searxng" and p.engine_evidence
                ],
                "tasks": p.capabilities,
                "score_basis": "configured priors; not measured quality",
                "query_contract": contract(p),
                "source_family": p.source_family,
                "independence_confidence": "unknown",
                "independence_basis": "operator configuration",
                "estimated_cost_usd": p.estimated_cost_usd,
                "cost_basis": "configured estimate; not billing",
                "timeout_ms": p.timeout_ms,
                "availability": {
                    "enabled": True,
                    "credentials_ready": True,
                    "cooling_down": not router.health.available(name),
                    "recent_probe_at": state.observed_at,
                    "recent_probe_result": state.observed_result,
                },
            }
        )
    return {
        "protocol_version": PROTOCOL_VERSION,
        "interaction_version": INTERACTION_VERSION,
        "registry_revision": snapshot_revision(router, allowed, limits),
        "generated_at": datetime.now(UTC).isoformat(),
        "cache_ttl_seconds": 30,
        "limits": limits.public(),
        "tools": tools,
    }


class TenantLimiter:
    """Bounded process-local tenant admission, shared across the two transports."""

    def __init__(self):
        self.states = {}

    def enter(self, identity, limits):
        now = time.monotonic()
        state = self.states.get(identity)
        if state is None:
            self.states = {k: s for k, s in self.states.items() if s[0] > now - 60 or s[2]}
            if len(self.states) >= 10000:
                raise ProtocolFailure("rate_limit", "Tenant admission capacity reached", status_code=429)
            state = self.states.setdefault(identity, [now, 0, 0])
        if state[0] <= now - 60:
            state[0], state[1] = now, 0
        if state[1] >= limits.requests_per_minute or state[2] >= limits.tenant_concurrency:
            raise ProtocolFailure(
                "rate_limit", "Tenant request limit reached", status_code=429, retryable=True
            )
        state[1] += 1
        state[2] += 1

    def leave(self, identity):
        self.states[identity][2] -= 1


async def search(router, request, allowed, limits=None, context=None):
    limits = limits or ProtocolLimits()
    revision = snapshot_revision(router, allowed, limits)
    if request.registry_revision is not None and request.registry_revision != revision:
        raise ProtocolFailure(
            "stale_capabilities", "Capabilities changed; discover and replan", "registry_revision", 409, True
        )
    warnings = []
    task = bounded_task(
        analyze(
            SearchRequest(
                query=request.query or request.calls[0].query,
                profile=request.profile,
                constraints=request.constraints,
                max_results=request.max_results,
                fusion=request.fusion,
            )
        )
    )

    def validate_call(item, field):
        if item.tool_id not in allowed or item.tool_id not in router.registry.providers:
            raise ProtocolFailure(
                "tool_unavailable", "Tool is not enabled or authorized", field + ".tool_id", 403
            )
        p = router.registry.providers[item.tool_id]
        if item.engine_id and (
            p.provider != "searxng" or not p.engine_evidence or item.engine_id not in p.verified_engines
        ):
            raise ProtocolFailure(
                "engine_unavailable", "Engine selection has not been verified", field + ".engine_id"
            )
        if len(item.query) > p.query_max_length or item.options.dialect not in p.query_dialects:
            raise ProtocolFailure(
                "query_not_supported", "Query exceeds this tool's contract", field + ".query"
            )
        supported = contract(p)["options"]
        for key in ("country", "result_language", "safe_search"):
            if getattr(item.options, key) and supported[key] == "unsupported":
                raise ProtocolFailure(
                    "query_not_supported",
                    "Option is not supported by this adapter",
                    field + ".options." + key,
                )
        if item.options.query_language:
            warnings.append(
                {
                    "code": "advisory_query_language",
                    "call_id": item.call_id,
                    "message": "Query is sent unchanged; query language is advisory",
                }
            )
        if item.options.search_domain_filter or task.freshness not in {"any", "auto"}:
            warnings.append(
                {
                    "code": "post_filter",
                    "call_id": item.call_id,
                    "message": "Domain/date filters apply to returned candidates; unknown dates excluded",
                }
            )
        per_task = task.model_copy(update={"query": item.query})
        options = map_options(p, item.options, per_task)
        if p.provider == "bensz_search":
            options["fusion"] = request.fusion
        return ExecutionCall(
            item.call_id,
            item.tool_id,
            item.query,
            item.max_results,
            engine_id=item.engine_id,
            options=options,
            domains=item.options.search_domain_filter,
            task=per_task,
        )

    if request.mode == "planned":
        calls = []
        for index, item in enumerate(request.calls):
            entry = validate_call(item, f"calls.{index}")
            entry.fallbacks = [
                validate_call(c, f"calls.{index}.fallbacks.{i}") for i, c in enumerate(item.fallbacks)
            ]
            calls.append(entry)
    else:
        try:
            plan = router.planner.plan(task, allowed, request.fusion)
        except NoProviders as error:
            raise ProtocolFailure("no_providers", str(error), status_code=503) from error

        def rule_call(entry):
            item = validate_call(
                CallSpec(
                    call_id=entry.name,
                    tool_id=entry.name,
                    query=request.query,
                    max_results=entry.count,
                    options=request.options,
                ),
                "options",
            )
            item.weight = entry.weight
            engines = router.registry.providers[entry.name].intent_engines.get(task.intent)
            if engines:
                item.options["engines"] = ",".join(engines)
            return item

        calls = [rule_call(e) for e in plan.providers]
        # Rule fallback is bounded by the published physical call limit.
        fallbacks = [rule_call(e) for e in plan.fallbacks[: max(0, limits.max_calls - len(calls))]]
        for item in calls:
            item.fallbacks = fallbacks
    all_calls = {c.call_id: c for primary in calls for c in [primary, *primary.fallbacks]}
    if len(all_calls) > limits.max_calls:
        raise ProtocolFailure("call_limit", "Plan exceeds the physical call limit", "calls")
    primary_cost = sum(router.registry.providers[c.tool_id].estimated_cost_usd for c in calls)
    if primary_cost > task.cost_budget_usd + 1e-12:
        raise ProtocolFailure(
            "budget_exceeded", "Primary calls exceed the estimated budget", "constraints.cost_budget_usd"
        )
    envelope = SearchEnvelope(
        request_id=str(uuid4()), registry_revision=revision, status="validated", warnings=warnings
    )
    envelope.cost_estimate = {
        "primary_usd": primary_cost,
        "maximum_declared_usd": sum(
            router.registry.providers[c.tool_id].estimated_cost_usd for c in all_calls.values()
        ),
        "physical_call_limit": len(all_calls),
    }
    envelope.constraints = {
        "latency_budget_ms": task.latency_budget_ms,
        "cost_budget_usd": task.cost_budget_usd,
        "query_rewritten": False,
        "strict_billing_budget": False,
        "quality_constraints_basis": "routing preferences; quality not guaranteed",
    }
    if request.response_language != "en":
        envelope.warnings.append(
            {
                "code": "response_language_unsupported",
                "message": "Machine messages use English; query is never translated",
            }
        )
    if request.dry_run:
        envelope.estimated_cost_usd = primary_cost
        envelope.execution = [
            {
                "call_id": c.call_id,
                "tool_id": c.tool_id,
                "engine_id": c.engine_id,
                "status": "validated",
                "fallback": c.call_id not in {p.call_id for p in calls},
            }
            for c in all_calls.values()
        ]
        return envelope
    execution_started = time.monotonic()
    buckets, attempts, cost = await execute(
        router,
        calls,
        task.latency_budget_ms,
        task.cost_budget_usd,
        envelope.request_id,
        context,
        limits.concurrency,
        request.fallback_on_empty,
    )
    by_id = {a["call_id"]: a for a in attempts}
    for c in all_calls.values():
        a = by_id.get(c.call_id)
        envelope.execution.append(
            {
                "call_id": c.call_id,
                "tool_id": c.tool_id,
                "engine_id": c.engine_id,
                "status": a["status"] if a else "skipped",
                "error_code": a.get("error_code") if a else "not_needed",
                "fallback": c.call_id not in {p.call_id for p in calls},
                "latency_ms": a["latency_ms"] if a else 0,
                "result_count": a["result_count"] if a else 0,
                "estimated_cost_usd": a["estimated_cost_usd"] if a else 0,
                "executed": bool(a and a["status"] != "skipped"),
            }
        )
    envelope.results, result_warnings = normalize_results(
        buckets, all_calls, router.registry, request.fusion, request.max_results, limits.max_snippet_chars
    )
    envelope.warnings.extend(result_warnings)
    envelope.estimated_cost_usd = cost
    healthy = any(a["status"] in {"success", "partial_success", "empty"} for a in attempts)
    failed = any(a["status"] not in {"success", "empty"} for a in attempts)
    envelope.status = (
        ("partial_success" if failed else "success")
        if envelope.results
        else ("no_results" if healthy and not failed else "failed")
    )
    if envelope.status == "failed":
        envelope.error = ProtocolError(
            code="search_failed",
            message="No successful search results",
            retryable=True,
            suggestion="Inspect execution; discover capabilities before replanning",
        )
    if failed and request.mode == "planned":
        envelope.warnings.append(
            {
                "code": "replan_required",
                "message": "Only declared calls were attempted; discover and replan missing coverage",
            }
        )
    await router.telemetry.arecord_execution(
        envelope.request_id,
        "protocol",
        [
            {
                key: attempt[key]
                for key in (
                    "provider",
                    "status",
                    "fallback",
                    "latency_ms",
                    "result_count",
                    "estimated_cost_usd",
                )
            }
            for attempt in attempts
        ],
        len(envelope.results),
        cost,
        round((time.monotonic() - execution_started) * 1000, 2),
        ["Caller supplied plan" if request.mode == "planned" else "Rule based protocol routing"],
    )
    # No query or external content is copied into process-local metrics/logs.
    with router.telemetry.lock:
        router.telemetry.counts["protocol:requests"] += 1
        router.telemetry.counts["protocol:" + envelope.status] += 1
        for attempt in attempts:
            router.telemetry.counts["protocol:call:" + attempt["status"]] += 1
    while len(envelope.model_dump_json().encode()) > limits.max_response_bytes and envelope.results:
        if not envelope.truncated:
            envelope.warnings.append(
                {"code": "response_truncated", "message": "Response exceeded byte limit"}
            )
            envelope.truncated = True
        envelope.results.pop()
    if envelope.truncated:
        envelope.status = "partial_success" if envelope.results else "failed"
        if not envelope.results:
            envelope.error = ProtocolError(
                code="response_limit_exceeded", message="Results could not fit within the response byte limit"
            )
    return envelope
