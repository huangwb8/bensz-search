"""One execution primitive for legacy rules and the versioned search protocol."""

import asyncio
import re
import time
from dataclasses import dataclass, field
from uuid import uuid4

import httpx
from litellm.llms.base_llm.search.transformation import SearchResponse

from .filters import filter_results


def failure_category(error):
    status = getattr(error, "status_code", None)
    if status in {401, 403}:
        return "auth"
    # Serper reports exhausted credits as HTTP 400; LiteLLM keeps the JSON
    # message in BadRequestError but replaces the original response body.
    serper_quota = (
        status == 400
        and getattr(error, "llm_provider", None) == "serper"
        and re.search(r'"message"\s*:\s*"not enough credits"', str(error), re.IGNORECASE)
    )
    if status == 402 or serper_quota:
        return "quota"
    if status == 429:
        return "rate_limit"
    if isinstance(error, TimeoutError) or status == 408 or "timeout" in type(error).__name__.lower():
        return "timeout"
    if status is not None and 400 <= status < 500:
        return "bad_request"
    if isinstance(error, (ValueError, TypeError)):
        return "invalid_response"
    if isinstance(error, httpx.TransportError) or type(error).__name__ in {
        "APIConnectionError",
        "ConnectError",
        "NetworkError",
    }:
        return "network"
    return "unavailable"


@dataclass
class ExecutionCall:
    call_id: str
    tool_id: str
    query: str | list[str]
    count: int
    weight: float = 1
    engine_id: str | None = None
    options: dict = field(default_factory=dict)
    domains: list[str] = field(default_factory=list)
    task: object = None
    fallbacks: list = field(default_factory=list)


async def execute(
    router,
    calls,
    timeout_ms,
    max_cost,
    request_id,
    context=None,
    concurrency=3,
    fallback_on_empty=True,
    empty_is_failure=False,
):
    deadline = time.monotonic() + timeout_ms / 1000
    semaphore = asyncio.Semaphore(concurrency)
    claimed, buckets, attempts = set(), {}, []
    reserved = 0.0
    primaries = {c.call_id for c in calls}
    costs = {
        c.call_id: router.registry.providers[c.tool_id].estimated_cost_usd
        * (len(c.query) if isinstance(c.query, list) else 1)
        for primary in calls
        for c in [primary, *primary.fallbacks]
    }
    # A fast failing branch cannot spend an unstarted primary's cost reservation.
    waiting = {c.call_id: costs[c.call_id] for c in calls}
    base = {k: v for k, v in (context or {}).items() if k in {"metadata", "litellm_metadata", "user"}}

    async def branch(primary):
        nonlocal reserved
        for item in [primary, *primary.fallbacks]:
            if item.call_id in claimed or (item.call_id != primary.call_id and item.call_id in primaries):
                continue
            async with semaphore:
                if item.call_id in claimed:
                    continue
                capability = router.registry.providers[item.tool_id]
                remaining = deadline - time.monotonic()
                cost = costs[item.call_id]
                held = sum(v for k, v in waiting.items() if k != primary.call_id)
                attempt = {
                    "call_id": item.call_id,
                    "provider": item.tool_id,
                    "engine_id": item.engine_id,
                    "status": "skipped",
                    "fallback": item.call_id != primary.call_id,
                    "estimated_cost_usd": 0,
                    "latency_ms": 0,
                    "result_count": 0,
                }
                claimed.add(item.call_id)
                attempts.append(attempt)
                waiting.pop(primary.call_id, None)
                if remaining <= 0:
                    attempt["error_code"] = "timeout"
                    continue
                if reserved + held + cost > max_cost + 1e-12:
                    attempt["error_code"] = "budget_exceeded"
                    continue
                if not router.health.claim(item.tool_id):
                    attempt["error_code"] = "circuit_open"
                    continue
                reserved += cost
                attempt.update(status="pending", estimated_cost_usd=cost)
                started = time.monotonic()
                try:
                    kwargs = dict(base)
                    for key in ("metadata", "litellm_metadata"):
                        if key in kwargs:
                            kwargs[key] = dict(kwargs[key] or {})
                    metadata = dict(kwargs.get("metadata") or {})
                    metadata.update(
                        model_group=item.tool_id,
                        smart_search_request_id=request_id,
                        smart_search_intent=getattr(item.task, "intent", "planned"),
                    )
                    kwargs.update(item.options)
                    kwargs.update(
                        query=item.query,
                        search_tool_name=item.tool_id,
                        model=item.tool_id,
                        max_results=item.count,
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
                    if item.engine_id:
                        kwargs["engines"] = item.engine_id
                    raw = await asyncio.wait_for(router.call(**kwargs), kwargs["timeout"])
                    response = raw if isinstance(raw, SearchResponse) else SearchResponse.model_validate(raw)
                    for rank, row in enumerate(response.results, 1):
                        row.original_rank = rank
                    rows = filter_results(response.results, item.task, item.domains)[: item.count]
                    attempt.update(result_count=len(rows), status="success" if rows else "empty")
                    if rows:
                        buckets[item.call_id] = rows
                    latency = round((time.monotonic() - started) * 1000, 2)
                    if rows or not empty_is_failure:
                        router.health.success(item.tool_id, latency)
                    else:
                        router.health.failure(item.tool_id, "empty")
                    if rows or not fallback_on_empty:
                        break
                except asyncio.CancelledError:
                    attempt.update(status="timeout", error_code="timeout")
                    router.health.release(item.tool_id)
                    raise
                except Exception as error:
                    category = failure_category(error)
                    attempt.update(status=category, error_code=category)
                    router.health.failure(item.tool_id, category)
                    if category == "bad_request":
                        break
                finally:
                    attempt["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
                    router.health.release(item.tool_id)

    pending = [asyncio.create_task(branch(c)) for c in calls]
    try:
        await asyncio.wait_for(asyncio.gather(*pending), max(0.001, deadline - time.monotonic()))
    except TimeoutError:
        pass
    finally:
        for job in pending:
            if not job.done():
                job.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
    return buckets, attempts, round(reserved, 8)
