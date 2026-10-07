"""Native bensz-search provider; delegate only to a cooperating v1 HTTP service."""

import asyncio
import json
import time
from urllib.parse import urlsplit

import httpx
from litellm.llms.base_llm.search.transformation import SearchResponse, SearchResult

from .federation import FederationError, context, valid_id
from .filters import filter_results
from .fusion import fuse
from .intent import analyze
from .models import SearchRequest
from .openai_search import resolve
from .protocol_models import SearchEnvelope

RESPONSE_LIMIT = 512000


def base_url(value):
    if not isinstance(value, str):
        raise ValueError("bensz-search requires an instance base URL")
    parts = urlsplit(value)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("bensz-search requires an HTTP(S) base URL without credentials")
    _ = parts.port
    if parts.path.rstrip("/").endswith(("/search", "/capabilities", "/mcp", "/bensz-search/v1")):
        raise ValueError("Use the instance base URL, not a search or protocol endpoint")
    return value.rstrip("/")


async def read_response(client, method, url, **kwargs):
    async with client.stream(method, url, **kwargs) as response:
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > RESPONSE_LIMIT:
                raise ValueError("Remote response exceeds the federation byte limit")
        if response.status_code >= 400:
            # Never expose the remote body, URLs or credentials in exceptions/logs.
            code = {
                401: "auth",
                403: "auth",
                402: "quota",
                429: "rate_limit",
                408: "timeout",
                508: "federation_loop",
            }.get(response.status_code, "unavailable")
            try:
                remote_code = json.loads(data).get("error", {}).get("code")
                if remote_code in {
                    "federation_loop",
                    "federation_depth_exceeded",
                    "call_budget_exceeded",
                    "invalid_federation_context",
                }:
                    code = remote_code
            except (ValueError, AttributeError):
                pass
            raise FederationError(code, response.status_code)
        if response.headers.get("x-bensz-search-federation") != "1" or not valid_id(
            response.headers.get("x-bensz-search-node")
        ):
            raise ValueError("Remote instance does not support bounded federation; upgrade it")
        return bytes(data), response.headers["x-bensz-search-node"]


def normalize(envelope, node):
    rows = []
    for item in envelope.results:
        try:
            parts = urlsplit(item.url)
            _ = parts.port
        except ValueError:
            continue
        if parts.username or parts.password:
            continue
        sources = []
        for source in item.sources[:30]:
            sources.append(
                {
                    "source_family": source.source_family,
                    "snippet_kind": source.snippet_kind,
                    "date": source.date,
                    "upstream_tool_id": source.upstream_tool_id or source.tool_id,
                    "upstream_call_id": source.upstream_call_id or source.call_id,
                    "upstream_rank": source.upstream_rank or source.rank,
                    "instance_path": [node, *source.instance_path][:8],
                }
            )
        if not sources:
            sources = [
                {
                    "source_family": "bensz_search_unknown",
                    "snippet_kind": item.snippet_kind,
                    "date": item.date,
                    "instance_path": [node],
                }
            ]
        rows.append(
            SearchResult(
                title=item.title,
                url=item.url,
                snippet=item.snippet,
                date=item.date,
                snippet_kind=item.snippet_kind,
                upstream_sources=sources,
                source_families=sorted({s["source_family"] for s in sources}) or ["bensz_search_unknown"],
            )
        )
    return rows


async def search(params, kwargs):
    base = base_url(resolve(params.get("api_base")))
    key = resolve(params.get("api_key"))
    if not key:
        raise ValueError("bensz-search requires a remote access key")
    request = SearchRequest.model_validate(
        {
            k: kwargs[k]
            for k in (
                "query",
                "max_results",
                "profile",
                "profile_prompt",
                "constraints",
                "fusion",
                "search_domain_filter",
                "country",
                "max_tokens_per_page",
            )
            if kwargs.get(k) is not None
        }
    )
    task = kwargs.get("_federation_task") or analyze(request)
    ctx = context()
    timeout_ms = min(
        int(float(params.get("timeout", 15)) * 1000),
        int(float(kwargs.get("timeout") or 60) * 1000),
        ctx.remaining_ms(),
        task.latency_budget_ms,
    )
    cost = min(float(kwargs.get("_federation_cost_budget", task.cost_budget_usd)), ctx.cost_budget_usd)
    budget = min(int(kwargs.get("_federation_call_budget", ctx.remaining_calls - 1)), ctx.remaining_calls - 1)
    queries = request.query if isinstance(request.query, list) else [request.query]
    # Every list query is a distinct delegation edge as well as a remote subtree.
    budget -= len(queries) - 1
    if budget < len(queries):
        raise FederationError("call_budget_exceeded")
    deadline = time.monotonic() + timeout_ms / 1000

    async def run():
        buckets = {}
        partial = False
        async with httpx.AsyncClient(
            follow_redirects=False, trust_env=False, timeout=timeout_ms / 1000
        ) as client:
            # Discovery proves remote support and permission before spending on search.
            headers = {"Authorization": "Bearer " + key, **ctx.headers(timeout_ms, budget, cost)}
            _, node = await read_response(
                client, "GET", base + "/bensz-search/v1/capabilities", headers=headers
            )
            if node in ctx.path:
                raise FederationError("federation_loop", 508)
            for index, query in enumerate(queries):
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining < 100:
                    raise FederationError("timeout", 408)
                per_cost = cost / len(queries)
                headers = {
                    "Authorization": "Bearer " + key,
                    **ctx.headers(remaining, budget // len(queries), per_cost),
                }
                payload = {
                    "mode": "auto",
                    "query": query,
                    "max_results": request.max_results,
                    "fusion": request.fusion,
                    "profile": {"intent": task.intent, "domain": task.domain},
                    "constraints": {
                        "freshness": task.freshness,
                        "authority": task.authority_requirement,
                        "recall": task.recall_requirement,
                        "precision": task.precision_requirement,
                        "semantic": task.semantic_requirement,
                        "source_diversity": task.source_diversity,
                        "cost": "low" if task.prefer_single else "auto",
                        "latency_budget_ms": remaining,
                        "cost_budget_usd": per_cost,
                    },
                    "options": {
                        "search_domain_filter": request.search_domain_filter,
                        "country": request.country,
                    },
                    "fallback_on_empty": True,
                }
                raw, response_node = await read_response(
                    client, "POST", base + "/bensz-search/v1/search", headers=headers, json=payload
                )
                if node != response_node:
                    raise ValueError("Remote workers have inconsistent instance IDs")
                envelope = SearchEnvelope.model_validate_json(raw)
                if envelope.protocol_version != "1.0" or envelope.status not in {
                    "success",
                    "partial_success",
                    "no_results",
                }:
                    codes = {e.get("error_code") for e in envelope.execution}
                    code = next(
                        (
                            c
                            for c in (
                                "federation_loop",
                                "federation_depth_exceeded",
                                "call_budget_exceeded",
                                "timeout",
                                "auth",
                                "quota",
                                "rate_limit",
                            )
                            if c in codes
                        ),
                        "unavailable",
                    )
                    raise FederationError(code)
                if envelope.status == "no_results" and envelope.results:
                    raise ValueError("Remote no_results response contains results")
                partial = partial or envelope.status == "partial_success"
                buckets[str(index)] = filter_results(
                    normalize(envelope, node), task, request.search_domain_filter
                )
        rows, _ = fuse(buckets, {}, {}, "rrf", request.max_results)
        return SearchResponse(results=rows, federation_partial=partial)

    return await asyncio.wait_for(run(), timeout_ms / 1000)
