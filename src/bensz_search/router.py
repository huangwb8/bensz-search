"""Execution owns one deadline, one attempt per tool and one estimated cost reservation."""

import asyncio
import time
from uuid import uuid4

from litellm.llms.base_llm.search.transformation import SearchResponse

from .filters import filter_results, provider_options
from .fusion import fuse
from .health import Health
from .intent import analyze
from .models import SearchRequest
from .planner import NoProviders, Planner
from .telemetry import Telemetry


class SearchFailed(Exception):
    def __init__(self, message="Search providers could not return usable results", status_code=502):
        super().__init__(message)
        self.status_code = status_code


def failure_category(error):
    status = getattr(error, "status_code", None)
    if status in {401, 403}:
        return "auth"
    if status == 402:
        return "quota"
    if status == 429:
        return "rate_limit"
    if (
        isinstance(error, (TimeoutError, asyncio.TimeoutError))
        or status == 408
        or "timeout" in type(error).__name__.lower()
    ):
        return "timeout"
    if status is not None and 400 <= status < 500:
        return "bad_request"
    if isinstance(error, (ValueError, TypeError)):
        return "invalid_response"
    return "unavailable"


class SmartRouter:
    def __init__(self, registry, call, health=None, telemetry=None):
        self.registry, self.call = registry, call
        self.health, self.telemetry = health or Health(), telemetry or Telemetry()
        self.planner = Planner(registry, self.health)

    async def search(self, request: SearchRequest, allowed: set[str], context=None):
        task = analyze(request)
        try:
            plan = self.planner.plan(task, allowed, request.fusion)
        except NoProviders as error:
            raise SearchFailed(str(error), 503) from error
        request_id = str(uuid4())
        deadline = time.monotonic() + plan.timeout_ms / 1000
        claimed, buckets, attempts = set(), {}, []
        reserved_cost = 0.0
        multiplier = len(request.query) if isinstance(request.query, list) else 1
        all_entries = plan.providers + plan.fallbacks
        # Reserve ownership of primaries before parallel branches can claim fallbacks.
        primary_names = {entry.name for entry in plan.providers}
        base = dict(context or {})
        for name in (
            "model",
            "search_tool_name",
            "custom_llm_provider",
            "search_provider",
            "api_key",
            "api_base",
            "litellm_logging_obj",
            "litellm_call_id",
            "fallbacks",
            "num_retries",
            "max_retries",
        ):
            base.pop(name, None)

        async def execute(primary):
            nonlocal reserved_cost
            candidates = [primary] + plan.fallbacks
            for entry in candidates:
                name = entry.name
                if name in claimed or (name != primary.name and name in primary_names):
                    continue
                capability = self.registry.providers[name]
                cost = capability.estimated_cost_usd * multiplier
                remaining = deadline - time.monotonic()
                if remaining <= 0 or reserved_cost + cost > plan.max_cost + 1e-12:
                    continue
                if not self.health.claim(name):
                    continue
                # No await between eligibility, claim and reservation: atomic in this event loop.
                claimed.add(name)
                reserved_cost += cost
                attempt = {
                    "provider": name,
                    "status": "pending",
                    "fallback": name != primary.name,
                    "estimated_cost_usd": cost,
                    "latency_ms": 0,
                    "result_count": 0,
                }
                attempts.append(attempt)
                started = time.monotonic()
                try:
                    kwargs = dict(base)
                    if "litellm_metadata" in kwargs:
                        kwargs["litellm_metadata"] = dict(kwargs["litellm_metadata"] or {})
                    metadata = dict(kwargs.get("metadata") or {})
                    metadata.update(
                        {
                            "model_group": name,
                            "smart_search_request_id": request_id,
                            "smart_search_intent": task.intent,
                        }
                    )
                    kwargs.update(
                        query=request.query,
                        search_tool_name=name,
                        model=name,
                        max_results=entry.count,
                        metadata=metadata,
                        num_retries=0,
                        max_retries=0,
                        fallbacks=[],
                        disable_fallbacks=True,
                        context_window_fallbacks=[],
                        content_policy_fallbacks=[],
                        timeout=min(capability.timeout_ms / 1000, remaining),
                        litellm_call_id=str(uuid4()),
                    )
                    if request.search_domain_filter:
                        kwargs["search_domain_filter"] = request.search_domain_filter
                    if request.country:
                        kwargs["country"] = request.country
                    if request.max_tokens_per_page is not None:
                        kwargs["max_tokens_per_page"] = request.max_tokens_per_page
                    kwargs.update(provider_options(capability.provider, task))
                    if capability.intent_engines.get(task.intent):
                        kwargs["engines"] = ",".join(capability.intent_engines[task.intent])
                    raw = await asyncio.wait_for(
                        self.call(**kwargs), min(capability.timeout_ms / 1000, remaining)
                    )
                    response = raw if isinstance(raw, SearchResponse) else SearchResponse.model_validate(raw)
                    rows = filter_results(response.results, task, request.search_domain_filter)[: entry.count]
                    attempt["result_count"] = len(rows)
                    attempt["status"] = "success" if rows else "empty"
                    if rows:
                        buckets[name] = rows
                        attempt["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
                        self.health.success(name, attempt["latency_ms"])
                        break
                    self.health.failure(name, "empty")
                except asyncio.CancelledError:
                    attempt["status"] = "timeout"
                    self.health.failure(name, "timeout")
                    raise
                except Exception as error:
                    category = failure_category(error)
                    attempt["status"] = category
                    self.health.failure(name, category)
                    if category == "bad_request":
                        break
                finally:
                    attempt["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
                    self.health.release(name)

        pending = [asyncio.create_task(execute(entry)) for entry in plan.providers]
        try:
            await asyncio.wait_for(asyncio.gather(*pending), max(0.001, deadline - time.monotonic()))
        except TimeoutError:
            pass
        finally:
            for job in pending:
                if not job.done():
                    job.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        # Stable provider order, independent of network completion speed.
        ordered = {entry.name: buckets[entry.name] for entry in all_entries if entry.name in buckets}
        results, trace = fuse(
            ordered,
            {e.name: e.weight for e in all_entries},
            {n: p.source_family for n, p in self.registry.providers.items()},
            plan.fusion,
            request.max_results,
        )
        event = self.telemetry.record(
            request_id, task, plan, attempts, ordered, round(reserved_cost, 8), trace
        )
        if not results:
            raise SearchFailed()
        response = SearchResponse(results=results)
        response._hidden_params["smart_search_request_id"] = request_id
        if request.debug:
            response.debug = {
                **event,
                "task": task.model_dump(exclude={"query", "caller_profile"}),
                "plan": plan.model_dump(),
                "fusion": trace,
                "partial_success": any(a["status"] != "success" for a in attempts),
                "cost_basis": "configured conservative estimate; not provider billing",
            }
        return response
